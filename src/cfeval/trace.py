"""Capture the DAX that Fabric IQ ran for each Copilot ask.

Source: the Fabric workspace monitoring Eventhouse, table SemanticModelLogs, for
the workspace that holds the semantic models. Rows are matched to asks by the
test user (ExecutingUser), optional artifact/operation identifiers, and the ask's
time window.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .clock import SystemClock, iso, parse_iso
from .interfaces import EngineEvidence

WATERMARK_TAG = "cfeval_watermark"

KQL_SEMANTIC_MODEL_LOGS = (
    """SemanticModelLogs
| where Timestamp between ({t0} .. {t1})
| where ExecutingUser =~ {upn}
| where OperationName == "QueryEnd"
| where EventText !contains "%s"
| extend OperationId = tostring(column_ifexists('OperationId', '')),
         ApplicationContext = tostring(column_ifexists('ApplicationContext', '')),
         CpuTimeMs = todouble(column_ifexists('CpuTimeMs', 0))
| project Timestamp, WorkspaceId, ItemId, ItemName, ApplicationName, OperationName,
          DurationMs, EventText, CorrelationId, OperationId, ApplicationContext, CpuTimeMs, ExecutingUser
| order by Timestamp asc"""
    % WATERMARK_TAG
)

TRACE_KQL = KQL_SEMANTIC_MODEL_LOGS

LATEST_KQL = "SemanticModelLogs | where Timestamp > ago(1d) | summarize Latest = max(Timestamp)"

WATERMARK_KQL = """SemanticModelLogs
| where Timestamp > {since}
| where EventText contains {marker}
| summarize Seen = count()"""

_TEXT_INDEX_NOISE_RE = re.compile(
    r"SELECTCOLUMNS\s*\(\s*(?:FILTER\s*\(\s*)?VALUES\s*\(.*?LEN\s*\(.*?\"valueColumn\"",
    re.IGNORECASE | re.DOTALL,
)
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def kql_str(value: Any) -> str:
    """A KQL string literal."""
    return '"%s"' % str(value).replace("\\", "\\\\").replace('"', '\\"')


def kql_dt(value: Any) -> str:
    return "datetime(%s)" % iso(value)


def watermark_dax(marker: str) -> str:
    """A tiny DAX query used to observe ingestion progress, not an ordering fence."""
    return 'EVALUATE ROW("%s", "%s")' % (WATERMARK_TAG, marker)


def is_noise_dax(dax: str | None) -> bool:
    """Detect watermark markers and internal semantic-model text-index build queries."""
    if not dax:
        return False
    if WATERMARK_TAG in dax:
        return True
    return bool(_TEXT_INDEX_NOISE_RE.search(dax))


def parse_application_context(raw: str | Mapping[str, Any] | None) -> dict[str, str]:
    """Extract DatasetId, ReportId, and VisualId from SemanticModelLogs ApplicationContext."""
    out = {"DatasetId": "", "ReportId": "", "VisualId": ""}
    if not raw:
        return out
    payload: Mapping[str, Any] | None = None
    if isinstance(raw, Mapping):
        payload = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return out
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, Mapping):
                    payload = parsed
            except (TypeError, ValueError):
                payload = None
        if payload is None:
            for pair in re.split(r"[;,]", text):
                if "=" not in pair:
                    continue
                k, v = pair.split("=", 1)
                k_low = k.strip().lower()
                val = v.strip().strip('"').strip("'")
                if k_low == "datasetid":
                    out["DatasetId"] = val
                elif k_low == "reportid":
                    out["ReportId"] = val
                elif k_low == "visualid":
                    out["VisualId"] = val
            return out

    if payload is not None:
        out["DatasetId"] = str(payload.get("DatasetId") or payload.get("datasetId") or "")
        out["ReportId"] = str(payload.get("ReportId") or payload.get("reportId") or "")
        out["VisualId"] = str(payload.get("VisualId") or payload.get("visualId") or "")
        sources = payload.get("Sources") or payload.get("sources") or []
        if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)):
            for src in sources:
                if not isinstance(src, Mapping):
                    continue
                if not out["DatasetId"]:
                    out["DatasetId"] = str(src.get("DatasetId") or src.get("datasetId") or "")
                if not out["ReportId"]:
                    out["ReportId"] = str(src.get("ReportId") or src.get("reportId") or "")
                if not out["VisualId"]:
                    out["VisualId"] = str(src.get("VisualId") or src.get("visualId") or "")
    return out


@dataclass
class FabricQuery:
    query_time: Any
    workspace_id: str = ""
    item_id: str = ""
    item_name: str = ""
    application_name: str = ""
    operation_name: str = "QueryEnd"
    duration_ms: float = 0.0
    dax: str = ""
    correlation_id: str = ""
    operation_id: str = ""
    application_context: str = ""
    cpu_time_ms: float = 0.0
    executing_user: str = ""

    def parsed_context(self) -> dict[str, str]:
        return parse_application_context(self.application_context)

    def to_dict(
        self,
        *,
        run_id: str = "",
        ask_id: str = "",
        ask_start: datetime | None = None,
        include_parsed_context: bool = False,
    ) -> dict[str, Any]:
        offset_ms = None
        if ask_start is not None and isinstance(self.query_time, datetime):
            offset_ms = round((self.query_time - ask_start).total_seconds() * 1000.0, 1)
        row: dict[str, Any] = {
            "RunId": run_id,
            "AskId": ask_id,
            "QueryTimeUtc": self.query_time,
            "OffsetMs": offset_ms,
            "WorkspaceId": self.workspace_id,
            "ItemId": self.item_id,
            "ItemName": self.item_name,
            "ApplicationName": self.application_name,
            "OperationName": self.operation_name,
            "DurationMs": self.duration_ms,
            "Dax": self.dax,
            "DaxChars": len(self.dax or ""),
            "CorrelationId": self.correlation_id,
            "OperationId": self.operation_id,
            "ApplicationContext": self.application_context,
            "CpuTimeMs": self.cpu_time_ms,
        }
        if include_parsed_context:
            ctx = self.parsed_context()
            row["DatasetId"] = ctx["DatasetId"]
            row["ReportId"] = ctx["ReportId"]
            row["VisualId"] = ctx["VisualId"]
        return row


def _normalise_row(raw: Mapping[str, Any]) -> FabricQuery:
    """Normalize a raw SemanticModelLogs Kusto row into a FabricQuery."""
    raw_app_ctx = raw.get("ApplicationContext")
    if isinstance(raw_app_ctx, Mapping):
        app_ctx_str = json.dumps(raw_app_ctx, sort_keys=True)
    else:
        app_ctx_str = str(raw_app_ctx or "")
    ts = raw.get("Timestamp") or raw.get("QueryTimeUtc")
    q_time = ts if isinstance(ts, datetime) else parse_iso(ts)
    return FabricQuery(
        query_time=q_time,
        workspace_id=str(raw.get("WorkspaceId") or ""),
        item_id=str(raw.get("ItemId") or ""),
        item_name=str(raw.get("ItemName") or ""),
        application_name=str(raw.get("ApplicationName") or ""),
        operation_name=str(raw.get("OperationName") or "QueryEnd"),
        duration_ms=float(raw.get("DurationMs") or 0.0),
        dax=str(raw.get("EventText") if raw.get("EventText") is not None else (raw.get("Dax") or "")),
        correlation_id=str(raw.get("CorrelationId") or ""),
        operation_id=str(raw.get("OperationId") or ""),
        application_context=app_ctx_str,
        cpu_time_ms=float(raw.get("CpuTimeMs") or 0.0),
        executing_user=str(raw.get("ExecutingUser") or ""),
    )


_normalize_row = _normalise_row


@dataclass
class AskWindow:
    ask_id: str
    start: Any
    end: Any


class WorkspaceMonitoringSource:
    def __init__(self, query_client: Any, database: str) -> None:
        self.client = query_client
        self.database = database

    def fetch(self, upn: str, start: Any, end: Any) -> list[FabricQuery]:
        rows = self.client.query(
            self.database,
            KQL_SEMANTIC_MODEL_LOGS.format(t0=kql_dt(start), t1=kql_dt(end), upn=kql_str(upn)),
        )
        queries = [_normalise_row(r) for r in rows]
        return [q for q in queries if not is_noise_dax(q.dax)]

    def latest_timestamp(self) -> Any:
        rows = self.client.query(self.database, LATEST_KQL)
        return parse_iso(rows[0].get("Latest")) if rows and rows[0].get("Latest") else None

    def watermark_seen(self, marker: str, since: Any) -> bool:
        rows = self.client.query(self.database, WATERMARK_KQL.format(since=kql_dt(since), marker=kql_str(marker)))
        return bool(rows and int(rows[0].get("Seen") or 0) > 0)


class TraceCollectionError(RuntimeError):
    def __init__(self, message: str, queries: Sequence[FabricQuery] = ()) -> None:
        super().__init__(message)
        self.queries = list(queries)


class CombinedMonitoringSource:
    """Read every configured model/decoy workspace; partial coverage cannot settle."""

    def __init__(self, sources: Sequence[Any]) -> None:
        self.sources = list(sources)
        if not self.sources:
            raise ValueError("at least one workspace monitoring source is required")

    def fetch(self, upn: str, start: Any, end: Any) -> list[FabricQuery]:
        queries: list[FabricQuery] = []
        errors: list[str] = []
        for source in self.sources:
            try:
                queries.extend(source.fetch(upn, start, end))
            except Exception as exc:
                errors.append("%s: %s" % (getattr(source, "database", "monitoring"), exc))
        if errors:
            raise TraceCollectionError("Workspace monitoring read failed: " + "; ".join(errors), queries)
        return queries

    def latest_timestamp(self) -> Any:
        timestamps = [source.latest_timestamp() for source in self.sources]
        return min(timestamps) if all(t is not None for t in timestamps) else None

    def watermark_seen(self, marker: str, since: Any) -> bool:
        return all(source.watermark_seen(marker, since) for source in self.sources)


def query_key(query: FabricQuery) -> tuple[Any, ...]:
    return (
        query.workspace_id,
        query.item_id,
        query.correlation_id or query.operation_id,
        query.query_time,
        query.dax,
    )


def settle_queries(
    fetch: Callable[[], list[FabricQuery]],
    clock: Any,
    deadline: float,
    poll_s: float = 20.0,
    settle_s: float = 40.0,
) -> tuple[list[FabricQuery], bool]:
    """Keep collecting after progress, resetting a bounded quiet window on any change.

    A quiet window is an observation heuristic. Monitoring does not promise global
    ordering or that another query cannot arrive after this collection ends.
    """
    collected: dict[tuple[Any, ...], FabricQuery] = {}

    def snapshot() -> list[FabricQuery]:
        for q in fetch():
            if not is_noise_dax(q.dax):
                collected[query_key(q)] = q
        return list(collected.values())

    queries = snapshot()
    signature = {(query_key(q), q.duration_ms) for q in queries}
    quiet_since = clock.monotonic()
    quiet_seconds = max(settle_s, 2 * poll_s)
    while clock.monotonic() - quiet_since < quiet_seconds:
        remaining = deadline - clock.monotonic()
        if remaining <= 0:
            return queries, False
        clock.sleep(min(poll_s, remaining))
        queries = snapshot()
        current = {(query_key(q), q.duration_ms) for q in queries}
        if current != signature:
            signature, quiet_since = current, clock.monotonic()
    return queries, True


def _windows_overlap(a: AskWindow, b: AskWindow, pad_before_s: float, pad_after_s: float) -> bool:
    pb, pa = timedelta(seconds=pad_before_s), timedelta(seconds=pad_after_s)
    a0, a1 = a.start - pb, a.end + pa
    b0, b1 = b.start - pb, b.end + pa
    return a0 <= b1 and b0 <= a1


def extract_artifact_ids(artifacts: Sequence[Mapping[str, Any]] | None) -> set[str]:
    """Extract item/report/dataset GUIDs or explicit ids from cited artifacts."""
    ids: set[str] = set()
    for art in artifacts or ():
        if not isinstance(art, Mapping):
            continue
        for key in ("id", "item_id", "itemId", "artifact_id", "report_id", "dataset_id", "operation_id"):
            val = str(art.get(key) or "").strip()
            if val:
                ids.add(val.lower())
        url = str(art.get("url") or art.get("seeMoreWebUrl") or "")
        for m in _UUID_RE.findall(url):
            ids.add(m.lower())
    # Exclude the synthetic workspace id if extracted from /groups/<ws>/reports/<rpt>
    for art in artifacts or ():
        url = str((art or {}).get("url") or (art or {}).get("seeMoreWebUrl") or "")
        grp_match = re.search(r"/groups/([0-9a-f-]{36})/", url, re.IGNORECASE)
        if grp_match and len(ids) > 1:
            ids.discard(grp_match.group(1).lower())
    return ids


def correlate(
    windows: Sequence[AskWindow],
    queries: Sequence[FabricQuery],
    pad_before_s: float = 5.0,
    pad_after_s: float = 5.0,
) -> dict[str, list[FabricQuery]]:
    """Assign each query to the ask whose padded window contains it (nearest start wins)."""
    out: dict[str, list[FabricQuery]] = {w.ask_id: [] for w in windows}
    pb, pa = timedelta(seconds=pad_before_s), timedelta(seconds=pad_after_s)
    for q in queries:
        if is_noise_dax(q.dax) or q.query_time is None:
            continue
        hits = [w for w in windows if w.start - pb <= q.query_time <= w.end + pa]
        if hits:
            best = min(hits, key=lambda w: abs((q.query_time - w.start).total_seconds()))
            out[best.ask_id].append(q)
    for ask_id in out:
        out[ask_id].sort(key=lambda q: q.query_time)
    return out


def compute_correlation_confidence(
    status: str,
    queries: Sequence[Any],
    *,
    ask_window: AskWindow | None = None,
    all_windows: Sequence[AskWindow] = (),
    artifact_ids: Collection[str] = (),
    user_upn: str = "",
    pad_before_s: float = 5.0,
    pad_after_s: float = 5.0,
    matched_via_run_window: bool = False,
) -> str:
    """Compute correlation confidence ('high' | 'medium' | 'low' | 'none') for an ask's queries."""
    if status != "observed" or not queries:
        return "none"
    if matched_via_run_window:
        return "low"

    norm_ids = {str(x).strip().lower() for x in artifact_ids if str(x).strip()}
    for q in queries:
        raw_op = getattr(q, "operation_id", "") if not isinstance(q, Mapping) else q.get("OperationId")
        op_id = str(raw_op or "").lower()
        item_id = str(getattr(q, "item_id", "") if not isinstance(q, Mapping) else q.get("ItemId") or "").lower()
        raw_ctx = getattr(q, "application_context", "") if not isinstance(q, Mapping) else q.get("ApplicationContext")
        ctx = parse_application_context(raw_ctx)
        ctx_ids = {v.lower() for v in ctx.values() if v}
        if item_id:
            ctx_ids.add(item_id)
        if op_id:
            ctx_ids.add(op_id)
        if norm_ids and (norm_ids & ctx_ids):
            return "high"

    if ask_window is not None:
        others = [w for w in all_windows if w.ask_id != ask_window.ask_id]
        overlaps = any(_windows_overlap(ask_window, other, pad_before_s, pad_after_s) for other in others)
        if not overlaps and bool(user_upn.strip()):
            upn_cf = user_upn.strip().casefold()
            exact_upn = True
            for q in queries:
                q_user = (
                    getattr(q, "executing_user", "")
                    if not isinstance(q, Mapping)
                    else str(q.get("ExecutingUser") or "")
                ).strip()
                if q_user and q_user.casefold() != upn_cf:
                    exact_upn = False
                    break
            if exact_upn:
                return "high"

    return "medium"


