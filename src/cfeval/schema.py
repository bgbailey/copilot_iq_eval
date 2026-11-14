"""Telemetry schema: the single source of truth for Eventhouse tables.

Every table is keyed by RunId; ask-level tables also carry AskId, so a Copilot
ask, the DAX Fabric IQ ran for it, its scores and its stage timings join on
AskId. Schema evolution is strictly additive: existing column names and types
remain unchanged while v2 columns are appended at the end of each table.
"""

import hashlib
import json
from typing import Any

SCHEMA_VERSION = 2

ROW_ID_KEYS = {
    "EvalRun": ("RunId", "Status", "EndedUtc"),
    "EvalQuestion": ("RunId", "QuestionId"),
    "EvalAsk": ("RunId", "AskId"),
    "FabricIqQuery": ("RunId", "AskId", "QueryTimeUtc", "ItemId", "DurationMs", "Dax"),
    "EvalScore": ("RunId", "AskId", "Backend", "Check", "ScoredUtc"),
    "EvalResult": ("RunId", "AskId", "Backend", "ScoredUtc"),
    "EvalEvent": ("RunId", "AskId", "Stage", "EventTimeUtc", "DurationMs", "Status"),
}


def compute_row_id(*parts: object) -> str:
    """Deterministic SHA-256 hex digest for idempotent ingestion and deduplication."""
    normalized = [
        json.dumps(p, sort_keys=True, default=str) if isinstance(p, (dict, list)) else str(p if p is not None else "")
        for p in parts
    ]
    return hashlib.sha256("\x1f".join(normalized).encode("utf-8")).hexdigest()


def table_row_id(table: str, row: dict) -> str:
    keys = ROW_ID_KEYS.get(table, ("RunId",))
    return compute_row_id(table, *[row.get(k) for k in keys])


