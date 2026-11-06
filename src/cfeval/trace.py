"""Capture the DAX that Fabric IQ ran for each Copilot ask.

Source: the Fabric workspace monitoring Eventhouse, table SemanticModelLogs, for
the workspace that holds the semantic models. Rows are matched to asks by the
test user (ExecutingUser) and the ask's time window. No documented field marks
a query as Copilot-generated, so use a dedicated test user and leave a pause
between questions.
"""
from dataclasses import dataclass
from datetime import timedelta

from .clock import iso, parse_iso

WATERMARK_TAG = "cfeval_watermark"

TRACE_KQL = """SemanticModelLogs
| where Timestamp between ({t0} .. {t1})
| where ExecutingUser =~ {upn}
| where OperationName == "QueryEnd"
| where EventText !contains "%s"
| project Timestamp, WorkspaceId, ItemId, ItemName, ApplicationName, OperationName, DurationMs, EventText, CorrelationId
| order by Timestamp asc""" % WATERMARK_TAG

LATEST_KQL = "SemanticModelLogs | where Timestamp > ago(1d) | summarize Latest = max(Timestamp)"

WATERMARK_KQL = """SemanticModelLogs
| where Timestamp > {since}
| where EventText contains {marker}
| summarize Seen = count()"""


def kql_str(value):
    """A KQL string literal."""
    return '"%s"' % str(value).replace("\\", "\\\\").replace('"', '\\"')


def kql_dt(value):
    return "datetime(%s)" % iso(value)


def watermark_dax(marker):
    """A tiny DAX query used to observe ingestion progress, not an ordering fence."""
    return 'EVALUATE ROW("%s", "%s")' % (WATERMARK_TAG, marker)


@dataclass
class FabricQuery:
    query_time: object
    workspace_id: str = ""
    item_id: str = ""
    item_name: str = ""
    application_name: str = ""
    operation_name: str = "QueryEnd"
    duration_ms: float = 0.0
    dax: str = ""
    correlation_id: str = ""


@dataclass
class AskWindow:
    ask_id: str
    start: object
    end: object


class WorkspaceMonitoringSource:
    def __init__(self, query_client, database):
        self.client = query_client
        self.database = database

    def fetch(self, upn, start, end):
        rows = self.client.query(self.database, TRACE_KQL.format(t0=kql_dt(start), t1=kql_dt(end), upn=kql_str(upn)))
        return [FabricQuery(
            query_time=parse_iso(r.get("Timestamp")), workspace_id=str(r.get("WorkspaceId") or ""),
            item_id=str(r.get("ItemId") or ""), item_name=str(r.get("ItemName") or ""),
            application_name=str(r.get("ApplicationName") or ""),
            operation_name=str(r.get("OperationName") or ""), duration_ms=float(r.get("DurationMs") or 0),
            dax=str(r.get("EventText") or ""), correlation_id=str(r.get("CorrelationId") or ""),
        ) for r in rows]

    def latest_timestamp(self):
        rows = self.client.query(self.database, LATEST_KQL)
        return parse_iso(rows[0].get("Latest")) if rows and rows[0].get("Latest") else None

    def watermark_seen(self, marker, since):
        rows = self.client.query(self.database, WATERMARK_KQL.format(since=kql_dt(since), marker=kql_str(marker)))
        return bool(rows and int(rows[0].get("Seen") or 0) > 0)


class TraceCollectionError(RuntimeError):
    def __init__(self, message, queries=()):
        super().__init__(message)
        self.queries = list(queries)


class CombinedMonitoringSource:
    """Read every configured model/decoy workspace; partial coverage cannot settle."""

    def __init__(self, sources):
        self.sources = list(sources)
        if not self.sources:
            raise ValueError("at least one workspace monitoring source is required")

    def fetch(self, upn, start, end):
        queries, errors = [], []
        for source in self.sources:
            try:
                queries.extend(source.fetch(upn, start, end))
            except Exception as exc:
                errors.append("%s: %s" % (source.database, exc))
        if errors:
            raise TraceCollectionError("Workspace monitoring read failed: " + "; ".join(errors), queries)
        return queries

    def latest_timestamp(self):
        timestamps = [source.latest_timestamp() for source in self.sources]
        return min(timestamps) if all(t is not None for t in timestamps) else None

    def watermark_seen(self, marker, since):
        return all(source.watermark_seen(marker, since) for source in self.sources)


def query_key(query):
    return (query.workspace_id, query.item_id, query.correlation_id, query.query_time, query.dax)


def settle_queries(fetch, clock, deadline, poll_s=20.0, settle_s=40.0):
    """Keep collecting after progress, resetting a bounded quiet window on any change.

    A quiet window is an observation heuristic. Monitoring does not promise global
    ordering or that another query cannot arrive after this collection ends.
    """
    collected = {}

    def snapshot():
        collected.update({query_key(q): q for q in fetch()})
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


def correlate(windows, queries, pad_before_s=5.0, pad_after_s=5.0):
    """Assign each query to the ask whose padded window contains it (nearest start wins)."""
    out = {w.ask_id: [] for w in windows}
    pb, pa = timedelta(seconds=pad_before_s), timedelta(seconds=pad_after_s)
    for q in queries:
        hits = [w for w in windows if w.start - pb <= q.query_time <= w.end + pa]
        if hits:
            best = min(hits, key=lambda w: abs((q.query_time - w.start).total_seconds()))
            out[best.ask_id].append(q)
    for ask_id in out:
        out[ask_id].sort(key=lambda q: q.query_time)
    return out


def wait_for_ingestion(source, until, clock, timeout_s=300.0, poll_s=20.0, marker=None, since=None, log=print):
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
            log("Workspace monitoring hasn't caught up after %ss (%s); asks without DAX are marked pending. "
                "Re-score later with 'cfeval rescore'." % (int(timeout_s), "watermark not seen yet" if marker
                                                          else "latest event %s" % (iso(latest) if latest else "none")))
            return None
        clock.sleep(min(poll_s, deadline - clock.monotonic()))


def trace_status(ask_end, latest, pad_after_s=5.0):
    """Event-time progress alone cannot establish that an ask's DAX was captured."""
    if latest is None:
        return "pending"
    return "caught-up" if latest >= ask_end + timedelta(seconds=pad_after_s) else "pending"
