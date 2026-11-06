"""Command line: python -m cfeval <command>  (run 'python -m cfeval -h')."""
import argparse
import json
import random
import sys
from datetime import timedelta
from pathlib import Path

from . import __version__, runtime
from .clock import SimClock, SystemClock, utc_now
from .config import Settings
from .golden import golden_hash, load_golden, resolve_golden_path, write_golden
from .kqlgen import OPTIONAL_MARK, setup_commands, setup_script
from .pipeline import EvalHarness, load_run
from .schema import TABLES
from .scoring import LocalBackend
from .sinks import EventhouseSink, JsonlSink

OPTIONS = {"fabric-native": ("fabric-native",), "foundry": ("foundry",), "both": ("fabric-native", "foundry")}
DEMO_USER = "eval.tester@contoso.com"


def _eventhouse_sinks(settings, enabled=True):
    if not (enabled and settings.telemetry_enabled):
        return []
    return [EventhouseSink(settings.eventhouse_query_uri, settings.eventhouse_database, settings.eventhouse_ingest_uri,
                          settings=settings)]


def _monitoring(settings, questions, log):
    from .kusto import KustoQueryClient
    from .powerbi import DaxWatermark, DaxWatermarks, PowerBiClient
    from .trace import CombinedMonitoringSource, WorkspaceMonitoringSource

    raw = getattr(settings, "monitoring_sources", "")
    try:
        entries = json.loads(raw) if raw else [{
            "query_uri": settings.monitoring_query_uri, "database": settings.monitoring_database,
            "workspace_id": settings.semantic_model_workspace_id,
        }]
    except (TypeError, ValueError) as exc:
        raise SystemExit("MONITORING_SOURCES must be a JSON list of monitoring sources: %s" % exc) from exc
    if not isinstance(entries, list) or not entries or any(
            not isinstance(e, dict) or not all(isinstance(e.get(k), str) and e[k].strip()
                                               for k in ("query_uri", "database")) for e in entries):
        raise SystemExit("Each MONITORING_SOURCES entry needs query_uri and database.")
    sources = [WorkspaceMonitoringSource(KustoQueryClient(e["query_uri"], settings=settings), e["database"])
               for e in entries]
    monitoring = CombinedMonitoringSource(sources) if len(sources) > 1 else sources[0]
    watermark = None
    if all(e.get("workspace_id") for e in entries):
        try:
            client = PowerBiClient(settings=settings)
            watermark = DaxWatermarks([DaxWatermark.for_questions(client, e["workspace_id"], questions,
                                                                 include_decoys=True) for e in entries])
        except Exception as exc:
            log("DAX watermark unavailable (%s); every configured monitoring source must show later event progress." %
                exc)
    return monitoring, watermark