def compute_routing_evidence(
    status: str,
    queries: Sequence[Any],
    citations: Sequence[Any],
    *,
    preset: str = "",
) -> str:
    """Classify routing evidence tier for an ask."""
    if preset == "tool_call":
        return "tool_call"
    has_queries = status == "observed" and bool(queries)
    if has_queries and any(
        (
            (isinstance(q, Mapping) and str(q.get("OperationId") or "") == "mcp-tool-call")
            or str(getattr(q, "operation_id", "") or "") == "mcp-tool-call"
        )
        for q in queries
    ):
        return "tool_call"
    has_citations = bool(citations)
    if has_queries and has_citations:
        return "engine+citations"
    if has_queries:
        return "engine-only"
    if status in ("disabled", "none") and has_citations:
        return "citations-only"
    return "unverified"


def wait_for_ingestion(
    source: Any,
    until: Any,
    clock: Any,
    timeout_s: float = 300.0,
    poll_s: float = 20.0,
    marker: str | None = None,
    since: Any = None,
    log: Callable[[str], Any] = print,
) -> str | None:
    """Wait for a marker or later event: progress only, never trace completeness."""
    if timeout_s < 0 or poll_s <= 0:
        raise ValueError("trace timeout must be non-negative and polling must be positive")
    deadline = clock.monotonic() + timeout_s
    latest = None
    while True:
        if marker:
            if source.watermark_seen(marker, since):
                return "watermark"
        else:
            latest = source.latest_timestamp()
            if latest is not None and latest >= until:
                return "latest"
        if clock.monotonic() >= deadline:
            log(
                "Workspace monitoring hasn't caught up after %ss (%s); asks without DAX are marked pending. "
                "Re-score later with 'cfeval rescore'."
                % (
                    int(timeout_s),
                    "watermark not seen yet" if marker else "latest event %s" % (iso(latest) if latest else "none"),
                )
            )
            return None
        clock.sleep(min(poll_s, deadline - clock.monotonic()))