TABLES: dict[str, dict[str, Any]] = {
    "EvalRun": {
        "doc": "One row per evaluation run (written when the run finishes).",
        "app": True,
        "columns": [
            ("RunId", "string"),
            ("RunName", "string"),
            ("EvalOption", "string"),
            ("Surface", "string"),
            ("StartedUtc", "datetime"),
            ("EndedUtc", "datetime"),
            ("Status", "string"),
            ("Host", "string"),
            ("HarnessVersion", "string"),
            ("GoldenSetName", "string"),
            ("GoldenSetHash", "string"),
            ("QuestionCount", "int"),
            ("AskCount", "int"),
            ("Repeats", "int"),
            ("ExplainMode", "string"),
            ("TraceEnabled", "int"),
            ("TestUser", "string"),
            ("JudgeModel", "string"),
            ("FoundryEvalId", "string"),
            ("FoundryRunId", "string"),
            ("FoundryReportUrl", "string"),
            ("PassRate", "real"),
            ("ValueAccuracy", "real"),
            ("ArtifactAccuracy", "real"),
            ("ModelAccuracy", "real"),
            ("LatencyP50Ms", "real"),
            ("LatencyP95Ms", "real"),
            ("Notes", "string"),
            # v2 additive columns
            ("RowId", "string"),
            ("Target", "string"),
            ("K", "int"),
            ("PassPowK", "real"),
            ("WilsonLow", "real"),
            ("WilsonHigh", "real"),
            ("JudgePromptHash", "string"),
            ("JudgeCalibrationId", "string"),
            ("GatePolicyHash", "string"),
            ("SchemaVersion", "int"),
        ],
    },
    "EvalQuestion": {
        "doc": "Snapshot of the golden set used by each run.",
        "app": True,
        "columns": [
            ("RunId", "string"),
            ("QuestionId", "string"),
            ("Question", "string"),
            ("Category", "string"),
            ("ExpectedArtifact", "string"),
            ("ArtifactAliases", "string"),
            ("ExpectedModel", "string"),
            ("Decoys", "string"),
            ("ExpectedValue", "real"),
            ("Unit", "string"),
            ("RelTol", "real"),
            ("AbsTol", "real"),
            ("ExpectedAnswer", "string"),
            ("ReferenceDax", "string"),
            ("Criticality", "string"),
            # v2 additive columns
            ("RowId", "string"),
            ("ExpectedArtifactId", "string"),
            ("CaseType", "string"),
            ("Persona", "string"),
            ("Tags", "string"),
            ("Intent", "string"),
            ("Gates", "string"),
            ("Paraphrase", "string"),
        ],
    },
    "EvalAsk": {
        "doc": "One row per question asked: the answer, cited artifacts and the follow-up 'why'.",
        "app": False,
        "columns": [
            ("RunId", "string"),
            ("AskId", "string"),
            ("QuestionId", "string"),
            ("Attempt", "int"),
            ("Question", "string"),
            ("TestUser", "string"),
            ("ConversationId", "string"),
            ("AskStartUtc", "datetime"),
            ("AskEndUtc", "datetime"),
            ("LatencyMs", "real"),
            ("Status", "string"),
            ("HttpStatus", "int"),
            ("Error", "string"),
            ("Answer", "string"),
            ("AnswerChars", "int"),
            ("Artifacts", "dynamic"),
            ("ArtifactNames", "string"),
            ("PowerBiCited", "int"),
            ("ExplainMode", "string"),
            ("Why", "string"),
            ("WhyJson", "dynamic"),
            ("WhyLatencyMs", "real"),
            ("AttributionCount", "int"),
            # v2 additive columns
            ("RowId", "string"),
            ("Target", "string"),
            ("Persona", "string"),
        ],
    },
    "FabricIqQuery": {
        "doc": "DAX queries Fabric IQ ran for each ask, from workspace monitoring (SemanticModelLogs).",
        "app": True,
        "columns": [
            ("RunId", "string"),
            ("AskId", "string"),
            ("QueryTimeUtc", "datetime"),
            ("OffsetMs", "real"),
            ("WorkspaceId", "string"),
            ("ItemId", "string"),
            ("ItemName", "string"),
            ("ApplicationName", "string"),
            ("OperationName", "string"),
            ("DurationMs", "real"),
            ("Dax", "string"),
            ("DaxChars", "int"),
            ("CorrelationId", "string"),
            # v2 additive columns
            ("RowId", "string"),
            ("OperationId", "string"),
            ("ApplicationContext", "string"),
            ("CpuTimeMs", "real"),
        ],
    },
    "EvalScore": {
        "doc": "One row per check per ask, from either scoring backend.",
        "app": False,
        "columns": [
            ("RunId", "string"),
            ("AskId", "string"),
            ("QuestionId", "string"),
            ("Backend", "string"),
            ("Check", "string"),
            ("Evaluator", "string"),
            ("Score", "real"),
            ("Outcome", "string"),
            ("Reason", "string"),
            ("Details", "dynamic"),
            ("ScoredUtc", "datetime"),
            # v2 additive columns
            ("RowId", "string"),
        ],
    },
    "EvalResult": {
        "doc": "One row per ask per scoring backend: verdict, accuracy, routing, DAX and latency in one place.",
        "app": True,
        "columns": [
            ("RunId", "string"),
            ("AskId", "string"),
            ("QuestionId", "string"),
            ("Attempt", "int"),
            ("Question", "string"),
            ("Category", "string"),
            ("Criticality", "string"),
            ("TestUser", "string"),
            ("AskStartUtc", "datetime"),
            ("Backend", "string"),
            ("Verdict", "string"),
            ("ValueScore", "real"),
            ("ArtifactScore", "real"),
            ("ModelScore", "real"),
            ("JudgeAnswerScore", "real"),
            ("WhyScore", "real"),
            ("DecoyHit", "int"),
            ("PowerBiCited", "int"),
            ("ExpectedArtifact", "string"),
            ("CitedArtifacts", "string"),
            ("ExpectedModel", "string"),
            ("QueriedModels", "string"),
            ("ExpectedValue", "real"),
            ("ExtractedValue", "real"),
            ("ValueErrorPct", "real"),
            ("LatencyMs", "real"),
            ("WhyLatencyMs", "real"),
            ("DaxQueryCount", "int"),
            ("DaxTotalMs", "real"),
            ("DaxMaxMs", "real"),
            ("FirstDaxOffsetMs", "real"),
            ("TraceStatus", "string"),
            ("AnswerPreview", "string"),
            ("WhyPreview", "string"),
            ("Reasons", "string"),
            ("JudgeNotes", "string"),
            ("Error", "string"),
            ("ScoredUtc", "datetime"),
            # v2 additive columns
            ("RowId", "string"),
            ("CaseType", "string"),
            ("Persona", "string"),
            ("MatchKind", "string"),
            ("ExtractionMethod", "string"),
            ("RoutingEvidence", "string"),
            ("CorrelationConfidence", "string"),
        ],
    },
    "EvalEvent": {
        "doc": "Stage timings for end-to-end telemetry: ask, follow-up, trace, scoring, publish.",
        "app": True,
        "columns": [
            ("RunId", "string"),
            ("AskId", "string"),
            ("EventTimeUtc", "datetime"),
            ("Stage", "string"),
            ("DurationMs", "real"),
            ("Status", "string"),
            ("Details", "dynamic"),
            # v2 additive columns
            ("RowId", "string"),
        ],
    },
}


def column_names(table):
    return [c for c, _ in TABLES[table]["columns"]]


def column_types(table):
    return dict(TABLES[table]["columns"])