def build_harness(settings, option="fabric-native", mock=False, trace=True, publish=True, run_name="", notes="",
                  profile="baseline", seed=7, start=None, repeats=None, explain_mode=None, questions=None,
                  run_id=None, log=print, chat_required=True, chat_max_retries=4, judge_max_retries=2,
                  judge_max_calls=None):
    """Wire up a harness from settings. mock=True uses the simulated tenant (no network)."""
    backends = OPTIONS[option]
    golden_path = resolve_golden_path(settings.golden_set, log=log) if questions is None else None
    questions = questions if questions is not None else load_golden(golden_path)
    common = dict(
        questions=questions, backends=backends, output_dir=settings.output_dir,
        explain_mode=explain_mode or settings.explain_mode, repeats=repeats or settings.repeats,
        pause_seconds=settings.pause_seconds, trace_wait_seconds=settings.trace_wait_seconds,
        trace_poll_seconds=settings.trace_poll_seconds,
        trace_settle_seconds=getattr(settings, "trace_settle_seconds", 40.0),
        golden_name=golden_path.name if golden_path else Path(settings.golden_set).name,
        golden_hash=golden_hash(golden_path) if golden_path else "",
        run_name=run_name, notes=notes, settings_public=settings.public(), log=log, run_id=run_id,
    )
    if mock:
        from .mock import LocalFoundryEmulator, MockCopilotChat, MockJudge, MockMonitoringSource, MockWatermark, MockWorld

        clock = SimClock(start or utc_now())
        user = settings.test_user_upn or DEMO_USER
        world = MockWorld(clock, questions, profile=profile, seed=seed, test_user=user)
        return EvalHarness(
            chat=MockCopilotChat(world), clock=clock, rng=random.Random("%s|%s|%s" % (seed, profile, option)),
            local_backend=LocalBackend(judge=MockJudge(), gate_on_judge=settings.judge_gates_verdict),
            foundry_runner=LocalFoundryEmulator(include_trace=trace,
                                                include_builtin=settings.foundry_builtin_evaluators),
            monitoring=MockMonitoringSource(world) if trace else None,
            watermark=MockWatermark(world) if trace else None,
            extra_sinks=(), test_user=user, trace_user=user,
            judge_model=MockJudge.model_name, surface="simulated", host=runtime.host_name(), **common)

    chat = None
    if chat_required:
        from .auth import DelegatedAuth
        from .chat import CopilotChatClient

        if not (settings.tenant_id and settings.client_id and settings.test_user_upn):
            raise SystemExit("Set TENANT_ID, CLIENT_ID and TEST_USER_UPN (see .env.example), or use --mock.")
        auth = DelegatedAuth.from_settings(settings)
        chat = CopilotChatClient(auth.token, time_zone=settings.time_zone, max_retries=chat_max_retries)
    monitoring = watermark = None
    if trace and settings.trace_enabled and not settings.effective_trace_user:
        raise SystemExit("Set TEST_USER_UPN or TRACE_USER so DAX can be matched to the test user's asks.")
    if trace and settings.trace_enabled:
        monitoring, watermark = _monitoring(settings, questions, log)
    elif trace:
        log("DAX capture is off: set MONITORING_QUERY_URI and MONITORING_DATABASE to capture Fabric IQ's DAX.")
    judge = None
    if "fabric-native" in backends:
        from .judge import make_judge

        judge = make_judge(settings, max_retries=judge_max_retries, max_calls=judge_max_calls)
        if judge is None:
            log("No judge model configured (JUDGE_ENDPOINT): Option 1 runs deterministic checks only.")
    foundry_runner = None
    if "foundry" in backends:
        if not settings.foundry_enabled:
            raise SystemExit("Option 2 needs FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_EVAL_DEPLOYMENT.")
        from .credentials import foundry_credential
        from .foundry import FoundryEvaluation

        foundry_runner = FoundryEvaluation(settings.foundry_project_endpoint, settings.foundry_eval_deployment,
                                           credential=foundry_credential(settings), include_trace=monitoring is not None,
                                           include_builtin=settings.foundry_builtin_evaluators, log=log)
    judge_model = (judge.model_name if judge else "") if "fabric-native" in backends else settings.foundry_eval_deployment
    return EvalHarness(
        chat=chat, clock=SystemClock(), local_backend=LocalBackend(judge=judge, gate_on_judge=settings.judge_gates_verdict),
        foundry_runner=foundry_runner, monitoring=monitoring, watermark=watermark,
        extra_sinks=_eventhouse_sinks(settings, publish), test_user=settings.test_user_upn,
        trace_user=settings.effective_trace_user, judge_model=judge_model, surface="copilot-chat-api",
        host=runtime.host_name(), **common)