def trace_status(ask_end: Any, latest: Any, pad_after_s: float = 5.0) -> str:
    """Event-time progress alone cannot establish that an ask's DAX was captured."""
    if latest is None:
        return "pending"
    return "caught-up" if latest >= ask_end + timedelta(seconds=pad_after_s) else "pending"


def collect_traces(
    monitoring: Any,
    *,
    run_id: str,
    asks: Sequence[Mapping[str, Any]],
    started: datetime | None = None,
    ended: datetime | None = None,
    user_upn: str = "",
    watermark: Any = None,
    clock: Any = None,
    wait_seconds: float = 300.0,
    poll_seconds: float = 20.0,
    settle_seconds: float = 40.0,
    pad_before_s: float = 5.0,
    pad_after_s: float = 5.0,
    broad_fallback: bool = True,
    log: Callable[[str], Any] = print,
) -> dict[str, EngineEvidence]:
    """Collect and correlate workspace-monitoring DAX queries into per-ask EngineEvidence."""
    clk = clock or SystemClock()
    if monitoring is None:
        out_disabled: dict[str, EngineEvidence] = {}
        for a in asks:
            ask_id = str(a["AskId"])
            arts = a.get("Artifacts") or []
            out_disabled[ask_id] = EngineEvidence(
                status="disabled",
                queries=[],
                correlation_confidence="none",
                routing_evidence=compute_routing_evidence("disabled", [], arts),
                detail="workspace monitoring disabled",
            )
        return out_disabled

    if not asks:
        return {}

    windows: list[AskWindow] = []
    for a in asks:
        s_raw = a.get("AskStartUtc") or started
        e_raw = a.get("AskEndUtc") or ended or s_raw
        s_dt = s_raw if isinstance(s_raw, datetime) else parse_iso(s_raw)
        e_dt = e_raw if isinstance(e_raw, datetime) else parse_iso(e_raw)
        windows.append(AskWindow(str(a["AskId"]), s_dt, e_dt))

    first = started or min(w.start for w in windows)
    last = ended or max(w.end for w in windows)
    pb = timedelta(seconds=pad_before_s)
    pa = timedelta(seconds=max(pad_after_s, settle_seconds))
    deadline = clk.monotonic() + wait_seconds

    marker: str | None = None
    if watermark is not None:
        marker = "%s-wm" % (run_id or "run")
        try:
            watermark.send(marker)
        except Exception as exc:
            log("DAX watermark query failed (%s); falling back to the newest logged event." % exc)
            marker = None

    queries: list[FabricQuery] = []
    settled = False
    capture_error = ""

    def fetch() -> list[FabricQuery]:
        nonlocal queries
        found = monitoring.fetch(user_upn, first - pb, last + pa)
        merged = {query_key(q): q for q in queries}
        for q in found:
            if not is_noise_dax(q.dax):
                merged[query_key(q)] = q
        queries = list(merged.values())
        return queries

    try:
        caught = wait_for_ingestion(
            monitoring,
            last + timedelta(seconds=pad_after_s),
            clk,
            max(0.0, deadline - clk.monotonic()),
            poll_seconds,
            marker=marker,
            since=first - pb,
            log=log,
        )
        if caught:
            queries, settled = settle_queries(fetch, clk, deadline, poll_seconds, settle_seconds)
        else:
            queries = fetch()
    except Exception as exc:
        capture_error = str(exc)
        queries = list(getattr(exc, "queries", queries))

    by_ask = correlate(windows, queries, pad_before_s=pad_before_s, pad_after_s=pad_after_s)
    assigned_keys = {query_key(q) for qs in by_ask.values() for q in qs}
    unassigned = [q for q in queries if query_key(q) not in assigned_keys and not is_noise_dax(q.dax)]

    evidence: dict[str, EngineEvidence] = {}
    for a, w in zip(asks, windows, strict=True):
        ask_id = str(a["AskId"])
        found = list(by_ask.get(ask_id, []))
        via_run_window = False
        if not found and broad_fallback and len(windows) == 1 and unassigned:
            found = sorted(unassigned, key=lambda q: q.query_time)
            via_run_window = True

        if capture_error:
            status = "error"
        elif settled and found:
            status = "observed"
        elif settled and not found:
            status = "none"
        else:
            status = "pending"

        arts = a.get("Artifacts") or []
        art_ids = extract_artifact_ids(arts)
        expected_art_id = str(a.get("ExpectedArtifactId") or "").strip()
        if expected_art_id:
            art_ids.add(expected_art_id.lower())

        conf = compute_correlation_confidence(
            status,
            found,
            ask_window=w,
            all_windows=windows,
            artifact_ids=art_ids,
            user_upn=user_upn,
            pad_before_s=pad_before_s,
            pad_after_s=pad_after_s,
            matched_via_run_window=via_run_window,
        )
        routing = compute_routing_evidence(
            status,
            found,
            arts,
            preset=str(getattr(monitoring, "routing_evidence_preset", "") or ""),
        )
        evidence[ask_id] = EngineEvidence(
            status=status,
            queries=[q.to_dict(run_id=run_id, ask_id=ask_id, ask_start=w.start) for q in found],
            correlation_confidence=conf,
            routing_evidence=routing,
            detail=capture_error or ("settled" if settled else "unsettled"),
        )
    return evidence


