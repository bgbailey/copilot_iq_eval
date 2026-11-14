"""Generate the Eventhouse setup script from the schema."""

import json
from importlib import resources

from .schema import TABLES

OPTIONAL_MARK = "// optional"


def table_commands():
    cmds = []
    for name, spec in TABLES.items():
        cols = ", ".join("%s:%s" % (c, t) for c, t in spec["columns"])
        cmds.append(
            '.create-merge table %s (%s) with (folder="cfeval", docstring="%s")'
            % (name, cols, spec["doc"].replace('"', "'"))
        )
    return cmds


def mapping_commands():
    cmds = []
    for name, spec in TABLES.items():
        mapping = [{"column": c, "Properties": {"Path": "$.%s" % c}} for c, _ in spec["columns"]]
        cmds.append(
            ".create-or-alter table %s ingestion json mapping \"%s_json\" '%s'"
            % (name, name, json.dumps(mapping, separators=(",", ":")))
        )
    return cmds


def policy_commands(database, onelake_latency_minutes=5):
    if not database or any(c in database for c in "'[]\\\r\n"):
        raise ValueError("database must be a non-empty name without KQL delimiters")
    if not isinstance(onelake_latency_minutes, int) or not 5 <= onelake_latency_minutes <= 180:
        raise ValueError("OneLake latency must be between 5 and 180 minutes")
    cmds = [
        "%s: lower queued-ingestion latency for demos\n"
        % OPTIONAL_MARK
        + '.alter database [\'%s\'] policy ingestionbatching \'{"MaximumBatchingTimeSpan":"00:00:10",'
        '"MaximumNumberOfItems":50,"MaximumRawDataSizeMB":100}\'' % database,
        "%s: streaming ingestion (the harness falls back to queued ingestion)\n" % OPTIONAL_MARK
        + ".alter database ['%s'] policy streamingingestion enable" % database,
    ]
    for name, spec in TABLES.items():
        if spec.get("app"):
            cmds.append(
                ".alter-merge table %s policy mirroring dataformat=parquet with "
                "(IsEnabled=true, TargetLatencyInMinutes=%d)" % (name, onelake_latency_minutes)
            )
    return cmds


def function_commands():
    text = resources.files("cfeval").joinpath("kql/functions.kql").read_text(encoding="utf-8")
    return [block.strip() for block in text.split("\n\n\n") if block.strip().startswith(".create-or-alter")]


def setup_commands(database="copilot_eval", onelake_latency_minutes=5):
    """Whole commands in order; an optional command carries its comment in the same string."""
    return (
        table_commands() + mapping_commands() + policy_commands(database, onelake_latency_minutes) + function_commands()
    )


def setup_script(database="copilot_eval", onelake_latency_minutes=5):
    out = [
        "// Copilot Chat x Fabric IQ evaluation: Eventhouse setup for database '%s'" % database,
        "// Run each command in a KQL queryset (select a command, then Run), or run: python -m cfeval setup-eventhouse",
        "// Only ingestion tuning is best effort. OneLake availability is required for the Fabric app.",
        "",
    ]
    for cmd in setup_commands(database, onelake_latency_minutes):
        out.append(cmd if cmd.startswith("//") else cmd + "\n")
    return "\n".join(out)
