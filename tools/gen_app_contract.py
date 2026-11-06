"""Generate the app's data contract from the telemetry schema (src/cfeval/schema.py).

Writes:
  app/overlay/src/eval/generated/contract.ts  row types, field lists and column maps for the app
  app/connectors/evals/metadata.example.json  fictional SQL metadata for reference entity generation;
                                              never a substitute for live connector discovery

Run from the repo root:  python tools/gen_app_contract.py   (CI fails if the files are stale)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cfeval.schema import TABLES  # noqa: E402

TS_TYPES = {"string": "string", "int": "number", "real": "number", "datetime": "Date", "dynamic": "string"}
# How Eventhouse OneLake availability (Delta) surfaces through a lakehouse SQL analytics endpoint
SQL_TYPES = {
    "string": {"dataType": "varchar", "maxLength": 8000},
    "dynamic": {"dataType": "varchar", "maxLength": 8000},
    "int": {"dataType": "int", "precision": 10},
    "real": {"dataType": "float", "precision": 53},
    "datetime": {"dataType": "datetime2", "datePrecision": 6},
}
ROW_NAMES = {"EvalRun": "EvalRunRow", "EvalQuestion": "EvalQuestionRow", "EvalResult": "EvalResultRow",
             "FabricIqQuery": "FabricIqQueryRow", "EvalEvent": "EvalEventRow"}


def camel(name):
    return name[:1].lower() + name[1:]


def app_tables():
    return [(name, spec) for name, spec in TABLES.items() if spec.get("app")]


def contract_ts():
    out = ["// Generated from src/cfeval/schema.py by tools/gen_app_contract.py. Do not edit by hand.",
           "// Property names follow the Rayfin entity convention: camelCase of the SQL column name.", "",
           "export type ColumnType = 'string' | 'int' | 'real' | 'datetime' | 'dynamic';",
           "/** property name -> [SQL column name, telemetry type] */",
           "export type ColumnMap = Record<string, readonly [string, ColumnType]>;", ""]
    for name, spec in app_tables():
        out.append("/** %s */" % spec["doc"])
        out.append("export interface %s {" % ROW_NAMES[name])
        for col, typ in spec["columns"]:
            out.append("  %s: %s | null;" % (camel(col), TS_TYPES[typ]))
        out.append("}")
        out.append("")
    out.append("export const ENTITY_NAMES = [%s] as const;" % ", ".join("'%s'" % n for n, _ in app_tables()))
    out.append("export type EntityName = (typeof ENTITY_NAMES)[number];")
    out.append("")
    out.append("export const COLUMNS: Record<EntityName, ColumnMap> = {")
    for name, spec in app_tables():
        out.append("  %s: {" % name)
        for col, typ in spec["columns"]:
            out.append("    %s: ['%s', '%s']," % (camel(col), col, typ))
        out.append("  },")
    out.append("};")
    out.append("")
    out.append("export const FIELDS: Record<EntityName, readonly string[]> = {")
    for name, spec in app_tables():
        out.append("  %s: [%s]," % (name, ", ".join("'%s'" % camel(c) for c, _ in spec["columns"])))
    out.append("};")
    out.append("")
    return "\n".join(out)


def metadata_example():
    tables = []
    for name, spec in app_tables():
        cols = []
        for col, typ in spec["columns"]:
            entry = {"columnName": col, "isNullable": True}
            entry.update(SQL_TYPES[typ])
            cols.append(entry)
        tables.append({"tableName": name, "columns": cols})
    return {"source": "eval_lakehouse", "connector": "fabric-sqlanalytics",
            "connectionString": "Data Source=<sql-analytics-endpoint>;Initial Catalog=eval_lakehouse",
            "discoveredAt": "2026-11-04T00:00:00.000Z", "schemas": [{"schemaName": "dbo", "tables": tables}]}


def outputs():
    return {
        ROOT / "app" / "overlay" / "src" / "eval" / "generated" / "contract.ts": contract_ts(),
        ROOT / "app" / "connectors" / "evals" / "metadata.example.json": json.dumps(metadata_example(), indent=2) + "\n",
    }


if __name__ == "__main__":
    for path, text in outputs().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print("wrote", path.relative_to(ROOT))
