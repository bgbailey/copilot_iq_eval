"""The three Fabric calls the script makes, using plain REST so every request is visible.

1. Reference DAX against the certified semantic model (Power BI executeQueries) for the expected value.
2. KQL against workspace monitoring (SemanticModelLogs) for the DAX that ran while Copilot answered.
3. Inline ingestion of the results into the results Eventhouse, for the scorecard app.
"""
import csv
import io
import json

import requests

POWERBI = "https://api.powerbi.com/v1.0/myorg"


def reference_value(token, semantic_model_id, dax):
    """Run the question's reference DAX and return the first value of the first row."""
    r = requests.post(f"{POWERBI}/datasets/{semantic_model_id}/executeQueries", timeout=120,
                      headers={"Authorization": f"Bearer {token}"},
                      json={"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}})
    r.raise_for_status()
    rows = r.json()["results"][0]["tables"][0]["rows"]
    return float(next(iter(rows[0].values()))) if rows else None


def kql(token, query_uri, database, query):
    """Run a KQL query and return the rows as dictionaries."""
    r = requests.post(f"{query_uri.rstrip('/')}/v1/rest/query", timeout=120,
                      headers={"Authorization": f"Bearer {token}"}, json={"db": database, "csl": query})
    r.raise_for_status()
    table = r.json()["Tables"][0]
    names = [c["ColumnName"] for c in table["Columns"]]
    return [dict(zip(names, row)) for row in table["Rows"]]


def dax_that_ran(token, query_uri, database, user, started, ended, slack_seconds=5):
    """DAX queries the test user ran between `started` and `ended`, from workspace monitoring.

    Copilot doesn't tell us which query it ran, so we match on user and time window. That's evidence,
    not proof: anything else the test user does at the same time lands in the same window.
    """
    query = f"""SemanticModelLogs
| where Timestamp between (datetime({started}) - {slack_seconds}s .. datetime({ended}) + {slack_seconds}s)
| where OperationName == "QueryEnd" and ExecutingUser =~ "{user}"
| project Timestamp, SemanticModel = ItemName, Dax = EventText, DurationMs
| order by Timestamp asc"""
    return [{"timestamp": str(r["Timestamp"]), "semantic_model": r["SemanticModel"],
             "dax": r["Dax"], "duration_ms": r["DurationMs"]} for r in kql(token, query_uri, database, query)]


def ingest(token, query_uri, database, table, rows):
    """Append rows with .ingest inline: fine for a demo's few hundred rows, not for production volumes."""
    if not rows:
        return
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for row in rows:
        writer.writerow([json.dumps(v) if isinstance(v, (list, dict)) else ("" if v is None else v)
                         for v in row.values()])
    command = f".ingest inline into table {table} <|\n{buf.getvalue()}"
    r = requests.post(f"{query_uri.rstrip('/')}/v1/rest/mgmt", timeout=120,
                      headers={"Authorization": f"Bearer {token}"}, json={"db": database, "csl": command})
    r.raise_for_status()
