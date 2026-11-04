"""Spike S2: what does a Copilot-issued query look like in the engine logs, and how fast does it arrive? (ADR-002)

Queries the workspace-monitoring Eventhouse (``SemanticModelLogs``) for QueryEnd events in a time
window, typically the one spike S1 printed, and polls until they appear or ``--max-wait`` passes.
Records per event: the model, the executing user, ApplicationName and ApplicationContext (to tell
surfaces apart) and the DAX text; and the ingestion delay (first poll that saw the event minus
its timestamp), which sets the harness's evidence wait (PLAN §9.5).

    uv run python spikes/s2_engine_logs.py --workspace ws-eval-certified \\
        --t0 2026-11-03T20:00:00+00:00 --t1 2026-11-03T20:00:40+00:00 --user eval.exec@contoso.example

Signs in as the operator (az login). Settings: [evidence.monitoring.<workspace>]. Contract:
config/contracts.yaml `semantic_model_logs`. Raw results go to spikes/out/s2/.
"""

import argparse
import time
from datetime import datetime, timedelta

import httpx
from _common import heading, operator_credential, save, settings, utc_now

COLUMNS = ("Timestamp, ItemName, ExecutingUser, ApplicationName, ApplicationContext, DurationMs, "
           "CorrelationId, EventText")


def kql(t0: datetime, t1: datetime, user: str | None) -> str:
    window_start = t0 - timedelta(seconds=settings().evidence.window_before_s)
    window_end = t1 + timedelta(seconds=settings().evidence.window_after_s)
    user_filter = f'| where ExecutingUser =~ "{user}"' if user else ""
    return (
        "SemanticModelLogs\n"
        f"| where Timestamp between (datetime({window_start.isoformat()}) .. datetime({window_end.isoformat()}))\n"
        '| where OperationName == "QueryEnd"\n'
        '| where EventText !contains "eval-gt" and EventText !contains "eval-hb"\n'
        f"{user_filter}\n"
        f"| project {COLUMNS}\n"
        "| order by Timestamp asc"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", default=settings().fabric.certified_workspace)
    parser.add_argument("--t0", required=True, type=datetime.fromisoformat, help="request start, ISO 8601 with offset")
    parser.add_argument("--t1", required=True, type=datetime.fromisoformat, help="request end, ISO 8601 with offset")
    parser.add_argument("--user", help="only events executed as this UPN")
    parser.add_argument("--max-wait", type=int, default=settings().evidence.max_wait_s, help="seconds to keep polling")
    args = parser.parse_args()

    monitoring = settings().evidence.monitoring.get(args.workspace)
    if monitoring is None or "<" in monitoring.query_uri:
        raise SystemExit(f"set [evidence.monitoring.{args.workspace}] query_uri and database in config/settings.toml")
    token = operator_credential().get_token(f"{monitoring.query_uri}/.default").token
    query = kql(args.t0, args.t1, args.user)
    first_seen: dict[str, float] = {}
    rows: list[dict[str, object]] = []
    deadline = time.monotonic() + args.max_wait
    with httpx.Client(timeout=60, headers={"Authorization": f"Bearer {token}"}) as client:
        while True:
            body = {"db": monitoring.database, "csl": query}
            response = client.post(f"{monitoring.query_uri}/v1/rest/query", json=body)
            response.raise_for_status()
            table = response.json()["Tables"][0]
            names = [column["ColumnName"] for column in table["Columns"]]
            rows = [dict(zip(names, row, strict=True)) for row in table["Rows"]]
            now = utc_now()
            for row in rows:
                key = str(row.get("CorrelationId") or row["Timestamp"])
                if key not in first_seen:
                    stamp = datetime.fromisoformat(str(row["Timestamp"]).replace("Z", "+00:00"))
                    first_seen[key] = (now - stamp).total_seconds()
            if rows or time.monotonic() > deadline:
                break
            print(f"no events yet; polling again in {settings().evidence.poll_interval_s} s")
            time.sleep(settings().evidence.poll_interval_s)

    path = save("s2", args.workspace, {"query": query, "rows": rows, "ingestion_delay_s": first_seen})
    heading(f"S2 {args.workspace}: {len(rows)} QueryEnd events")
    for row in rows:
        print(f"- {row['Timestamp']} {row['ItemName']} as {row['ExecutingUser']} via {row['ApplicationName']} "
              f"({row['DurationMs']} ms)\n  context: {row['ApplicationContext']}\n  {str(row['EventText'])[:200]}")
    heading("For ADR-002")
    delays = sorted(first_seen.values())
    print(f"Ingestion delay (upper bound, s): {', '.join(f'{d:.0f}' for d in delays) or 'none observed'}")
    print(f"Raw results: {path}")


if __name__ == "__main__":
    main()
