"""Where telemetry rows go: local JSONL files, the Eventhouse, or both."""

import json
from datetime import datetime
from pathlib import Path

from .clock import iso
from .schema import SCHEMA_VERSION, TABLES, table_row_id


def coerce_row(table, row):
    """Return a row with exactly the table's columns and JSON-safe values."""
    out: dict[str, object] = {}
    for col, typ in TABLES[table]["columns"]:
        value = row.get(col)
        if value is None:
            out[col] = None
        elif typ == "datetime":
            out[col] = iso(value) if isinstance(value, datetime) else str(value)
        elif typ == "int":
            out[col] = int(value) if not isinstance(value, bool) else int(bool(value))
        elif typ == "real":
            out[col] = float(value)
        elif typ == "dynamic":
            out[col] = value
        else:
            out[col] = value if isinstance(value, str) else str(value)
    unknown = set(row) - set(out)
    if unknown:
        raise KeyError("%s has no column(s): %s" % (table, ", ".join(sorted(unknown))))
    if "SchemaVersion" in out and out["SchemaVersion"] is None:
        out["SchemaVersion"] = SCHEMA_VERSION
    if "RowId" in out and not out["RowId"]:
        out["RowId"] = table_row_id(table, out)
    return out


class JsonlSink:
    """Writes each table to <folder>/<Table>.jsonl (always on: the run's local record)."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def write(self, table, rows):
        if not rows:
            return 0
        with (self.folder / ("%s.jsonl" % table)).open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(coerce_row(table, r), ensure_ascii=False) + "\n")
        return len(rows)

    def read(self, table):
        path = self.folder / ("%s.jsonl" % table)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class EventhouseSink:
    """Ingests rows into the telemetry KQL database (streaming, falls back to queued)."""

    def __init__(self, query_uri, database, ingest_uri="", client=None, settings=None):
        if client is None:
            from .kusto import KustoIngestClient

            client = KustoIngestClient(query_uri, ingest_uri, settings=settings)
        self.client = client
        self.database = database

    def write(self, table, rows):
        rows = [coerce_row(table, r) for r in rows]
        return self.client.ingest_json(self.database, table, rows, "%s_json" % table)


class FanoutSink:
    """Write to several sinks. A failing secondary sink is reported, not fatal."""

    def __init__(self, primary, *others, on_error=print):
        self.primary = primary
        self.others = list(others)
        self.on_error = on_error
        self.errors = []

    def write(self, table, rows):
        n = self.primary.write(table, rows)
        for sink in self.others:
            try:
                sink.write(table, rows)
            except Exception as exc:  # keep the run going; the JSONL copy can be re-published
                msg = "telemetry write to %s failed for %s: %s" % (type(sink).__name__, table, exc)
                self.errors.append(msg)
                self.on_error(msg)
        return n
