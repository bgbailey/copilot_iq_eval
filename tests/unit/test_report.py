"""Offline unit tests for HTML5 report rendering, XSS escaping, McNemar comparison, and OTel spans."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cfeval.otel import export_otel_spans
from cfeval.report import render_html_report
from cfeval.sinks import JsonlSink


def _seed_run_dir(
    folder: Path,
    *,
    run_id: str,
    run_name: str,
    verdicts: list[tuple[str, str, str]],
    xss_payload: str = "",
) -> Path:
    sink = JsonlSink(folder)
    t0 = datetime(2026, 5, 1, 14, 0, 0, tzinfo=timezone.utc)
    n_pass = sum(1 for (_qid, v, _mk) in verdicts if v == "PASS")
    sink.write(
        "EvalRun",
        [
            {
                "RunId": run_id,
                "RunName": run_name + xss_payload,
                "EvalOption": "fabric-native",
                "StartedUtc": t0,
                "EndedUtc": t0 + timedelta(seconds=30),
                "QuestionCount": len(verdicts),
                "AskCount": len(verdicts),
                "Repeats": 1,
                "TraceEnabled": 1,
                "ExplainMode": "followup",
                "Target": "mcp-agent",
                "Surface": "mcp-agent",
                "PassRate": n_pass / max(len(verdicts), 1),
                "Status": "completed",
            }
        ],
    )

    q_rows = []
    ask_rows = []
    res_rows = []
    iq_rows = []
    for idx, (qid, v_str, match_kind) in enumerate(verdicts, start=1):
        ask_id = f"{run_id}:{qid}:1"
        q_text = f"Question {qid}{xss_payload}"
        ans_text = f"Answer for {qid} is $12.84M.{xss_payload}"
        dax_text = f'EVALUATE ROW("Metric", {idx * 100}) /* {xss_payload} */'

        q_rows.append(
            {
                "RunId": run_id,
                "QuestionId": qid,
                "Question": q_text,
                "Category": "named-source" if idx % 2 else "disambiguation",
                "ExpectedArtifact": "Sales Analytics",
                "ExpectedModel": "Sales Analytics",
                "ExpectedValue": 12840000.0,
                "Unit": "currency",
                "RelTol": 0.005,
                "AbsTol": 0.0,
                "Criticality": "critical",
            }
        )
        ask_rows.append(
            {
                "RunId": run_id,
                "AskId": ask_id,
                "QuestionId": qid,
                "Attempt": 1,
                "Question": q_text,
                "ConversationId": f"conv-{idx}",
                "TestUser": "eval.tester@contoso.com",
                "AskStartUtc": t0 + timedelta(seconds=idx * 2),
                "AskEndUtc": t0 + timedelta(seconds=idx * 2 + 1),
                "LatencyMs": 1000.0 + idx * 100.0,
                "HttpStatus": 200,
                "Status": "ok",
                "Answer": ans_text,
                "Why": "Sales Analytics",
                "Artifacts": [{"name": f"Sales Analytics{xss_payload}", "kind": "powerbi_report"}],
            }
        )
        res_rows.append(
            {
                "RunId": run_id,
                "AskId": ask_id,
                "QuestionId": qid,
                "Attempt": 1,
                "Question": q_text,
                "Category": "named-source" if idx % 2 else "disambiguation",
                "Criticality": "critical",
                "TestUser": "eval.tester@contoso.com",
                "AskStartUtc": t0 + timedelta(seconds=idx * 2),
                "Backend": "fabric-native",
                "Verdict": v_str,
                "ValueScore": 1.0 if v_str == "PASS" else 0.0,
                "ArtifactScore": 1.0,
                "ModelScore": 1.0,
                "DecoyHit": 0,
                "PowerBiCited": 1,
                "ExpectedArtifact": "Sales Analytics",
                "CitedArtifacts": f"Sales Analytics{xss_payload}",
                "ExpectedModel": "Sales Analytics",
                "QueriedModels": "Sales Analytics",
                "ExtractedValue": 12840000.0 if v_str == "PASS" else 9000000.0,
                "ExpectedValue": 12840000.0,
                "TraceStatus": "observed",
                "DaxQueryCount": 1,
                "LatencyMs": 1000.0 + idx * 100.0,
                "AnswerPreview": ans_text,
                "Reasons": "" if v_str == "PASS" else f"value mismatch {xss_payload}",
                "ScoredUtc": t0 + timedelta(seconds=25),
                "CaseType": "scalar",
                "MatchKind": match_kind,
                "ExtractionMethod": "first",
                "RoutingEvidence": "tool_call",
                "CorrelationConfidence": "high",
            }
        )
        iq_rows.append(
            {
                "RunId": run_id,
                "AskId": ask_id,
                "QueryTimeUtc": t0 + timedelta(seconds=idx * 2 + 0.5),
                "OffsetMs": 500.0,
                "WorkspaceId": "ws-1",
                "ItemId": "item-1",
                "ItemName": "Sales Analytics",
                "ApplicationName": "MCP-PowerBI",
                "OperationName": "QueryEnd",
                "DurationMs": 45.0,
                "Dax": dax_text,
                "DaxChars": len(dax_text),
                "CorrelationId": f"corr-{idx}",
                "OperationId": "mcp-tool-call",
            }
        )

    sink.write("EvalQuestion", q_rows)
    sink.write("EvalAsk", ask_rows)
    sink.write("EvalResult", res_rows)
    sink.write("FabricIqQuery", iq_rows)
    return folder


def test_render_html_report_cards_details_and_strict_xss_escaping(tmp_path: Path) -> None:
    xss = "<script>alert('xss')</script><img src=x onerror=alert(1)>"
    run_dir = _seed_run_dir(
        tmp_path / "run_cand",
        run_id="run-cand-01",
        run_name="Contoso Readiness Run ",
        verdicts=[
            ("Q01", "PASS", "exact"),
            ("Q02", "PASS", "display_rounded"),
            ("Q03", "FAIL", "wrong_value"),
        ],
        xss_payload=xss,
    )

    report_path = render_html_report(run_dir)
    assert report_path == run_dir / "report.html"
    html_text = report_path.read_text(encoding="utf-8")

    assert html_text.lower().startswith("<!doctype html>")
    assert '<html lang="en">' in html_text
    assert "Wilson CI" in html_text
    assert "pass@1" in html_text
    assert "pass^1" in html_text
    assert "mcp-agent" in html_text
    assert "tool_call" in html_text
    assert "<details" in html_text
    assert "display_rounded" in html_text

    # Unescaped XSS tags must NEVER appear in rendered HTML
    assert "<script>" not in html_text
    assert "<img src=x" not in html_text
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html_text


def test_render_html_report_with_baseline_mcnemar_comparison(tmp_path: Path) -> None:
    base_dir = _seed_run_dir(
        tmp_path / "run_base",
        run_id="run-base-01",
        run_name="Baseline",
        verdicts=[
            ("Q01", "PASS", "exact"),
            ("Q02", "FAIL", "wrong_value"),
            ("Q03", "FAIL", "wrong_value"),
            ("Q04", "PASS", "exact"),
        ],
    )
    cand_dir = _seed_run_dir(
        tmp_path / "run_cand2",
        run_id="run-cand-02",
        run_name="Candidate",
        verdicts=[
            ("Q01", "PASS", "exact"),
            ("Q02", "PASS", "exact"),
            ("Q03", "PASS", "exact"),
            ("Q04", "FAIL", "wrong_value"),
        ],
    )
    out = tmp_path / "compared_report.html"
    returned = render_html_report(cand_dir, out, compare_dir=base_dir)
    assert returned == out
    doc = out.read_text(encoding="utf-8")
    assert "McNemar" in doc
    assert "run-base-01" in doc
    assert "run-cand-02" in doc
    assert "Q02, Q03" in doc
    assert "Q04" in doc


def test_export_otel_spans_deterministic_ids_and_otlp_post(tmp_path: Path) -> None:
    run_dir = _seed_run_dir(
        tmp_path / "run_otel",
        run_id="run-otel-01",
        run_name="OTel Export Test",
        verdicts=[("Q01", "PASS", "exact"), ("Q02", "FAIL", "wrong_value")],
    )

    posted: list[tuple[str, dict[str, Any]]] = []

    class _FakeResp:
        status_code = 200
        text = "{}"
        headers: dict[str, str] = {}

    class _FakeSess:
        def request(self, method: str, url: str, **kwargs: Any) -> _FakeResp:
            assert method == "POST"
            posted.append((url, kwargs["json"]))
            return _FakeResp()

    spans_path_1 = export_otel_spans(
        run_dir,
        endpoint="http://127.0.0.1:4318/v1/traces",
        session=_FakeSess(),
    )
    spans_1 = [json.loads(line) for line in spans_path_1.read_text(encoding="utf-8").splitlines() if line.strip()]

    # Re-exporting produces identical deterministic W3C trace_id & span_ids
    spans_path_2 = export_otel_spans(run_dir, tmp_path / "second.jsonl")
    spans_2 = [json.loads(line) for line in spans_path_2.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [s["span_id"] for s in spans_1] == [s["span_id"] for s in spans_2]
    assert [s["trace_id"] for s in spans_1] == [s["trace_id"] for s in spans_2]

    # 1 run root span + 2 ask spans + 2 child DAX spans = 5 spans
    assert len(spans_1) == 5
    root_span = spans_1[0]
    assert len(root_span["trace_id"]) == 32
    assert len(root_span["span_id"]) == 16
    assert root_span["parent_span_id"] == ""

    ask_spans = [s for s in spans_1 if s["name"] == "gen_ai.chat"]
    dax_spans = [s for s in spans_1 if s["name"] == "dax.query"]
    assert len(ask_spans) == 2
    assert len(dax_spans) == 2

    assert ask_spans[0]["parent_span_id"] == root_span["span_id"]
    assert ask_spans[0]["attributes"]["gen_ai.operation.name"] == "chat"
    assert ask_spans[0]["attributes"]["cfeval.question_id"] == "Q01"
    assert ask_spans[0]["attributes"]["cfeval.verdict"] == "PASS"
    assert ask_spans[0]["attributes"]["cfeval.routing_evidence"] == "tool_call"

    assert dax_spans[0]["parent_span_id"] == ask_spans[0]["span_id"]
    assert dax_spans[0]["attributes"]["db.system"] == "dax"
    assert "EVALUATE" in dax_spans[0]["attributes"]["db.statement"]

    assert len(posted) == 1
    assert posted[0][0] == "http://127.0.0.1:4318/v1/traces"
    assert len(posted[0][1]["resourceSpans"][0]["scopeSpans"][0]["spans"]) == 5
