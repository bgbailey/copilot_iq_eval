"""One bounded Option 1 demo, then exact Eventhouse/SQL readback; --verify-only never submits.

Note: For standard end-to-end verification, you can also run `python -m cfeval verify`.
"""

import argparse
import hashlib
import importlib
import json
import math
import re
import struct
import sys
import time
from pathlib import Path

from cfeval import runtime
from cfeval.cli import build_harness
from cfeval.clock import iso, utc_now
from cfeval.config import Settings
from cfeval.fabric_rest import app_tables
from cfeval.golden import golden_hash, load_golden
from cfeval.schema import TABLES
from setup_demo import ROOT, configured_settings, require_trace_progress, resolve_targets, sql_host


def _write_receipt(path, receipt):
    path.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def sql_driver(settings):
    try:
        module = importlib.import_module("pyodbc")
    except ImportError:
        raise RuntimeError(
            'SQL verification is required. Install: python -m pip install -e ".[sql]"; '
            "also install Microsoft ODBC Driver 18 for SQL Server. No verification was skipped."
        ) from None
    if settings.sql_odbc_driver not in module.drivers():
        raise RuntimeError(
            "SQL driver %r is missing. Install Microsoft ODBC Driver 18 for SQL Server "
            "for this OS/architecture; no verification was skipped." % settings.sql_odbc_driver
        )
    return module


