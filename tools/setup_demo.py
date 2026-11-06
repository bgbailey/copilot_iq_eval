"""Reuse existing demo resources; writes require both an operation flag and --apply."""
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from cfeval import runtime
from cfeval.config import Settings
from cfeval.fabric_rest import FabricClient, app_tables, create_app_shortcuts
from cfeval.golden import load_golden, write_golden

ROOT = Path(__file__).resolve().parents[1]


def configured_settings(env_file):
    if not Path(env_file).is_file():
        raise ValueError("Settings file not found: %s. Copy .env.example and configure explicit targets." % env_file)
    settings = Settings.load(env_file=env_file)
    runtime.require_operator_settings(settings, cli=True)
    runtime.require_identity(settings.tenant_id, settings.test_user_upn, settings.test_user_object_id)
    runtime._uuid(settings.client_id, "CLIENT_ID")
    for key in ("eventhouse_workspace_id", "eventhouse_database_id", "lakehouse_workspace_id", "lakehouse_id",
                "semantic_model_workspace_id"):
        runtime._uuid(getattr(settings, key), key.upper())
    if settings.lakehouse_shortcut_path not in ("Tables", "Tables/dbo"):
        raise ValueError("LAKEHOUSE_SHORTCUT_PATH must be Tables or Tables/dbo")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", settings.sql_schema):
        raise ValueError("SQL_SCHEMA must be a simple SQL schema identifier")
    if settings.repeats != 1 or settings.explain_mode != "followup":
        raise ValueError("The demo requires REPEATS=1 and EXPLAIN_MODE=followup")
    if not settings.trace_enabled or not settings.judge_enabled:
        raise ValueError("Configure all expected/decoy monitoring sources and the Option 1 judge")
    _https(settings.judge_endpoint, "JUDGE_ENDPOINT")
    sources = json.loads(settings.monitoring_sources) if settings.monitoring_sources else [{
        "query_uri": settings.monitoring_query_uri, "database": settings.monitoring_database,
        "workspace_id": settings.semantic_model_workspace_id,
    }]
    if not isinstance(sources, list) or not sources:
        raise ValueError("MONITORING_SOURCES must be a nonempty JSON list")
    for source in sources:
        if not isinstance(source, dict) or not source.get("database"):
            raise ValueError("Each monitoring source needs query_uri, database and workspace_id")
        _https(source.get("query_uri", ""), "Monitoring query_uri")
        runtime._uuid(source.get("workspace_id"), "Monitoring workspace_id")
    for key in ("pause_seconds", "trace_wait_seconds", "trace_poll_seconds", "trace_settle_seconds"):
        value = getattr(settings, key)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("%s must be finite and positive" % key.upper())
    if settings.demo_app_url:
        url = urlsplit(settings.demo_app_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("DEMO_APP_URL must be an HTTPS hosted-app link without credentials")
    return settings


def _https(value, label):
    url = urlsplit(value)
    if (url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment):
        raise ValueError("%s must be an HTTPS URL without credentials, query or fragment" % label)
    return value.rstrip("/")


def sql_host(value):
    host = value.removeprefix("tcp:").removesuffix(",1433").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.datawarehouse\.fabric\.microsoft\.com", host):
        raise ValueError("SQL_ENDPOINT_SERVER must be the Fabric SQL endpoint host (not a URL/connection string)")
    return host


def require_trace_progress(settings, questions):
    from cfeval.cli import _monitoring

    _source, watermark = _monitoring(settings, questions, print)
    if watermark is None:
        raise ValueError("Each monitoring source needs a queryable model represented by this CSV's expected "
                         "models or decoys so a progress marker can be sent. Narrow MONITORING_SOURCES for "
                         "a small control CSV; no Copilot questions were submitted.")


def resolve_targets(settings):
    """Read back explicit IDs, bind connection properties, never create/replace an item."""
    eventhouse = FabricClient(settings=settings, skill="eventhouse-cli", max_retries=0)
    lakehouses = FabricClient(settings=settings, skill="sqldw-cli", max_retries=0)
    for workspace in {settings.eventhouse_workspace_id, settings.lakehouse_workspace_id,
                      settings.semantic_model_workspace_id}:
        item = eventhouse.workspace(workspace)
        if str(item.get("id", "")).lower() != workspace.lower() or not item.get("capacityId"):
            raise ValueError("Configured workspace was not resolved on an existing capacity: %s" % workspace)
    database = eventhouse.kql_database(settings.eventhouse_workspace_id, settings.eventhouse_database_id)
    lakehouse = lakehouses.lakehouse(settings.lakehouse_workspace_id, settings.lakehouse_id)
    for item, expected in ((database, settings.eventhouse_database_id), (lakehouse, settings.lakehouse_id)):
        if str(item.get("id", "")).lower() != expected.lower():
            raise ValueError("Target readback did not match the configured item ID")
    properties = database.get("properties") or {}
    for field, remote in (("eventhouse_query_uri", properties.get("queryServiceUri")),
                          ("eventhouse_ingest_uri", properties.get("ingestionServiceUri"))):
        if not remote:
            if field == "eventhouse_ingest_uri":
                continue
            raise ValueError("KQL database readback is missing queryServiceUri")
        actual = _https(remote, field.upper())
        configured = getattr(settings, field)
        if configured and _https(configured, field.upper()).lower() != actual.lower():
            raise ValueError("%s differs from the configured KQL database item" % field.upper())
        setattr(settings, field, actual)
    engine_name = properties.get("databaseName")
    if not settings.eventhouse_database or (engine_name and settings.eventhouse_database != engine_name):
        raise ValueError("EVENTHOUSE_DATABASE must be the actual engine databaseName from connection details "
                         "(often the KQL database GUID), not its display name")
    from cfeval.kusto import KustoQueryClient
    context = KustoQueryClient(settings.eventhouse_query_uri, settings=settings).query(
        settings.eventhouse_database, "print DatabaseName=current_database()")
    if len(context) != 1 or context[0].get("DatabaseName") != settings.eventhouse_database:
        raise ValueError("EVENTHOUSE_DATABASE did not match the actual Kusto database context")
    endpoint = (lakehouse.get("properties") or {}).get("sqlEndpointProperties") or {}
    endpoint_id = runtime._uuid(endpoint.get("id"), "Resolved SQL endpoint ID")
    if settings.sql_endpoint_id and settings.sql_endpoint_id.lower() != endpoint_id:
        raise ValueError("SQL_ENDPOINT_ID is not this lakehouse's SQL endpoint; do not use LAKEHOUSE_ID here")
    actual_host = sql_host(endpoint.get("connectionString", ""))
    if settings.sql_endpoint_server and sql_host(settings.sql_endpoint_server) != actual_host:
        raise ValueError("SQL_ENDPOINT_SERVER is not this lakehouse's resolved SQL endpoint")
    settings.sql_endpoint_id = endpoint_id
    settings.sql_endpoint_server = actual_host
    settings.sql_endpoint_database = settings.sql_endpoint_database or lakehouse.get("displayName", "")
    if not settings.sql_endpoint_database:
        raise ValueError("Set SQL_ENDPOINT_DATABASE to the lakehouse SQL database name")
    print("Reusing KQL database %s; lakehouse %s; SQL endpoint %s (three distinct bindings)." %
          (database.get("displayName"), lakehouse.get("displayName"), endpoint_id))
    return settings


def bundle(destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Bundle destination already exists; choose a new directory")
    destination.mkdir(parents=True)
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                    "--wheel-dir", str(destination.resolve()), str(ROOT)], check=True)
    for notebook in (ROOT / "notebooks").glob("*.ipynb"):
        shutil.copy2(notebook, destination / notebook.name)
    print("Public wheel/notebooks only in %s. Attach the wheel in a Fabric Environment, import notebooks, "
          "configure them manually; no notebook was published, run or scheduled." % destination)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env")
    parser.add_argument("--offline", action="store_true", help="configuration/CSV validation only; no tokens/network")
    parser.add_argument("--telemetry", action="store_true", help="review/apply the existing Eventhouse setup")
    parser.add_argument("--shortcuts", action="store_true", help="review/apply the five non-overwriting shortcuts")
    parser.add_argument("--refresh-golden", action="store_true", help="preview reference DAX calibration; --apply saves")
    parser.add_argument("--apply", action="store_true", help="permit only the selected setup/calibration writes")
    parser.add_argument("--onelake-latency", type=int, default=5)
    parser.add_argument("--bundle-dir", help="optional NEW local directory for a wheel and generic notebooks")
    args = parser.parse_args(argv)
    try:
        if args.offline and args.apply:
            raise ValueError("--offline cannot be combined with --apply")
        if args.onelake_latency < 5:
            raise ValueError("OneLake availability has a five-minute minimum setting, not a hard delivery deadline")
        settings = configured_settings(args.env)
        path = Path(settings.golden_set)
        questions = load_golden(path)  # No fallback to a bundled sample for a live configuration.
        print("Configured %d questions from %s. No Copilot/judge/Foundry evaluation requests in setup." %
              (len(questions), path))
        if args.offline:
            print("OFFLINE: identities/targets are configured, NOT authenticated or resolved.")
        else:
            resolve_targets(settings)
            from cfeval.powerbi import PowerBiClient
            client = PowerBiClient(settings=settings, max_retries=0)
            models = client.dataset_ids(settings.semantic_model_workspace_id)
            from cfeval.scorers import normalize_name
            missing = sorted({q.model for q in questions if normalize_name(q.model) not in models})
            if missing:
                raise ValueError("Expected models not found in SEMANTIC_MODEL_WORKSPACE_ID: %s" % ", ".join(missing))
            require_trace_progress(settings, questions)
            print("Operator can resolve expected models. This does NOT verify test-user access, RLS or Copilot routing.")
        if args.telemetry:
            from cfeval.cli import cmd_setup_eventhouse
            from cfeval.kqlgen import setup_script
            if args.apply:
                if cmd_setup_eventhouse(settings, args):
                    raise RuntimeError("Eventhouse setup failed; stopped before shortcuts/calibration")
            else:
                print(setup_script(settings.eventhouse_database, args.onelake_latency))
        if args.shortcuts:
            print("Five shortcut targets: %s -> %s/%s/Tables/<table>" %
                  (", ".join(app_tables()), settings.eventhouse_workspace_id, settings.eventhouse_database_id))
            if args.apply:
                results = create_app_shortcuts(
                    FabricClient(settings=settings, max_retries=0), settings.lakehouse_workspace_id,
                    settings.lakehouse_id, settings.eventhouse_workspace_id, settings.eventhouse_database_id,
                    path=settings.lakehouse_shortcut_path)
                if any(r["status"] != "ok" for r in results):
                    raise RuntimeError("Shortcut setup failed; conflicting targets were not overwritten")
        if args.refresh_golden:
            if args.offline:
                print("OFFLINE: reference DAX was not executed.")
            else:
                from cfeval.powerbi import refresh_expected_values
                report = refresh_expected_values(questions, client, settings.semantic_model_workspace_id)
                for row in report:
                    print("%s %s: %s -> %s %s" %
                          (row["QuestionId"], row["Status"], row["Old"], row["New"], row["Detail"]))
                if any(r["Status"] in ("error", "skipped") for r in report):
                    raise RuntimeError("Calibration incomplete; the CSV was not written")
                if args.apply:
                    if path.resolve() in {(ROOT / "data/golden/golden_questions.csv").resolve(),
                                           (ROOT / "src/cfeval/sample/golden_questions.csv").resolve()}:
                        raise ValueError("Preserve Q01-Q08 baseline samples. Calibrate a separate CSV with new IDs "
                                         "where prompts change.")
                    write_golden(questions, path)
                    print("Saved calibrated values. Review expected_answer text/units/period/cutoff before rehearsal.")
        if args.bundle_dir:
            bundle(args.bundle_dir)
        print("MANUAL GATES: licensing/admin consent; test-user Viewer + Read/Build and RLS in supported UI; "
              "Prep data for AI/UI artifacts; labelled browser sign-in. No admin/security/capacity changes performed.")
        print("App scaffold/overlay/publish: app/README.md. Hosted SSO and all four browser views remain manual.")
        return 0
    except (Exception, SystemExit) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
