"""OpenTelemetry GenAI & DAX span exporter for completed cfeval runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from .clock import iso, parse_iso
from .config import request_with_retry
from .sinks import JsonlSink


def _deterministic_hex(seed: str, length: int) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:length]
    if int(digest, 16) == 0:
        digest = "1" + digest[1:]
    return digest


def _to_unix_nano(ts: Any) -> int:
    if isinstance(ts, datetime):
        dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    elif ts:
        try:
            dt = parse_iso(str(ts))
        except Exception:
            dt = datetime(1970, 1, 1, tzinfo=timezone.utc)
    else:
        dt = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


def _otlp_attr_value(val: Any) -> dict[str, Any]:
    if isinstance(val, bool):
        return {"boolValue": val}
    if isinstance(val, int):
        return {"intValue": str(val)}
    if isinstance(val, float):
        return {"doubleValue": val}
    return {"stringValue": str(val)}


def _to_otlp_payload(spans: list[dict[str, Any]], service_name: str = "cfeval") -> dict[str, Any]:
    otlp_spans: list[dict[str, Any]] = []
    for sp in spans:
        attrs = [{"key": k, "value": _otlp_attr_value(v)} for k, v in (sp.get("attributes") or {}).items()]
        otlp_span: dict[str, Any] = {
            "traceId": sp["trace_id"],
            "spanId": sp["span_id"],
            "name": sp["name"],
            "kind": 3 if sp.get("kind") == "CLIENT" else 1,
            "startTimeUnixNano": str(sp["start_time_unix_nano"]),
            "endTimeUnixNano": str(sp["end_time_unix_nano"]),
            "attributes": attrs,
            "status": {"code": 2 if sp.get("status") == "ERROR" else 1},
        }
        if sp.get("parent_span_id"):
            otlp_span["parentSpanId"] = sp["parent_span_id"]
        otlp_spans.append(otlp_span)

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": service_name}},
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "cfeval.otel", "version": "0.1.0"},
                        "spans": otlp_spans,
                    }
                ],
            }
        ]
    }


def export_otel_spans(
    run_dir: str | Path,
    out_path: str | Path | None = None,
    *,
    endpoint: str = "",
    session: Any = None,
    headers: Mapping[str, str] | None = None,
) -> Path:
    """Export deterministic W3C OpenTelemetry JSONL spans (and optional OTLP/HTTP POST) for `run_dir`."""
    folder = Path(run_dir)
    if not folder.exists():
        raise FileNotFoundError(f"Run directory not found: {folder}")

    sink = JsonlSink(folder)
    runs = sink.read("EvalRun")
    asks = sink.read("EvalAsk")
    results = sink.read("EvalResult")
    queries = sink.read("FabricIqQuery")

    run_meta = dict(runs[-1]) if runs else {}
    run_id = str(run_meta.get("RunId") or folder.name)
    target = str(run_meta.get("Target") or "copilot-chat")
    surface = str(run_meta.get("Surface") or target)
    gen_ai_system = "m365_copilot" if target == "copilot-chat" else target

    trace_id = _deterministic_hex(f"cfeval:trace:{run_id}", 32)
    run_span_id = _deterministic_hex(f"cfeval:run:{run_id}", 16)

    result_by_ask: dict[str, dict[str, Any]] = {}
    for res in results:
        aid = str(res.get("AskId") or "")
        if aid and (aid not in result_by_ask or res.get("Backend") == "fabric-native"):
            result_by_ask[aid] = dict(res)

    queries_by_ask: dict[str, list[dict[str, Any]]] = {}
    for qr in queries:
        aid = str(qr.get("AskId") or "")
        if aid:
            queries_by_ask.setdefault(aid, []).append(dict(qr))

    run_start_raw = run_meta.get("StartedUtc") or (asks[0].get("AskStartUtc") if asks else None)
    run_end_raw = (
        run_meta.get("EndedUtc")
        or run_meta.get("CompletedUtc")
        or (asks[-1].get("AskEndUtc") if asks else run_start_raw)
    )
    run_start_dt = parse_iso(run_start_raw) if run_start_raw else datetime(1970, 1, 1, tzinfo=timezone.utc)
    run_end_dt = parse_iso(run_end_raw) if run_end_raw else run_start_dt

    spans: list[dict[str, Any]] = [
        {
            "trace_id": trace_id,
            "span_id": run_span_id,
            "parent_span_id": "",
            "name": "cfeval.run",
            "kind": "INTERNAL",
            "start_time": iso(run_start_dt) or "",
            "end_time": iso(max(run_end_dt, run_start_dt)) or "",
            "start_time_unix_nano": _to_unix_nano(run_start_dt),
            "end_time_unix_nano": _to_unix_nano(max(run_end_dt, run_start_dt)),
            "status": "ERROR" if str(run_meta.get("Status") or "").lower() == "error" else "OK",
            "attributes": {
                "gen_ai.system": gen_ai_system,
                "cfeval.run_id": run_id,
                "cfeval.target": target,
                "cfeval.surface": surface,
            },
        }
    ]

    for ask in asks:
        ask_id = str(ask.get("AskId") or "")
        qid = str(ask.get("QuestionId") or "")
        res_row = result_by_ask.get(ask_id, {})

        ask_span_id = _deterministic_hex(f"cfeval:ask:{run_id}:{ask_id}", 16)
        a_start = parse_iso(ask.get("AskStartUtc")) if ask.get("AskStartUtc") else run_start_dt
        a_end = parse_iso(ask.get("AskEndUtc")) if ask.get("AskEndUtc") else a_start

        verdict_val = str(res_row.get("Verdict") or ("ERROR" if ask.get("Status") != "ok" else "UNSCORED"))
        match_kind = str(res_row.get("MatchKind") or "")
        routing_ev = str(res_row.get("RoutingEvidence") or "")
        conv_id = str(ask.get("ConversationId") or ask_id)

        spans.append(
            {
                "trace_id": trace_id,
                "span_id": ask_span_id,
                "parent_span_id": run_span_id,
                "name": "gen_ai.chat",
                "kind": "CLIENT",
                "start_time": iso(a_start) or "",
                "end_time": iso(max(a_end, a_start)) or "",
                "start_time_unix_nano": _to_unix_nano(a_start),
                "end_time_unix_nano": _to_unix_nano(max(a_end, a_start)),
                "status": "ERROR" if verdict_val in ("FAIL", "ERROR") else "OK",
                "attributes": {
                    "gen_ai.system": gen_ai_system,
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.id": conv_id,
                    "cfeval.run_id": run_id,
                    "cfeval.ask_id": ask_id,
                    "cfeval.question_id": qid,
                    "cfeval.verdict": verdict_val,
                    "cfeval.match_kind": match_kind,
                    "cfeval.routing_evidence": routing_ev,
                    "cfeval.target": target,
                },
            }
        )

        for q_idx, qr in enumerate(queries_by_ask.get(ask_id, [])):
            row_ident = str(qr.get("RowId") or qr.get("CorrelationId") or q_idx)
            q_span_id = _deterministic_hex(f"cfeval:query:{run_id}:{ask_id}:{q_idx}:{row_ident}", 16)
            q_end = parse_iso(qr.get("QueryTimeUtc")) if qr.get("QueryTimeUtc") else a_end
            dur_ms = float(qr.get("DurationMs") or 0.0)
            q_start = q_end - timedelta(milliseconds=max(0.0, dur_ms))

            spans.append(
                {
                    "trace_id": trace_id,
                    "span_id": q_span_id,
                    "parent_span_id": ask_span_id,
                    "name": "dax.query",
                    "kind": "CLIENT",
                    "start_time": iso(q_start) or "",
                    "end_time": iso(max(q_end, q_start)) or "",
                    "start_time_unix_nano": _to_unix_nano(q_start),
                    "end_time_unix_nano": _to_unix_nano(max(q_end, q_start)),
                    "status": "OK",
                    "attributes": {
                        "db.system": "dax",
                        "db.statement": str(qr.get("Dax") or ""),
                        "db.name": str(qr.get("ItemName") or ""),
                        "cfeval.run_id": run_id,
                        "cfeval.ask_id": ask_id,
                        "cfeval.question_id": qid,
                    },
                }
            )

    dst = Path(out_path) if out_path is not None else folder / "otel_spans.jsonl"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        "\n".join(json.dumps(sp, ensure_ascii=False) for sp in spans) + ("\n" if spans else ""),
        encoding="utf-8",
    )

    if endpoint.strip():
        sess = session if session is not None else requests.Session()
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        otlp_body = _to_otlp_payload(spans)
        request_with_retry(sess, "POST", endpoint.strip(), headers=req_headers, json=otlp_body)

    return dst
