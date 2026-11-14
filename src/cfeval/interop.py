"""Interoperability adapters: transcript import, Promptfoo YAML export, and Foundry JSONL export."""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from .chat import parse_json_block
from .foundry import foundry_row
from .golden import GoldenQuestion, load_golden
from .scorers import split_list
from .sinks import JsonlSink
from .trace import (
    FabricQuery,
    _normalise_row,
    compute_correlation_confidence,
    compute_routing_evidence,
    extract_artifact_ids,
)

_ESCAPED_PIPE_TOKEN = "\x00PIPE\x00"
_MD_LINK_RE = re.compile(r"^\[([^\]]+)\]\(([^)]+)\)$")
_MD_SEP_CELL_RE = re.compile(r"^:?-{2,}:?$")


def _first_present(raw: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw and raw[key] is not None:
            val = raw[key]
            if isinstance(val, str) and not val.strip():
                continue
            return val
    return None


def _parse_citation_item(item: Any) -> list[dict[str, Any]]:
    if item is None:
        return []
    if isinstance(item, Mapping):
        name = str(
            item.get("name") or item.get("providerDisplayName") or item.get("title") or item.get("artifact") or ""
        ).strip()
        url = str(item.get("url") or item.get("seeMoreWebUrl") or item.get("webUrl") or "").strip()
        kind = str(item.get("kind") or item.get("type") or item.get("attributionSource") or "").strip()
        art_id = str(item.get("id") or item.get("item_id") or item.get("artifactId") or "").strip()
        title = str(item.get("title") or name).strip()
        if not name and not url and not art_id:
            return []
        entry: dict[str, Any] = {
            "name": name or url or art_id,
            "url": url,
            "kind": kind,
        }
        if title:
            entry["title"] = title
        if art_id:
            entry["id"] = art_id
        return [entry]

    if isinstance(item, (list, tuple)):
        out: list[dict[str, Any]] = []
        for sub in item:
            out.extend(_parse_citation_item(sub))
        return out

    text = str(item).strip()
    if not text:
        return []

    if (text.startswith("[") and text.endswith("]")) or (text.startswith("{") and text.endswith("}")):
        try:
            parsed = json.loads(text)
            return _parse_citation_item(parsed)
        except json.JSONDecodeError:
            pass

    parts = [p.strip() for p in text.split(";") if p.strip()] if ";" in text else [text]
    entries: list[dict[str, Any]] = []
    for part in parts:
        md_match = _MD_LINK_RE.match(part)
        if md_match:
            entries.append(
                {
                    "name": md_match.group(1).strip(),
                    "url": md_match.group(2).strip(),
                    "kind": "",
                }
            )
        elif part.startswith(("http://", "https://")):
            entries.append({"name": part, "url": part, "kind": ""})
        else:
            entries.append({"name": part, "url": "", "kind": ""})
    return entries


def _parse_tool_calls(raw_tc: Any, raw_dax: str) -> tuple[str, list[dict[str, Any]]]:
    tool_calls: list[dict[str, Any]] = []
    parsed_tc = raw_tc
    if isinstance(raw_tc, str):
        stripped = raw_tc.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                parsed_tc = json.loads(stripped)
            except json.JSONDecodeError:
                if not raw_dax and stripped:
                    raw_dax = stripped
                parsed_tc = []
        elif stripped:
            if not raw_dax:
                raw_dax = stripped
            parsed_tc = []

    if isinstance(parsed_tc, Mapping):
        tool_calls = [dict(parsed_tc)]
    elif isinstance(parsed_tc, Sequence) and not isinstance(parsed_tc, (str, bytes)):
        for entry in parsed_tc:
            if isinstance(entry, Mapping):
                tool_calls.append(dict(entry))
            elif isinstance(entry, str) and entry.strip():
                tool_calls.append({"name": "execute_dax", "dax": entry.strip()})

    if not raw_dax:
        dax_chunks: list[str] = []
        for tc in tool_calls:
            raw_args = tc.get("arguments")
            args: Mapping[str, Any] = raw_args if isinstance(raw_args, Mapping) else {}
            candidate = (
                tc.get("dax")
                or tc.get("Dax")
                or tc.get("query")
                or tc.get("statement")
                or args.get("dax")
                or args.get("query")
                or ""
            )
            if str(candidate).strip():
                dax_chunks.append(str(candidate).strip())
        raw_dax = "\n".join(dax_chunks)

    return raw_dax, tool_calls


def _normalize_transcript_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    rec_id = str(_first_present(raw, "id", "question_id", "QuestionId", "case_id", "CaseId") or "").strip()
    question = str(_first_present(raw, "question", "Question", "prompt", "Prompt", "query") or "").strip()
    answer = str(
        _first_present(raw, "answer", "response", "actual_response", "output", "Answer", "answer_text", "Response")
        or ""
    ).strip()

    raw_cites = _first_present(raw, "citations", "attributions", "artifacts", "Citations", "Artifacts", "ArtifactNames")
    citations = _parse_citation_item(raw_cites)

    raw_model = _first_present(raw, "model", "queried_model", "ExpectedModel", "QueriedModels", "semantic_model")
    if isinstance(raw_model, Sequence) and not isinstance(raw_model, (str, bytes)):
        model = "; ".join(str(m).strip() for m in raw_model if str(m).strip())
    else:
        model = str(raw_model or "").strip()

    raw_dax = str(_first_present(raw, "dax", "Dax", "dax_query") or "").strip()
    raw_tc = _first_present(raw, "tool_calls", "ToolCalls")
    dax, tool_calls = _parse_tool_calls(raw_tc, raw_dax)

    lat_raw = _first_present(raw, "latency_ms", "LatencyMs")
    latency_ms: float | None = None
    if lat_raw is not None and str(lat_raw).strip() != "":
        try:
            latency_ms = float(lat_raw)
        except (TypeError, ValueError):
            latency_ms = None

    why = str(_first_present(raw, "why", "why_text", "Why") or "").strip()
    raw_why_json = _first_present(raw, "why_json", "WhyJson")
    why_json: dict[str, Any] | None = None
    if isinstance(raw_why_json, Mapping):
        why_json = dict(raw_why_json)
    elif isinstance(raw_why_json, str) and raw_why_json.strip():
        try:
            loaded_wj = json.loads(raw_why_json.strip())
            if isinstance(loaded_wj, Mapping):
                why_json = dict(loaded_wj)
        except json.JSONDecodeError:
            why_json = None
    if why_json is None and why:
        parsed_block = parse_json_block(why)
        if isinstance(parsed_block, Mapping):
            why_json = dict(parsed_block)

    normalized: dict[str, Any] = {
        "id": rec_id,
        "question_id": rec_id,
        "question": question,
        "answer": answer,
        "citations": citations,
        "model": model,
        "dax": dax,
        "tool_calls": tool_calls,
        "latency_ms": latency_ms,
        "why": why,
        "why_json": why_json,
    }
    for opt_src, opt_dst in (
        (("conversation_id", "ConversationId"), "conversation_id"),
        (("user", "TestUser"), "user"),
        (("started_utc", "AskStartUtc"), "started_utc"),
        (("ended_utc", "AskEndUtc"), "ended_utc"),
    ):
        val = _first_present(raw, *opt_src)
        if val is not None:
            normalized[opt_dst] = str(val).strip()
    return normalized


def _split_md_row(line: str) -> list[str]:
    protected = line.strip().replace(r"\|", _ESCAPED_PIPE_TOKEN)
    if protected.startswith("|"):
        protected = protected[1:]
    if protected.endswith("|"):
        protected = protected[:-1]
    return [cell.replace(_ESCAPED_PIPE_TOKEN, "|").strip() for cell in protected.split("|")]


def _is_md_separator(cells: Sequence[str]) -> bool:
    return bool(cells) and all(_MD_SEP_CELL_RE.match(c.strip()) is not None for c in cells)


def _parse_markdown_records(text: str) -> list[dict[str, str]]:
    lines = text.splitlines()
    rows: list[dict[str, str]] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if "|" in line and idx + 1 < len(lines) and "|" in lines[idx + 1]:
            headers = [h.strip("` ").strip() for h in _split_md_row(line)]
            sep_cells = _split_md_row(lines[idx + 1])
            if headers and len(headers) == len(sep_cells) and _is_md_separator(sep_cells):
                idx += 2
                while idx < len(lines):
                    data_line = lines[idx].strip()
                    if not data_line or "|" not in data_line:
                        break
                    cells = _split_md_row(data_line)
                    if _is_md_separator(cells):
                        idx += 1
                        continue
                    row_dict: dict[str, str] = {}
                    for col_idx, header in enumerate(headers):
                        if header:
                            row_dict[header] = cells[col_idx] if col_idx < len(cells) else ""
                    if any(v.strip() for v in row_dict.values()):
                        rows.append(row_dict)
                    idx += 1
                continue
        idx += 1
    return rows


def load_transcript_records(path: str | Path) -> list[dict[str, Any]]:
    """Load and normalize Q&A transcript records from .jsonl, .json, .csv, or .md."""
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"Transcript file not found: {src}")

    suffix = src.suffix.lower()
    raw_records: list[Mapping[str, Any]] = []

    if suffix in (".jsonl", ".ndjson"):
        for line_no, line in enumerate(src.read_text(encoding="utf-8-sig").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            parsed = json.loads(stripped)
            if not isinstance(parsed, Mapping):
                raise ValueError(f"{src}:{line_no}: expected JSON object per line")
            raw_records.append(parsed)
    elif suffix == ".json":
        payload = json.loads(src.read_text(encoding="utf-8-sig"))
        if isinstance(payload, list):
            items: list[Any] = payload
        elif isinstance(payload, Mapping):
            raw_items = (
                payload.get("records")
                if isinstance(payload.get("records"), list)
                else payload.get("items")
                if isinstance(payload.get("items"), list)
                else payload.get("results")
                if isinstance(payload.get("results"), list)
                else payload.get("transcript")
                if isinstance(payload.get("transcript"), list)
                else None
            )
            if raw_items is None:
                raise ValueError(f"{src}: JSON object must contain a 'records' array")
            items = list(raw_items)
        else:
            raise ValueError(f"{src}: expected JSON array or object with 'records'")
        for idx, item in enumerate(items):
            if not isinstance(item, Mapping):
                raise ValueError(f"{src}[{idx}]: expected JSON object")
            raw_records.append(item)
    elif suffix == ".csv":
        with src.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if any((v or "").strip() for v in row.values()):
                    raw_records.append(row)
    elif suffix in (".md", ".markdown"):
        raw_records.extend(_parse_markdown_records(src.read_text(encoding="utf-8-sig")))
    else:
        raise ValueError(f"Unsupported transcript file extension {suffix!r}; expected .jsonl, .json, .csv, or .md")

    return [_normalize_transcript_record(r) for r in raw_records]


def _promptfoo_assertions(q: GoldenQuestion) -> list[dict[str, Any]]:
    assertions: list[dict[str, Any]] = []
    ct = (q.case_type or "scalar").strip().lower()
    spec = q.expect if isinstance(q.expect, Mapping) else {}

    if ct in ("scalar", "numeric", "number") and q.expected_value is not None:
        exp_val = float(q.expected_value)
        tol = max(float(q.abs_tol or 0.0), abs(exp_val) * max(float(q.rel_tol or 0.005), float(q.display_tol or 0.01)))
        js_expr = (
            "(() => { "
            "const mult = {k: 1e3, thousand: 1e3, m: 1e6, million: 1e6, "
            "b: 1e9, billion: 1e9, t: 1e12, trillion: 1e12}; "
            "const re = /[-+]?(?:\\d{1,3}(?:,\\d{3})+|\\d+)(?:\\.\\d+)?"
            "(?:\\s*(k|m|b|t|thousand|million|billion|trillion))?/gi; "
            "let m; const vals = []; "
            "while ((m = re.exec(output)) !== null) { "
            "const base = parseFloat(m[0].replace(/,/g, '')); "
            "const scale = m[1] ? (mult[m[1].toLowerCase()] || 1) : 1; "
            "if (!Number.isNaN(base)) vals.push(base * scale); "
            "} "
            f"return vals.some(v => Math.abs(v - {exp_val!r}) <= {tol!r}); "
            "})()"
        )
        assertions.append({"type": "javascript", "metric": "value_match", "value": js_expr})
    elif ct in ("ranked_list", "set"):
        raw_spec_items = spec.get("items")
        spec_items: Sequence[Any] = (
            raw_spec_items
            if isinstance(raw_spec_items, Sequence) and not isinstance(raw_spec_items, (str, bytes))
            else []
        )
        for raw_item in spec_items:
            if isinstance(raw_item, Mapping):
                names = [str(raw_item.get("name") or "").strip()] + [
                    str(a).strip() for a in (raw_item.get("aliases") or []) if str(a).strip()
                ]
                names = [n for n in names if n]
                if len(names) > 1:
                    assertions.append({"type": "icontains-any", "metric": "list_item", "value": names})
                elif names:
                    assertions.append({"type": "icontains", "metric": "list_item", "value": names[0]})
            elif str(raw_item).strip():
                assertions.append({"type": "icontains", "metric": "list_item", "value": str(raw_item).strip()})
    elif ct in ("abstention", "negative", "refusal"):
        assertions.append(
            {
                "type": "javascript",
                "metric": "abstention",
                "value": (
                    "/(cannot|can't|do not have|don't have|not available|unable|no data|not found|insufficient)/i"
                    ".test(output)"
                ),
            }
        )
        for forbidden in spec.get("forbidden") or []:
            if str(forbidden).strip():
                assertions.append(
                    {"type": "not-icontains", "metric": "forbidden_content", "value": str(forbidden).strip()}
                )
    elif ct == "categorical":
        target = str(spec.get("value") or "").strip()
        aliases = [str(a).strip() for a in (spec.get("aliases") or []) if str(a).strip()]
        choices = [x for x in [target, *aliases] if x]
        if len(choices) > 1:
            assertions.append({"type": "icontains-any", "metric": "categorical", "value": choices})
        elif choices:
            assertions.append({"type": "icontains", "metric": "categorical", "value": choices[0]})
    elif ct == "direction":
        direction = str(spec.get("direction") or "").strip().lower()
        synonyms = {
            "up": ["up", "increase", "increased", "grew", "growth", "higher", "rose"],
            "down": ["down", "decrease", "decreased", "declined", "lower", "fell", "drop"],
            "flat": ["flat", "unchanged", "steady", "no change"],
        }
        if direction in synonyms:
            assertions.append({"type": "icontains-any", "metric": "direction", "value": synonyms[direction]})
    elif ct in ("facts", "text"):
        for fact in spec.get("facts") or spec.get("items") or []:
            if str(fact).strip():
                assertions.append({"type": "icontains", "metric": "fact", "value": str(fact).strip()})
    elif ct == "table":
        for row in spec.get("rows") or []:
            if isinstance(row, Mapping):
                for cell in row.values():
                    if cell is not None and str(cell).strip():
                        assertions.append({"type": "icontains", "metric": "table_cell", "value": str(cell).strip()})
                        break
    elif ct == "record":
        fields_map = spec.get("fields")
        if isinstance(fields_map, Mapping):
            for field_key, raw_fval in fields_map.items():
                if isinstance(raw_fval, (int, float)) and not isinstance(raw_fval, bool):
                    fval = float(raw_fval)
                    ftol = max(
                        float(q.abs_tol or 0.0),
                        abs(fval) * max(float(q.rel_tol or 0.005), float(q.display_tol or 0.01)),
                    )
                    rec_js = (
                        "(() => { "
                        "const mult = {k: 1e3, thousand: 1e3, m: 1e6, million: 1e6, "
                        "b: 1e9, billion: 1e9, t: 1e12, trillion: 1e12}; "
                        "const re = /[-+]?(?:\\d{1,3}(?:,\\d{3})+|\\d+)(?:\\.\\d+)?"
                        "(?:\\s*(k|m|b|t|thousand|million|billion|trillion))?/gi; "
                        "let m; const vals = []; "
                        "while ((m = re.exec(output)) !== null) { "
                        "const base = parseFloat(m[0].replace(/,/g, '')); "
                        "const scale = m[1] ? (mult[m[1].toLowerCase()] || 1) : 1; "
                        "if (!Number.isNaN(base)) vals.push(base * scale); "
                        "} "
                        f"return vals.some(v => Math.abs(v - {fval!r}) <= {ftol!r}); "
                        "})()"
                    )
                    assertions.append({"type": "javascript", "metric": f"record_{field_key}", "value": rec_js})
                elif raw_fval is not None and str(raw_fval).strip():
                    assertions.append(
                        {"type": "icontains", "metric": f"record_{field_key}", "value": str(raw_fval).strip()}
                    )

    if q.expected_artifact:
        art_names = [q.expected_artifact] + split_list(q.artifact_aliases)
        if len(art_names) > 1:
            assertions.append({"type": "icontains-any", "metric": "expected_artifact", "value": art_names})
        else:
            assertions.append({"type": "icontains", "metric": "expected_artifact", "value": q.expected_artifact})

    for decoy in split_list(q.decoys):
        assertions.append({"type": "not-icontains", "metric": "no_decoy", "value": decoy})

    if not assertions:
        assertions.append({"type": "javascript", "metric": "non_empty", "value": "output.trim().length > 0"})

    return assertions


def export_promptfoo(golden_path: str | Path, out_path: str | Path) -> Path:
    """Convert a cfeval golden set into a ready-to-run promptfooconfig.yaml."""
    src = Path(golden_path)
    dst = Path(out_path)
    questions = load_golden(src)

    tests: list[dict[str, Any]] = []
    for q in questions:
        test_vars: dict[str, Any] = {
            "question": q.question,
            "question_id": q.id,
            "case_type": q.case_type or "scalar",
        }
        if q.expected_value is not None:
            test_vars["expected_value"] = q.expected_value
        if q.unit:
            test_vars["unit"] = q.unit
        if q.expected_artifact:
            test_vars["expected_artifact"] = q.expected_artifact
        if q.model:
            test_vars["expected_model"] = q.model
        if q.persona:
            test_vars["persona"] = q.persona

        tests.append(
            {
                "description": f"{q.id}: {q.question}",
                "metadata": {
                    "id": q.id,
                    "category": q.category,
                    "case_type": q.case_type or "scalar",
                    "criticality": q.criticality,
                },
                "vars": test_vars,
                "assert": _promptfoo_assertions(q),
            }
        )

    config: dict[str, Any] = {
        "description": f"cfeval golden set export ({src.name})",
        "prompts": ["{{question}}"],
        "providers": [
            {
                "id": "echo",
                "config": {"label": "cfeval-golden-provider"},
            }
        ],
        "tests": tests,
    }
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return dst


def _question_from_eval_row(row: Mapping[str, Any]) -> GoldenQuestion:
    tags_raw = row.get("Tags")
    if isinstance(tags_raw, Sequence) and not isinstance(tags_raw, str):
        tags = [str(t) for t in tags_raw if str(t).strip()]
    elif isinstance(tags_raw, str) and tags_raw.strip():
        tags = split_list(tags_raw)
    else:
        tags = []

    gates_raw = row.get("Gates")
    if isinstance(gates_raw, Sequence) and not isinstance(gates_raw, str):
        gates = [str(g) for g in gates_raw if str(g).strip()]
    elif isinstance(gates_raw, str) and gates_raw.strip():
        gates = split_list(gates_raw)
    else:
        gates = []
    intent_raw = row.get("Intent")
    intent = dict(intent_raw) if isinstance(intent_raw, Mapping) else None
    exp_raw = row.get("Expect")
    expect = dict(exp_raw) if isinstance(exp_raw, Mapping) else None
    exp_val = row.get("ExpectedValue")
    return GoldenQuestion(
        id=str(row.get("QuestionId") or ""),
        question=str(row.get("Question") or ""),
        category=str(row.get("Category") or ""),
        expected_artifact=str(row.get("ExpectedArtifact") or ""),
        artifact_aliases=str(row.get("ArtifactAliases") or ""),
        expected_model=str(row.get("ExpectedModel") or ""),
        decoys=str(row.get("Decoys") or ""),
        expected_value=None if exp_val is None else float(exp_val),
        unit=str(row.get("Unit") or "number"),
        rel_tol=float(row["RelTol"]) if row.get("RelTol") is not None else 0.005,
        abs_tol=float(row["AbsTol"]) if row.get("AbsTol") is not None else 0.0,
        expected_answer=str(row.get("ExpectedAnswer") or ""),
        reference_dax=str(row.get("ReferenceDax") or ""),
        criticality=str(row.get("Criticality") or "standard"),
        case_type=str(row.get("CaseType") or "scalar"),
        expect=expect,
        expected_artifact_id=str(row.get("ExpectedArtifactId") or ""),
        persona=str(row.get("Persona") or ""),
        tags=tags,
        intent=intent,
        gates=gates,
    )


def export_foundry_jsonl(run_dir: str | Path, out_path: str | Path) -> Path:
    """Export a completed cfeval run directory into Foundry Evaluation dataset JSONL rows."""
    folder = Path(run_dir)
    if not folder.exists():
        raise FileNotFoundError(f"Run directory not found: {folder}")

    sink = JsonlSink(folder)
    runs = sink.read("EvalRun")
    q_rows = sink.read("EvalQuestion")
    asks = sink.read("EvalAsk")
    iq_rows = sink.read("FabricIqQuery")
    res_rows = sink.read("EvalResult")

    run_meta = runs[-1] if runs else {}
    trace_enabled = bool(run_meta.get("TraceEnabled"))

    qmap: dict[str, GoldenQuestion] = {}
    for qr in q_rows:
        gq = _question_from_eval_row(qr)
        if gq.id:
            qmap[gq.id] = gq

    queries_by_ask: dict[str, list[FabricQuery]] = {}
    for r in iq_rows:
        aid = str(r.get("AskId") or "")
        if aid:
            queries_by_ask.setdefault(aid, []).append(_normalise_row(r))

    result_by_ask: dict[str, Mapping[str, Any]] = {}
    for rr in res_rows:
        aid = str(rr.get("AskId") or "")
        if aid:
            result_by_ask[aid] = rr

    dst = Path(out_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for ask in asks:
        ask_id = str(ask.get("AskId") or "")
        qid = str(ask.get("QuestionId") or "")
        q = qmap.get(qid) or GoldenQuestion(id=qid, question=str(ask.get("Question") or ""))
        artifacts = ask.get("Artifacts") if isinstance(ask.get("Artifacts"), list) else []
        found_queries = queries_by_ask.get(ask_id, [])
        res_meta = result_by_ask.get(ask_id, {})

        status = str(res_meta.get("TraceStatus") or "")
        if not status:
            if found_queries:
                status = "observed"
            elif trace_enabled:
                status = "none"
            else:
                status = "disabled"

        models = sorted({fq.item_name for fq in found_queries if fq.item_name})
        if not models and isinstance(res_meta.get("QueriedModels"), list):
            models = sorted({str(m) for m in res_meta["QueriedModels"] if m})

        routing_ev = str(res_meta.get("RoutingEvidence") or "")
        if not routing_ev:
            routing_ev = compute_routing_evidence(status, found_queries, artifacts)

        corr_conf = str(res_meta.get("CorrelationConfidence") or "")
        if not corr_conf:
            art_ids = extract_artifact_ids(artifacts)
            if q.expected_artifact_id:
                art_ids.add(q.expected_artifact_id.lower())
            corr_conf = compute_correlation_confidence(
                status,
                found_queries,
                artifact_ids=art_ids,
                user_upn=str(ask.get("TestUser") or ""),
            )

        trace: dict[str, Any] = {
            "status": status,
            "queries": found_queries,
            "models": models,
            "routing_evidence": routing_ev,
            "correlation_confidence": corr_conf,
        }
        row = foundry_row(q, ask, artifacts, trace)
        lines.append(json.dumps(row, ensure_ascii=False))

    dst.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return dst


def export_m365_copilot_eval(golden_path: str | Path, out_path: str | Path) -> Path:
    """Export a golden set into a cleanroom Microsoft 365 Copilot Evaluations CLI v2 JSON document."""
    questions = load_golden(Path(golden_path))
    doc: dict[str, Any] = {
        "schemaVersion": "2.0",
        "default_evaluators": ["Relevance", "Groundedness", "Citations"],
        "items": [
            {
                "id": q.id,
                "prompt": q.question,
                "expected_response": q.expected_answer
                or (str(q.expected_value) if q.expected_value is not None else ""),
                "metadata": {
                    "category": q.category,
                    "expected_artifact": q.expected_artifact,
                    "expected_model": q.expected_model,
                    "case_type": q.case_type,
                },
            }
            for q in questions
        ],
    }
    dst = Path(out_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dst


def load_m365_copilot_eval_results(path: str | Path) -> list[dict[str, Any]]:
    """Load saved results from @microsoft/m365-copilot-eval into normalized transcript records."""
    return load_transcript_records(path)