def _brace(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


def sql_counts(settings, run_id, module):
    # The checked Entra token lives only in memory. Never add UID/PWD/Authentication to this connection.
    token = runtime.azure_cli_token("https://database.windows.net", settings=settings)
    runtime.inspect_acquired_token(
        token, "https://database.windows.net", settings.tenant_id, settings.operator_upn, settings.operator_object_id
    )
    raw = token.encode("utf-16-le")
    packed = struct.pack("<I", len(raw)) + raw
    connection_string = (
        "DRIVER=%s;SERVER=tcp:%s,1433;DATABASE=%s;Encrypt=yes;TrustServerCertificate=no;"
        "MARS_Connection=no;APP=cfeval-demo-readback;ApplicationIntent=ReadOnly;"
        % (
            _brace(settings.sql_odbc_driver),
            sql_host(settings.sql_endpoint_server),
            _brace(settings.sql_endpoint_database),
        )
    )
    connection = module.connect(connection_string, attrs_before={1256: packed}, timeout=30, autocommit=True)
    try:
        connection.timeout = 45
        cursor = connection.cursor()
        names = app_tables()
        visible = {
            r[0]
            for r in cursor.execute(
                "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = ? "
                "OPTION (LABEL='cfeval_demo_schema_readback')",
                settings.sql_schema,
            )
        }
        counts = {name: None for name in names}
        present = [name for name in names if name in visible]
        if present:
            query = " UNION ALL ".join(
                "SELECT '%s' AS TableName, COUNT_BIG(*) AS [RowCount] FROM [%s].[%s] WHERE [RunId] = ?"
                % (name, settings.sql_schema, name)
                for name in present
            )
            query += " OPTION (LABEL='cfeval_demo_run_count_readback')"
            counts.update({r[0]: int(r[1]) for r in cursor.execute(query, *([run_id] * len(present)))})
        return counts
    finally:
        connection.close()


def local_record(folder, run_id, mock):
    """Read JSONL as-is: late row versions count too; never rewrite/deduplicate evidence."""
    manifest = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    if manifest.get("run_id") != run_id or manifest.get("backends") != ["fabric-native"]:
        raise ValueError("Run manifest must identify this run and only the Option 1 backend")
    if (manifest.get("surface") == "simulated") != mock:
        raise ValueError("Use --mock only for a simulated run, never for a live publication check")
    rows, digests = {}, {}
    for table in TABLES:
        path = folder / ("%s.jsonl" % table)
        payload = path.read_bytes() if path.exists() else b""
        digests[table] = hashlib.sha256(payload).hexdigest()
        rows[table] = [json.loads(line) for line in payload.decode("utf-8").splitlines() if line.strip()]
        if any(r.get("RunId") != run_id for r in rows[table]):
            raise ValueError("%s contains rows for a different run" % table)
    receipt_path = folder / "rehearsal.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("state") != "recorded":
            raise ValueError("Original submission did not finish: preserve the run and inspect it; no automatic retry")
        if receipt.get("sha256") != digests:
            raise ValueError("Original JSONL changed after rehearsal; stop and inspect, never silently regrade")
        if receipt.get("sink_errors"):
            raise ValueError("Original publication reported errors; reconcile them manually, never auto-republish")
    counts = {table: len(data) for table, data in rows.items()}
    if any(count == 0 for count in counts.values()):
        raise ValueError("Incomplete local evidence: all seven tables, including DAX and scores, must be nonempty")
    run = rows["EvalRun"][-1]
    questions = {r["QuestionId"] for r in rows["EvalQuestion"]}
    asks = rows["EvalAsk"]
    ask_ids = {r["AskId"] for r in asks}
    if (
        run.get("Repeats") != 1
        or run.get("ExplainMode") != "followup"
        or not run.get("TraceEnabled")
        or run.get("Status") not in ("completed", "rescored")
        or len(ask_ids) != len(asks)
        or len(asks) != len(questions)
        or run.get("AskCount") != len(asks)
        or run.get("QuestionCount") != len(questions)
        or {r["QuestionId"] for r in asks} != questions
    ):
        raise ValueError("Incomplete run/ask/question roster or unsupported repeat/explanation settings")
    if any(
        r.get("Status") != "ok"
        or not r.get("ConversationId")
        or r.get("Attempt") != 1
        or not r.get("Why")
        or r.get("WhyLatencyMs") is None
        for r in asks
    ):
        raise ValueError("A question or actual why turn failed/missing; this is a runtime ERROR, not a quality FAIL")
    results = {}
    for row in rows["EvalResult"]:
        if row.get("Backend") != "fabric-native" or row.get("AskId") not in ask_ids:
            raise ValueError("Unexpected result backend or ask ID")
        results[row["AskId"]] = row
    scores = {}
    for row in rows["EvalScore"]:
        if row.get("Backend") != "fabric-native" or row.get("AskId") not in ask_ids:
            raise ValueError("Unexpected score backend or ask ID")
        scores[row["AskId"], row["Check"]] = row.get("Score")
    if set(results) != ask_ids:
        raise ValueError("Missing Option 1 result(s)")
    for ask_id in ask_ids:
        for check in ("value", "artifact", "model", "judge_answer", "why"):
            value = scores.get((ask_id, check))
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError("Missing/invalid Option 1 check: %s %s" % (ask_id, check))
        if scores[ask_id, "judge_answer"] not in (0, 1):
            raise ValueError("Answer judge did not return a valid yes/no grade: %s" % ask_id)
    if any(r.get("AskId") not in ask_ids for r in rows["FabricIqQuery"]):
        raise ValueError("Observed DAX has an unexpected ask ID")
    if (
        any(r.get("TraceStatus") not in ("observed", "complete") for r in results.values())
        or {r["AskId"] for r in rows["FabricIqQuery"]} != ask_ids
    ):
        raise ValueError("Missing/unsettled DAX for one or more asks; this is incomplete evidence")
    if any(r.get("Verdict") not in ("PASS", "FAIL") for r in results.values()):
        raise ValueError("Runtime ERROR/INCONCLUSIVE evidence remains; no successful acceptance claim")
    return rows, counts, digests, list(results.values())


def eventhouse_counts(client, database, run_id):
    kql = (
        "declare query_parameters(run_id:string);\nunion\n"
        + ",\n".join(
            "(%s | where RunId == run_id | summarize Rows=count() | extend Table='%s')" % (name, name)
            for name in TABLES
        )
        + "\n| project Table, Rows"
    )
    return {r["Table"]: int(r["Rows"]) for r in client.query(database, kql, {"run_id": run_id})}


def verify_publication(settings, run_id, expected, wait_seconds, poll_seconds, module):
    from cfeval.kusto import KustoQueryClient

    client = KustoQueryClient(settings.eventhouse_query_uri, settings=settings)
    deadline = time.monotonic() + wait_seconds
    while True:
        eventhouse = eventhouse_counts(client, settings.eventhouse_database, run_id)
        sql = sql_counts(settings, run_id, module)
        print("Table             JSONL  Eventhouse  SQL")
        for table in TABLES:
            print(
                "%-17s %5d  %10s  %s"
                % (table, expected[table], eventhouse.get(table, "MISSING"), sql.get(table, "n/a"))
            )
        if eventhouse == expected and sql == {name: expected[name] for name in app_tables()}:
            print("Exact seven-table Eventhouse and five-table SQL publication verified for %s." % run_id)
            return
        if any(eventhouse.get(t, 0) > n or (sql.get(t) or 0) > n for t, n in expected.items()):
            raise RuntimeError("Publication has extra rows; preserve IDs and reconcile, never silently deduplicate")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                "Publication incomplete at observation deadline. Resume with --verify-only and "
                "the SAME run ID; do not ask, rescore, fetch traces or publish again."
            )
        time.sleep(min(poll_seconds, remaining))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env")
    parser.add_argument("--run-id", required=True, help="unique immutable folder/operation label")
    parser.add_argument("--questions", help="comma-separated stable IDs; default all rows in GOLDEN_SET")
    parser.add_argument(
        "--max-questions",
        "--max-attempts",
        type=int,
        help="explicit ceiling on question attempts, including failed/ambiguous submissions",
    )
    parser.add_argument("--max-judge-calls", type=int, help="explicit direct judge-attempt ceiling")
    parser.add_argument("--verify-only", action="store_true", help="read original JSONL and publication only")
    parser.add_argument("--wait-seconds", type=float, default=1200, help="read-only publication observation, 0..3600")
    parser.add_argument("--poll-seconds", type=float, default=30, help="publication polling interval, at least 5")
    parser.add_argument("--output-dir", help="override OUTPUT_DIR (also for --verify-only)")
    parser.add_argument(
        "--mock", action="store_true", help="fully offline, simulated; never verifies cloud publication"
    )
    parser.add_argument(
        "--profile",
        choices=["baseline", "improving", "tuned"],
        default="tuned",
        help="offline simulation only; never changes live prompts/scores",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 64
    print("Tip: `python -m cfeval verify` provides standard CLI schema and harness verification.")
    folder = receipt = None
    try:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", args.run_id):
            raise ValueError("run-id must be a single safe folder name, at most 120 characters")
        if (
            not math.isfinite(args.wait_seconds)
            or not 0 <= args.wait_seconds <= 3600
            or not math.isfinite(args.poll_seconds)
            or args.poll_seconds < 5
        ):
            raise ValueError("wait-seconds must be 0..3600; poll-seconds must be finite and at least 5")
        settings = (
            Settings(golden_set=str(ROOT / "data/golden/golden_questions.csv"))
            if args.mock
            else configured_settings(args.env)
        )
        if args.output_dir:
            settings.output_dir = args.output_dir
        folder = Path(settings.output_dir) / args.run_id
        module = None
        if not args.mock:
            module = sql_driver(settings)  # Fail on missing optional dependency BEFORE any paid submissions.
        if not args.verify_only:
            if folder.exists():
                raise ValueError("Run ID already exists. Use --verify-only; never repeat an ambiguous submission.")
            if args.max_questions is None or args.max_judge_calls is None:
                raise ValueError("New runs require --max-questions and --max-judge-calls")
            questions = load_golden(settings.golden_set)
            if args.questions:
                wanted = args.questions.split(",")
                if len(set(wanted)) != len(wanted) or any(not name for name in wanted):
                    raise ValueError("Question IDs must be unique and nonempty")
                unknown = set(wanted) - {q.id for q in questions}
                if unknown:
                    raise ValueError("Unknown question IDs: %s" % ", ".join(sorted(unknown)))
                questions = [q for q in questions if q.id in wanted]
            count = len(questions)
            if count > args.max_questions or 2 * count > args.max_judge_calls:
                raise ValueError(
                    "Selected %d questions require %d question and %d judge attempts; above allowance"
                    % (count, count, 2 * count)
                )
            if any(
                q.expected_value is None
                or not math.isfinite(q.expected_value)
                or not q.expected_answer
                or not q.expected_artifact
                or not q.model
                or "<" in q.question
                or "CALIBRATE" in q.expected_answer
                for q in questions
            ):
                raise ValueError("Calibrate values/reference sentences and resolve every template placeholder first")
            if not args.mock:
                if Path(settings.golden_set).resolve() in {
                    (ROOT / "data/golden/golden_questions.csv").resolve(),
                    (ROOT / "src/cfeval/sample/golden_questions.csv").resolve(),
                }:
                    raise ValueError(
                        "The bundled Q01-Q08 baseline is fictional history, not a calibrated live set. "
                        "Configure a separate GOLDEN_SET."
                    )
                resolve_targets(settings)
                require_trace_progress(settings, questions)
                visible = sql_counts(settings, args.run_id, module)
                if any(value is None for value in visible.values()):
                    raise ValueError(
                        "SQL app tables are not all visible. Complete setup/propagation before paid calls."
                    )
                from cfeval.kusto import KustoQueryClient

                existing = eventhouse_counts(
                    KustoQueryClient(settings.eventhouse_query_uri, settings=settings),
                    settings.eventhouse_database,
                    args.run_id,
                )
                if set(existing) != set(TABLES) or any(existing.values()) or any(visible.values()):
                    raise ValueError(
                        "Run ID already appears in cloud telemetry, or table discovery is incomplete. "
                        "Use the original folder with --verify-only; no new submissions."
                    )
                from cfeval.auth import DelegatedAuth

                auth = DelegatedAuth.from_settings(settings)
                auth.token()  # Silent, actual principal/tenant/audience/scope checks; never launches sign-in.
                print("Verified actual test user %s in tenant %s." % (auth.signed_in_upn(), settings.tenant_id))
            folder.mkdir(parents=True, exist_ok=False)
            receipt = {
                "run_id": args.run_id,
                "state": "submitting",
                "questions": [q.id for q in questions],
                "reserved_question_attempts": count,
                "reserved_judge_attempts": 2 * count,
                "retries": 0,
                "started_utc": iso(utc_now()),
                "mock": args.mock,
            }
            _write_receipt(folder / "rehearsal.json", receipt)
            harness = build_harness(
                settings,
                option="fabric-native",
                mock=args.mock,
                publish=not args.mock,
                profile=args.profile,
                run_id=args.run_id,
                questions=questions,
                repeats=1,
                explain_mode="followup",
                run_name="Demo rehearsal " + args.run_id,
                chat_max_retries=0,
                judge_max_retries=0,
                judge_max_calls=2 * count,
            )
            harness.golden_hash = golden_hash(settings.golden_set)
            outcome = harness.run()
            receipt.update(
                state="recorded",
                sink_errors=outcome.sink_errors,
                sha256={
                    name: hashlib.sha256(
                        (folder / ("%s.jsonl" % name)).read_bytes() if (folder / ("%s.jsonl" % name)).exists() else b""
                    ).hexdigest()
                    for name in TABLES
                },
            )
            _write_receipt(folder / "rehearsal.json", receipt)
            print(outcome.summary_text())
        rows, expected, _digests, results = local_record(folder, args.run_id, args.mock)
        if args.mock:
            print(
                "OFFLINE SIMULATION ONLY: local seven-table counts %s; no live identity/publication evidence."
                % expected
            )
        else:
            if any(r.get("TestUser", "").casefold() != settings.test_user_upn.casefold() for r in rows["EvalAsk"]):
                raise ValueError("Saved test-user identity differs from explicit configuration")
            if args.verify_only:
                resolve_targets(settings)
            verify_publication(settings, args.run_id, expected, args.wait_seconds, args.poll_seconds, module)
            print(
                "Demo link: %s"
                % (
                    settings.demo_app_url
                    or "https://app.fabric.microsoft.com/groups/%s/list" % settings.lakehouse_workspace_id
                )
            )
            print(
                "MANUAL BROWSER GATE: enter hosted app through Fabric portal, verify actual SSO account/tenant; "
                "Live data filter + this RunId; Overview, Questions, Performance, Runs. "
                "Standalone/build/sample data are not hosted evidence."
            )
        failures = [r["QuestionId"] for r in results if r["Verdict"] == "FAIL"]
        if failures:
            print("QUALITY FAIL: %s. Preserve this run; no automatic second batch." % ", ".join(failures))
            return 2
        suffix = " (simulated)" if args.mock else "; manual hosted-browser gates still required"
        print("SCRIPTED GATES PASS%s." % suffix)
        return 0
    except (Exception, SystemExit) as exc:
        if receipt and receipt.get("state") == "submitting":
            receipt.update(state="error", error_type=type(exc).__name__)
            _write_receipt(folder / "rehearsal.json", receipt)
        print("ERROR: %s" % exc, file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