class WorkspaceMonitoringEvidenceSource:
    """Adapter wrapping WorkspaceMonitoringSource + collect_traces to satisfy EvidenceSource."""

    kind = "engine_query"

    def __init__(
        self,
        monitoring: Any,
        *,
        watermark: Any = None,
        clock: Any = None,
        wait_seconds: float = 300.0,
        poll_seconds: float = 20.0,
        settle_seconds: float = 40.0,
        pad_before_s: float = 5.0,
        pad_after_s: float = 5.0,
        log: Callable[[str], Any] = print,
    ) -> None:
        self.monitoring = monitoring
        self.watermark = watermark
        self.clock = clock
        self.wait_seconds = wait_seconds
        self.poll_seconds = poll_seconds
        self.settle_seconds = settle_seconds
        self.pad_before_s = pad_before_s
        self.pad_after_s = pad_after_s
        self.log = log

    def collect(
        self,
        *,
        run_id: str,
        asks: list[dict[str, Any]],
        started: datetime,
        ended: datetime,
        user_upn: str = "",
    ) -> dict[str, EngineEvidence]:
        return collect_traces(
            self.monitoring,
            run_id=run_id,
            asks=asks,
            started=started,
            ended=ended,
            user_upn=user_upn,
            watermark=self.watermark,
            clock=self.clock,
            wait_seconds=self.wait_seconds,
            poll_seconds=self.poll_seconds,
            settle_seconds=self.settle_seconds,
            pad_before_s=self.pad_before_s,
            pad_after_s=self.pad_after_s,
            log=self.log,
        )