def simulate_runs(settings, runs=6, days=6, seed=7, publish=False, log=print):
    """Simulated runs that tell a story (baseline -> improving -> tuned), spread over past days."""
    profiles = ["baseline", "baseline", "improving", "improving", "tuned", "tuned"]
    options = ["fabric-native", "foundry", "both"]
    outcomes = []
    if publish and not settings.telemetry_enabled:
        raise SystemExit("Set EVENTHOUSE_QUERY_URI and EVENTHOUSE_DATABASE before using demo-data --publish.")
    today = utc_now() - timedelta(hours=3)
    for i in range(runs):
        profile = profiles[min(i * len(profiles) // max(runs, 1), len(profiles) - 1)]
        start = today - timedelta(days=round(days * (runs - 1 - i) / max(runs - 1, 1)), hours=-(i % 3))
        harness = build_harness(settings, option=options[i % len(options)], mock=True, publish=False,
                                profile=profile, seed=seed + i, start=start,
                                run_name="Simulated %s run %d" % (profile, i + 1),
                                notes="Simulated data (profile %s)" % profile, log=lambda *_: None)
        if publish:
            harness.sink.others.extend(_eventhouse_sinks(settings))
        outcomes.append(harness.run())
        log("%s  %-13s %-26s pass rate %s" % (outcomes[-1].run_id, profile, outcomes[-1].run_row["EvalOption"],
                                             "%.0f%%" % (100 * (outcomes[-1].metrics["PassRate"] or 0))))
    return outcomes


def app_sample(outcomes, tables=("EvalRun", "EvalQuestion", "EvalResult", "FabricIqQuery", "EvalEvent")):
    data = {"generatedUtc": utc_now().isoformat(), "simulated": True, "tables": {t: [] for t in tables}}
    for o in outcomes:
        sink = JsonlSink(o.folder)
        for t in tables:
            data["tables"][t] += sink.read(t)
    return data


def _republish(settings, folder, tables=None, log=print):
    sinks = _eventhouse_sinks(settings)
    if not sinks:
        raise SystemExit("Set EVENTHOUSE_QUERY_URI and EVENTHOUSE_DATABASE to publish.")
    unknown = set(tables or []) - set(TABLES)
    if unknown:
        raise SystemExit("Unknown table(s): %s" % ", ".join(sorted(unknown)))
    src = JsonlSink(folder)
    for table in tables or TABLES:
        rows = src.read(table)
        if rows:
            sinks[0].write(table, rows)
            log("Published %d %s rows" % (len(rows), table))


def cmd_doctor(settings, args):
    def mark(ok):
        return "ok " if ok else "-- "

    print("cfeval %s on %s" % (__version__, runtime.host_name()))
    checks = [
        ("Copilot Chat sign-in (TENANT_ID, CLIENT_ID, TEST_USER_UPN)", settings.tenant_id and settings.client_id
         and settings.test_user_upn),
        ("Telemetry Eventhouse (EVENTHOUSE_QUERY_URI, EVENTHOUSE_DATABASE)", settings.telemetry_enabled),
        ("DAX capture (MONITORING_QUERY_URI, MONITORING_DATABASE)", settings.trace_enabled),
        ("DAX watermark / golden refresh (SEMANTIC_MODEL_WORKSPACE_ID)", settings.semantic_model_workspace_id),
        ("Option 1 judge model (JUDGE_ENDPOINT, JUDGE_DEPLOYMENT)", settings.judge_enabled),
        ("Option 2 Foundry project (FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_EVAL_DEPLOYMENT)", settings.foundry_enabled),
    ]
    for label, ok in checks:
        print("  %s%s" % (mark(ok), label))
    try:
        path = resolve_golden_path(settings.golden_set, log=lambda *_: None)
        questions = load_golden(path)
        print("  ok golden set %s: %d questions" % (path, len(questions)))
    except Exception as exc:
        print("  !! golden set %s: %s" % (settings.golden_set, exc))
    for module, extra in (("msal", "copilot"), ("azure.kusto.data", "kusto"), ("azure.kusto.ingest", "kusto"),
                          ("openai", "judge"), ("azure.identity", "judge"), ("azure.ai.projects", "foundry")):
        try:
            __import__(module)
            print("  ok package %s" % module)
        except ImportError:
            print("  -- package %s (pip install \"cfeval[%s]\")" % (module, extra))
    return 0


def cmd_login(settings, args):
    from .auth import DelegatedAuth, browser_login_callback

    auth = DelegatedAuth.from_settings(settings, login_callback=browser_login_callback(settings))
    auth.token(interactive=True)
    print("Verified Copilot Chat test user %s in tenant %s; private token cache saved." %
          (auth.signed_in_upn(), settings.tenant_id))
    return 0


def cmd_kql(settings, args):
    text = setup_script(args.database or settings.eventhouse_database, args.onelake_latency)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print("Wrote %s" % args.out)
    else:
        print(text)
    return 0


def cmd_setup_eventhouse(settings, args):
    if not settings.telemetry_enabled:
        raise SystemExit("Set EVENTHOUSE_QUERY_URI and EVENTHOUSE_DATABASE first.")
    from .kusto import KustoQueryClient

    client = KustoQueryClient(settings.eventhouse_query_uri, settings=settings)
    failures = 0
    for command in setup_commands(settings.eventhouse_database, args.onelake_latency):
        optional = command.startswith(OPTIONAL_MARK)
        body = command.split("\n", 1)[1] if optional else command
        try:
            client.mgmt(settings.eventhouse_database, body)
            print("ok  %s" % body.splitlines()[0][:100], flush=True)
        except Exception as exc:
            print("%s %s\n    %s" % ("--" if optional else "!! ", body.splitlines()[0][:100], str(exc)[:300]), flush=True)
            failures += 0 if optional else 1
            if not optional:
                return 1
    return 1 if failures else 0


def cmd_run(settings, args):
    questions = None
    if args.questions:
        wanted = [q.strip() for q in args.questions.split(",") if q.strip()]
        everything = load_golden(resolve_golden_path(settings.golden_set))
        questions = [q for q in everything if q.id in wanted]
        unknown = sorted(set(wanted) - {q.id for q in questions})
        if unknown:
            raise SystemExit("Unknown question id(s): %s" % ", ".join(unknown))
    harness = build_harness(settings, option=args.option, mock=args.mock, trace=not args.no_trace,
                            publish=not args.no_publish, run_name=args.name or "", notes=args.notes or "",
                            profile=args.profile, seed=args.seed, repeats=args.repeats, explain_mode=args.explain,
                            questions=questions)
    outcome = harness.run()
    print(outcome.summary_text())
    return 3 if outcome.sink_errors else 2 if outcome.status in ("partial", "failed") else 0


def cmd_rescore(settings, args):
    folder = Path(args.run_folder)
    questions, _asks = load_run(folder)
    settings.output_dir = str(folder.parent)
    if not settings.trace_enabled:
        raise SystemExit("rescore re-captures DAX: set MONITORING_QUERY_URI and MONITORING_DATABASE.")
    harness = build_harness(settings, option=args.option, mock=False, questions=questions, run_id=folder.name,
                            publish=not args.no_publish, chat_required=False)
    outcome = harness.rescore()
    print(outcome.summary_text())
    return 3 if outcome.sink_errors else 2 if outcome.status in ("partial", "failed") else 0


def cmd_publish(settings, args):
    tables = [t.strip() for t in args.tables.split(",")] if args.tables else None
    _republish(settings, Path(args.run_folder), tables)
    return 0


def cmd_golden_refresh(settings, args):
    from .powerbi import PowerBiClient, refresh_expected_values

    if not settings.semantic_model_workspace_id:
        raise SystemExit("Set SEMANTIC_MODEL_WORKSPACE_ID (the workspace that holds the semantic models).")
    path = resolve_golden_path(settings.golden_set)
    questions = load_golden(path)
    report = refresh_expected_values(questions, PowerBiClient(settings=settings), settings.semantic_model_workspace_id)
    for r in report:
        print("%-5s %-9s %-22s %s -> %s %s" % (r["QuestionId"], r["Status"], r["Model"][:22], r["Old"], r["New"],
                                               r["Detail"]))
    if args.write:
        write_golden(questions, path)
        print("Updated %s" % path)
    return 1 if any(r["Status"] == "error" for r in report) else 0


def cmd_shortcuts(settings, args):
    from .fabric_rest import FabricClient, create_app_shortcuts

    results = create_app_shortcuts(FabricClient(settings=settings), args.lakehouse_workspace, args.lakehouse,
                                   args.kql_workspace, args.kql_database, path=args.path)
    return 1 if any(r["status"] != "ok" for r in results) else 0


def cmd_demo_data(settings, args):
    outcomes = simulate_runs(settings, runs=args.runs, days=args.days, seed=args.seed, publish=args.publish)
    if args.app_json:
        Path(args.app_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.app_json).write_text(json.dumps(app_sample(outcomes), indent=1, default=str), encoding="utf-8")
        print("Wrote %s" % args.app_json)
    return 3 if any(o.sink_errors for o in outcomes) else 0


def parser():
    p = argparse.ArgumentParser(prog="cfeval", description="Copilot Chat x Fabric IQ evaluation harness")
    p.add_argument("--env", default=".env", help="settings file (default .env)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check settings and packages")
    sub.add_parser("login", help="explicit test-user sign-in with a persistent labelled browser context")
    k = sub.add_parser("kql", help="print or write the Eventhouse setup script")
    k.add_argument("--out")
    k.add_argument("--database")
    k.add_argument("--onelake-latency", type=int, default=5)
    s = sub.add_parser("setup-eventhouse", help="create the telemetry tables, mappings, policies and functions")
    s.add_argument("--onelake-latency", type=int, default=5)
    r = sub.add_parser("run", help="ask the golden set and score it")
    r.add_argument("--option", choices=sorted(OPTIONS), default="fabric-native")
    r.add_argument("--mock", action="store_true", help="simulated tenant: no sign-in, no network")
    r.add_argument("--profile", choices=["baseline", "improving", "tuned"], default="baseline",
                   help="simulated behaviour (with --mock)")
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--repeats", type=int)
    r.add_argument("--questions", help="comma-separated question ids to run (default: all)")
    r.add_argument("--explain", choices=["followup", "inline", "off"])
    r.add_argument("--no-trace", action="store_true", help="skip DAX capture")
    r.add_argument("--no-publish", action="store_true", help="local files only, no Eventhouse")
    r.add_argument("--name")
    r.add_argument("--notes")
    rs = sub.add_parser("rescore", help="re-capture DAX and re-score an existing run folder")
    rs.add_argument("run_folder")
    rs.add_argument("--option", choices=sorted(OPTIONS), default="fabric-native")
    rs.add_argument("--no-publish", action="store_true")
    pb = sub.add_parser("publish", help="(re)publish a run folder to the Eventhouse")
    pb.add_argument("run_folder")
    pb.add_argument("--tables", help="comma-separated tables to send (default: all); avoids duplicating rows "
                                     "that were already ingested")
    g = sub.add_parser("golden-refresh", help="recompute expected values from reference DAX")
    g.add_argument("--write", action="store_true")
    sc = sub.add_parser("shortcuts", help="shortcut the app tables from the KQL database into a lakehouse")
    sc.add_argument("--lakehouse-workspace", required=True)
    sc.add_argument("--lakehouse", required=True, help="lakehouse item id")
    sc.add_argument("--kql-workspace", required=True)
    sc.add_argument("--kql-database", required=True, help="KQL database item id")
    sc.add_argument("--path", default="Tables", help="destination: Tables, or Tables/dbo for a schema-enabled lakehouse")
    d = sub.add_parser("demo-data", help="simulated runs for demos and the app's sample mode")
    d.add_argument("--runs", type=int, default=6)
    d.add_argument("--days", type=int, default=6)
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--app-json", help="write the app's sample data file")
    d.add_argument("--publish", action="store_true", help="also ingest the simulated runs into the Eventhouse")
    return p


COMMANDS = {"doctor": cmd_doctor, "login": cmd_login, "kql": cmd_kql, "setup-eventhouse": cmd_setup_eventhouse, "run": cmd_run,
            "rescore": cmd_rescore, "publish": cmd_publish, "golden-refresh": cmd_golden_refresh,
            "shortcuts": cmd_shortcuts, "demo-data": cmd_demo_data}


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    settings = Settings.load(env_file=args.env)
    return COMMANDS[args.command](settings, args)
