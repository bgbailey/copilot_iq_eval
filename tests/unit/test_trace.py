"""Offline unit tests for cfeval.trace correlation, confidence, routing evidence, and schema coercion."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from cfeval.clock import SimClock
from cfeval.sinks import coerce_row
from cfeval.trace import (
    AskWindow,
    FabricQuery,
    InMemoryMonitoringSource,
    collect_traces,
    compute_correlation_confidence,
    compute_routing_evidence,
    correlate,
    is_noise_dax,
    parse_application_context,
    watermark_dax,
)


def test_parse_application_context_variants() -> None:
    ctx_json = json.dumps(
        {
            "DatasetId": "ds-100",
            "Sources": [{"ReportId": "rep-200", "VisualId": "vis-300"}],
        }
    )
    parsed = parse_application_context(ctx_json)
    assert parsed == {"DatasetId": "ds-100", "ReportId": "rep-200", "VisualId": "vis-300"}

    assert parse_application_context("") == {"DatasetId": "", "ReportId": "", "VisualId": ""}
    assert parse_application_context("{not-valid-json") == {"DatasetId": "", "ReportId": "", "VisualId": ""}


def test_is_noise_dax_filters_system_and_probe_queries() -> None:
    assert is_noise_dax("") is False
    assert is_noise_dax(None) is False
    assert is_noise_dax(watermark_dax("run-1")) is True
    assert is_noise_dax("/* cfeval_watermark:run-1 */ EVALUATE { 1 }") is True
    text_idx_dax = (
        "EVALUATE SELECTCOLUMNS(FILTER(VALUES('Sales'[Region]), "
        "LEN('Sales'[Region]) > 0), \"valueColumn\", 'Sales'[Region])"
    )
    assert is_noise_dax(text_idx_dax) is True
    assert is_noise_dax('EVALUATE SUMMARIZECOLUMNS("FY2025", [Gross Revenue])') is False


def test_fabric_query_to_dict_schema_coercion_compatibility() -> None:
    t0 = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    fq = FabricQuery(
        query_time=t0 + timedelta(seconds=1.5),
        workspace_id="ws-1",
        item_id="item-1",
        item_name="Sales Analytics",
        application_name="PowerBI",
        operation_name="QueryEnd",
        duration_ms=120.0,
        dax='EVALUATE ROW("Gross Revenue", 12840000)',
        correlation_id="corr-1",
        operation_id="op-1",
        application_context='{"DatasetId":"ds-1","Sources":[{"ReportId":"rep-1","VisualId":"vis-1"}]}',
        cpu_time_ms=45.0,
        executing_user="analyst@contoso.com",
    )

    default_row = fq.to_dict(run_id="run-1", ask_id="ask-1", ask_start=t0)
    assert "DatasetId" not in default_row
    assert "ReportId" not in default_row
    assert "VisualId" not in default_row
    coerced = coerce_row("FabricIqQuery", default_row)
    assert coerced["RunId"] == "run-1"
    assert coerced["AskId"] == "ask-1"
    assert coerced["OffsetMs"] == 1500.0
    assert coerced["DaxChars"] == len(fq.dax)

    with_ctx = fq.to_dict(run_id="run-1", ask_id="ask-1", ask_start=t0, include_parsed_context=True)
    assert with_ctx["DatasetId"] == "ds-1"
    assert with_ctx["ReportId"] == "rep-1"
    assert with_ctx["VisualId"] == "vis-1"


def test_correlate_assigns_closest_midpoint_when_padded_windows_overlap() -> None:
    base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    w1 = AskWindow("ask-1", base, base + timedelta(seconds=4))
    w2 = AskWindow("ask-2", base + timedelta(seconds=6), base + timedelta(seconds=10))

    q1 = FabricQuery(
        query_time=base + timedelta(seconds=2),
        workspace_id="w",
        item_id="i",
        item_name="M1",
        application_name="A",
        operation_name="QueryEnd",
        duration_ms=10.0,
        dax="EVALUATE {100}",
    )
    q2 = FabricQuery(
        query_time=base + timedelta(seconds=8),
        workspace_id="w",
        item_id="i",
        item_name="M2",
        application_name="A",
        operation_name="QueryEnd",
        duration_ms=10.0,
        dax="EVALUATE {200}",
    )
    q_out = FabricQuery(
        query_time=base + timedelta(seconds=40),
        workspace_id="w",
        item_id="i",
        item_name="M3",
        application_name="A",
        operation_name="QueryEnd",
        duration_ms=10.0,
        dax="EVALUATE {300}",
    )
    q_noise = FabricQuery(
        query_time=base + timedelta(seconds=2),
        workspace_id="w",
        item_id="i",
        item_name="M1",
        application_name="A",
        operation_name="QueryEnd",
        duration_ms=1.0,
        dax=watermark_dax("m-1"),
    )

    grouped = correlate([w1, w2], [q2, q1, q_out, q_noise], pad_before_s=5.0, pad_after_s=5.0)
    assert [q.dax for q in grouped["ask-1"]] == ["EVALUATE {100}"]
    assert [q.dax for q in grouped["ask-2"]] == ["EVALUATE {200}"]


def test_compute_correlation_confidence_tiers() -> None:
    base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    w1 = AskWindow("ask-1", base, base + timedelta(seconds=4))
    w2_far = AskWindow("ask-2", base + timedelta(seconds=60), base + timedelta(seconds=64))
    w2_near = AskWindow("ask-2", base + timedelta(seconds=5), base + timedelta(seconds=9))

    q = FabricQuery(
        query_time=base + timedelta(seconds=2),
        workspace_id="ws-1",
        item_id="model-guid-1",
        item_name="Sales Analytics",
        application_name="PowerBI",
        operation_name="QueryEnd",
        duration_ms=25.0,
        dax="EVALUATE {1}",
        application_context='{"DatasetId":"model-guid-1","Sources":[{"ReportId":"report-guid-9"}]}',
        executing_user="analyst@contoso.com",
    )

    assert compute_correlation_confidence("disabled", [q]) == "none"
    assert compute_correlation_confidence("observed", []) == "none"
    assert compute_correlation_confidence("observed", [q], matched_via_run_window=True) == "low"

    # High via artifact ID match even when windows overlap
    assert (
        compute_correlation_confidence(
            "observed",
            [q],
            ask_window=w1,
            all_windows=[w1, w2_near],
            artifact_ids={"report-guid-9"},
        )
        == "high"
    )

    # High via non-overlapping window + exact UPN match
    assert (
        compute_correlation_confidence(
            "observed",
            [q],
            ask_window=w1,
            all_windows=[w1, w2_far],
            user_upn="analyst@contoso.com",
        )
        == "high"
    )

    # Medium when windows overlap and no artifact IDs match
    assert (
        compute_correlation_confidence(
            "observed",
            [q],
            ask_window=w1,
            all_windows=[w1, w2_near],
            user_upn="analyst@contoso.com",
        )
        == "medium"
    )


def test_compute_routing_evidence_tiers() -> None:
    q_std = FabricQuery(
        query_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
        workspace_id="w",
        item_id="i",
        item_name="Sales",
        application_name="PowerBI",
        operation_name="QueryEnd",
        duration_ms=10.0,
        dax="EVALUATE {1}",
    )
    q_mcp = FabricQuery(
        query_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
        workspace_id="w",
        item_id="i",
        item_name="Sales",
        application_name="MCP-PowerBI",
        operation_name="QueryEnd",
        duration_ms=10.0,
        dax="EVALUATE {1}",
        operation_id="mcp-tool-call",
    )
    cite = [{"name": "Sales Analytics", "kind": "powerbi_report"}]

    assert compute_routing_evidence("disabled", [], cite, preset="tool_call") == "tool_call"
    assert compute_routing_evidence("observed", [q_mcp], cite) == "tool_call"
    assert compute_routing_evidence("observed", [q_std], cite) == "engine+citations"
    assert compute_routing_evidence("observed", [q_std], []) == "engine-only"
    assert compute_routing_evidence("disabled", [], cite) == "citations-only"
    assert compute_routing_evidence("none", [], []) == "unverified"


def test_collect_traces_with_in_memory_monitoring_and_fallback() -> None:
    clock = SimClock()
    start = clock.now()
    clock.sleep(2.0)
    end = clock.now()

    asks = [
        {
            "AskId": "run1:Q01:1",
            "AskStartUtc": start,
            "AskEndUtc": end,
            "Artifacts": [{"name": "Sales Analytics", "item_id": "rep-123"}],
            "ExpectedArtifactId": "rep-123",
        }
    ]

    disabled = collect_traces(None, run_id="run1", asks=asks, clock=clock)
    assert disabled["run1:Q01:1"].status == "disabled"
    assert disabled["run1:Q01:1"].routing_evidence == "citations-only"

    mon = InMemoryMonitoringSource(clock=clock)
    mon.record(
        FabricQuery(
            query_time=start + timedelta(seconds=1.0),
            workspace_id="ws-1",
            item_id="rep-123",
            item_name="Sales Analytics",
            application_name="PowerBI",
            operation_name="QueryEnd",
            duration_ms=33.0,
            dax='EVALUATE ROW("Revenue", 12840000)',
            executing_user="analyst@contoso.com",
        )
    )

    ev = collect_traces(
        mon,
        run_id="run1",
        asks=asks,
        user_upn="analyst@contoso.com",
        clock=clock,
        wait_seconds=30.0,
        poll_seconds=1.0,
        settle_seconds=2.0,
        log=lambda _m: None,
    )
    ask_ev = ev["run1:Q01:1"]
    assert ask_ev.status == "observed"
    assert ask_ev.correlation_confidence == "high"
    assert ask_ev.routing_evidence == "engine+citations"
    assert len(ask_ev.queries) == 1
    coerced = coerce_row("FabricIqQuery", ask_ev.queries[0])
    assert coerced["ItemName"] == "Sales Analytics"