class InMemoryMonitoringSource:
    """Zero-lag in-memory monitoring source for targets that record DAX directly."""

    def __init__(
        self,
        queries: Sequence[FabricQuery] = (),
        *,
        clock: Any = None,
        routing_evidence_preset: str = "",
    ) -> None:
        self._queries: list[FabricQuery] = list(queries)
        self._clock = clock or SystemClock()
        self.routing_evidence_preset = routing_evidence_preset

    def record(self, query: FabricQuery) -> None:
        self._queries.append(query)

    def extend(self, queries: Sequence[FabricQuery]) -> None:
        self._queries.extend(queries)

    def queries(self) -> list[FabricQuery]:
        return list(self._queries)

    def clear(self) -> None:
        self._queries.clear()

    def latest_timestamp(self) -> datetime:
        now_fn = getattr(self._clock, "now", None)
        base = now_fn() if callable(now_fn) else datetime.now(timezone.utc)
        if not isinstance(base, datetime):
            base = datetime.now(timezone.utc)
        if self._queries:
            latest_q = max(q.query_time for q in self._queries if isinstance(q.query_time, datetime))
            if latest_q > base:
                base = latest_q
        return base + timedelta(seconds=60)

    def watermark_seen(self, marker: str, since: Any = None) -> bool:
        return True

    def fetch(self, upn: str = "", start: Any = None, end: Any = None) -> list[FabricQuery]:
        start_dt = parse_iso(start) if start is not None and not isinstance(start, datetime) else start
        end_dt = parse_iso(end) if end is not None and not isinstance(end, datetime) else end
        upn_cf = (upn or "").strip().casefold()
        out: list[FabricQuery] = []
        for q in self._queries:
            if is_noise_dax(q.dax):
                continue
            if start_dt is not None and q.query_time < start_dt:
                continue
            if end_dt is not None and q.query_time > end_dt:
                continue
            if upn_cf and q.executing_user and q.executing_user.strip().casefold() != upn_cf:
                continue
            out.append(q)
        return sorted(out, key=lambda item: item.query_time)
