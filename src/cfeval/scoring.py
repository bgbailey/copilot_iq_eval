"""Turn an ask, its artifacts, and its engine evidence into scored rows and v2 observations."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from typing import Any

from .artifacts import powerbi_artifacts
from .judge import judge_prompt_hash
from .scorers import (
    FAIL,
    INCONCLUSIVE,
    PASS,
    _select_unit_compatible,
    artifact_check,
    citation_artifacts,
    extract_answer_value,
    extract_numbers,
    load_gate_policy,
    model_check,
    score_artifact,
    score_model,
    score_value,
    value_check,
    verdict,
    why_check,
)

GATE_CHECKS = ("value", "artifact", "model")
EVALUATOR_NAMES = {
    "value": "cfeval.score_value",
    "artifact": "cfeval.score_artifact",
    "model": "cfeval.score_model",
    "judge_answer": "judge.answer_correctness",
    "why": "judge.why_consistency",
}
VALID_EXTRACT_MODES = ("cascade", "first", "explicit", "llm_extract", "closest")


def _q_get(q: Any, name: str, default: Any = None) -> Any:
    if isinstance(q, Mapping):
        return q.get(name, default)
    return getattr(q, name, default)


def _q_expected(q: Any) -> Any:
    val = _q_get(q, "expected_value")
    if val is None:
        val = _q_get(q, "expected")
    if val is None:
        exp = _q_get(q, "expect")
        if isinstance(exp, Mapping):
            val = exp.get("value")
    return val


def _strip_num_punct(s: str) -> str:
    return re.sub(r"[\s,\u00a0\u202f]", "", s)


def _verify_explicit_candidate(
    answer_text: str,
    why_json: Mapping[str, Any] | None,
    unit: str,
    currency: str,
) -> dict[str, Any] | None:
    """Verify `why_json['answer']` / `answer_span` appears literally in `answer_text` and parses cleanly."""
    if not why_json:
        return None
    raw_ans = why_json.get("answer")
    span_hint = str(why_json.get("answer_span") or "").strip()

    raw_str = ""
    raw_num_val: float | None = None
    if isinstance(raw_ans, Mapping):
        span_hint = span_hint or str(raw_ans.get("span") or "").strip()
        val_field = raw_ans.get("value")
        if isinstance(val_field, (int, float)) and not isinstance(val_field, bool):
            raw_num_val = float(val_field)
            raw_str = str(val_field)
        elif val_field is not None:
            raw_str = str(val_field).strip()
    elif isinstance(raw_ans, (int, float)) and not isinstance(raw_ans, bool):
        raw_num_val = float(raw_ans)
        raw_str = str(raw_ans)
    elif raw_ans is not None:
        raw_str = str(raw_ans).strip()

    if not span_hint and not raw_str:
        return None

    all_cands = [c for c in extract_numbers(answer_text) if not c.get("_in_range", False)]
    compat = _select_unit_compatible(all_cands, unit, currency)
    if not compat:
        return None

    # 1. Exact literal span match if span_hint or raw_str is a direct substring of answer_text
    for probe in [span_hint, raw_str] if span_hint else [raw_str]:
        if not probe:
            continue
        if probe in answer_text:
            parsed_probe = extract_answer_value(probe, expected_unit=unit, expected_currency=currency)
            if parsed_probe["status"] == "ok" and parsed_probe["value"] is not None:
                p_val = float(parsed_probe["value"])
                if raw_num_val is not None and abs(p_val - raw_num_val) > max(1e-6, abs(raw_num_val) * 1e-6):
                    continue
                for c in compat:
                    if abs(float(c["value"]) - p_val) <= max(1e-6, abs(p_val) * 1e-6):
                        return {
                            "status": "ok",
                            "value": float(c["value"]),
                            "unit": c["unit"],
                            "currency": c["currency"],
                            "span": c["span"],
                            "scale": c["scale"],
                            "sig_figs": c["sig_figs"],
                            "decimals": c["decimals"],
                            "ulp": c["ulp"],
                            "has_scale_word": c["has_scale_word"],
                            "candidates": compat,
                        }

    # 2. Comma/whitespace-insensitive literal match against extracted candidate spans in answer_text
    norm_answer = _strip_num_punct(answer_text)
    for probe in [span_hint, raw_str] if span_hint else [raw_str]:
        if not probe:
            continue
        norm_probe = _strip_num_punct(probe)
        if not norm_probe or norm_probe not in norm_answer:
            continue
        probe_cands = extract_numbers(probe)
        if len(probe_cands) != 1:
            continue
        p_val = float(probe_cands[0]["value"])
        for c in compat:
            norm_c_span = _strip_num_punct(str(c["span"]))
            if (norm_probe in norm_c_span or norm_c_span in norm_probe) and abs(float(c["value"]) - p_val) <= max(
                1e-6, abs(p_val) * 1e-6
            ):
                return {
                    "status": "ok",
                    "value": float(c["value"]),
                    "unit": c["unit"],
                    "currency": c["currency"],
                    "span": str(c["span"]),
                    "scale": c["scale"],
                    "sig_figs": c["sig_figs"],
                    "decimals": c["decimals"],
                    "ulp": c["ulp"],
                    "has_scale_word": c["has_scale_word"],
                    "candidates": compat,
                }
    return None


def _verify_llm_candidate(
    answer_text: str,
    llm_res: Mapping[str, Any] | None,
    unit: str,
    currency: str,
) -> dict[str, Any] | None:
    """Verify `judge.extract_value` returned a literal substring of `answer_text` whose parse agrees."""
    if not isinstance(llm_res, Mapping):
        return None
    span = str(llm_res.get("span") or "").strip()
    if not span or span not in answer_text:
        return None

    span_cands = [c for c in extract_numbers(span) if not c.get("_in_range", False)]
    compat = _select_unit_compatible(span_cands, unit, currency)
    if len(compat) != 1:
        return None
    c = compat[0]
    det_val = float(c["value"])

    if "value" in llm_res and llm_res["value"] is not None:
        if isinstance(llm_res["value"], bool):
            return None
        try:
            rep_val = float(llm_res["value"])
        except (TypeError, ValueError):
            return None
        if abs(det_val - rep_val) > max(1e-6, abs(rep_val) * 1e-6):
            return None

    return {
        "status": "ok",
        "value": det_val,
        "unit": c["unit"],
        "currency": c["currency"],
        "span": span,
        "scale": c["scale"],
        "sig_figs": c["sig_figs"],
        "decimals": c["decimals"],
        "ulp": c["ulp"],
        "has_scale_word": c["has_scale_word"],
        "candidates": compat,
    }


def score_observation(
    question: Any,
    obs: Mapping[str, Any],
    judge: Any = None,
    *,
    gate_policy: Mapping[str, Any] | None = None,
    extract_mode: str = "cascade",
    trace_enabled: bool | None = None,
    surface: str = "copilot-chat",
    judge_gates_verdict: bool = False,
) -> dict[str, Any]:
    """Score a normalized observation with cascade extraction, span verification, and gate policy."""
    if extract_mode not in VALID_EXTRACT_MODES:
        raise ValueError(f"Unsupported extract_mode {extract_mode!r}; expected one of {VALID_EXTRACT_MODES}")

    answer_text = str(
        obs.get("answer_text")
        if "answer_text" in obs
        else obs.get("answer")
        if "answer" in obs
        else obs.get("Answer") or ""
    )
    if "ask_ok" in obs:
        ask_ok = bool(obs["ask_ok"])
    elif "ok" in obs:
        ask_ok = bool(obs["ok"])
    elif "status" in obs:
        ask_ok = str(obs["status"]).lower() == "ok"
    elif "Status" in obs:
        ask_ok = str(obs["Status"]).lower() == "ok"
    elif obs.get("error") or obs.get("Error"):
        ask_ok = False
    else:
        ask_ok = True

    attributions = obs.get("attributions") or []
    artifacts = obs.get("artifacts") if "artifacts" in obs else (obs.get("Artifacts") or [])
    why_text = str(
        obs.get("why_text") if "why_text" in obs else obs.get("why") if "why" in obs else obs.get("Why") or ""
    )
    why_json_raw = obs.get("why_json") if "why_json" in obs else obs.get("WhyJson")
    if isinstance(why_json_raw, str) and why_json_raw.strip():
        try:
            parsed_wj = json.loads(why_json_raw)
            why_json: Any = parsed_wj if isinstance(parsed_wj, Mapping) else None
        except ValueError:
            why_json = None
    else:
        why_json = why_json_raw

    raw_trace = obs.get("trace") or obs.get("engine_evidence") or obs.get("trace_info")
    if raw_trace is None and obs.get("tool_calls"):
        trace_info: dict[str, Any] = {
            "status": "observed",
            "routing_evidence": str(obs.get("routing_evidence") or "tool_call"),
            "correlation_confidence": "high",
            "queries": list(obs.get("tool_calls") or []),
        }
    elif isinstance(raw_trace, Mapping):
        trace_info = dict(raw_trace)
    elif raw_trace is not None:
        trace_info = {
            "status": getattr(raw_trace, "status", ""),
            "queries": getattr(raw_trace, "queries", []),
            "correlation_confidence": getattr(raw_trace, "correlation_confidence", "none"),
            "routing_evidence": getattr(raw_trace, "routing_evidence", ""),
        }
    else:
        trace_info = {}

    q_text = str(_q_get(question, "question") or "")
    case_type = str(_q_get(question, "case_type") or "scalar").strip().lower()
    expect = _q_get(question, "expect")
    expected_val = _q_expected(question)
    unit = str(_q_get(question, "unit") or "")
    currency = str(_q_get(question, "currency") or _q_get(question, "expected_currency") or "")
    rel_tol = float(_q_get(question, "rel_tol", 0.005) or 0.005)
    abs_tol = _q_get(question, "abs_tol")
    display_tol = float(_q_get(question, "display_tol", 0.01) if _q_get(question, "display_tol") is not None else 0.01)

    expected_artifact = str(_q_get(question, "expected_artifact") or "")
    expected_artifact_id = str(_q_get(question, "expected_artifact_id") or "")
    artifact_aliases = _q_get(question, "artifact_aliases")
    expected_model = str(_q_get(question, "model") or _q_get(question, "expected_model") or expected_artifact)
    decoys = _q_get(question, "decoys")
    case_gates = _q_get(question, "gates")

    extraction_method = "none"
    validated_span = ""

    if case_type in ("scalar", "numeric", "number"):
        first_ext = extract_answer_value(answer_text, expected_unit=unit, expected_currency=currency)
        if first_ext["status"] == "range":
            vc = value_check(
                answer_text,
                expected_val,
                expected_unit=unit,
                rel_tol=rel_tol,
                abs_tol=abs_tol,
                display_tol=display_tol,
                extracted_override=first_ext,
                expected_currency=currency,
            )
            extraction_method = "first"
            validated_span = str(first_ext.get("span") or "")
        elif first_ext["status"] == "ok" and extract_mode in ("cascade", "first"):
            vc = value_check(
                answer_text,
                expected_val,
                expected_unit=unit,
                rel_tol=rel_tol,
                abs_tol=abs_tol,
                display_tol=display_tol,
                extracted_override=first_ext,
                expected_currency=currency,
            )
            extraction_method = "first"
            validated_span = str(first_ext.get("span") or "")
        else:
            resolved_cand: dict[str, Any] | None = None
            # Step 2: explicit structured follow-up answer verified against literal answer_text
            if extract_mode == "explicit" or (
                extract_mode == "cascade" and first_ext["status"] in ("ambiguous", "none")
            ):
                wj_map = why_json if isinstance(why_json, Mapping) else None
                exp_cand = _verify_explicit_candidate(answer_text, wj_map, unit, currency)
                if exp_cand is not None:
                    resolved_cand = exp_cand
                    extraction_method = "explicit"
                    validated_span = str(exp_cand["span"])

            # Step 3: blind LLM span extraction (never receives expected value)
            if (
                resolved_cand is None
                and (
                    extract_mode == "llm_extract"
                    or (extract_mode == "cascade" and first_ext["status"] in ("ambiguous", "none"))
                )
                and judge is not None
                and hasattr(judge, "extract_value")
            ):
                llm_raw = judge.extract_value(q_text, answer_text)
                llm_cand = _verify_llm_candidate(answer_text, llm_raw, unit, currency)
                if llm_cand is not None:
                    resolved_cand = llm_cand
                    extraction_method = "llm_extract"
                    validated_span = str(llm_cand["span"])

            # Step 4: diagnostic closest mode or honest ambiguous/none fallback
            if resolved_cand is None and extract_mode == "closest":
                all_cands = [c for c in extract_numbers(answer_text) if not c.get("_in_range", False)]
                compat = _select_unit_compatible(all_cands, unit, currency)
                if compat and expected_val is not None:
                    target_f = float(expected_val)
                    best = min(compat, key=lambda c: abs(float(c["value"]) - target_f))
                    resolved_cand = {
                        "status": "ok",
                        "value": float(best["value"]),
                        "unit": best["unit"],
                        "currency": best["currency"],
                        "span": best["span"],
                        "scale": best["scale"],
                        "sig_figs": best["sig_figs"],
                        "decimals": best["decimals"],
                        "ulp": best["ulp"],
                        "has_scale_word": best["has_scale_word"],
                        "candidates": compat,
                    }
                    extraction_method = "closest"
                    validated_span = str(best["span"])

            if resolved_cand is not None:
                vc = value_check(
                    answer_text,
                    expected_val,
                    expected_unit=unit,
                    rel_tol=rel_tol,
                    abs_tol=abs_tol,
                    display_tol=display_tol,
                    extracted_override=resolved_cand,
                    expected_currency=currency,
                )
            elif first_ext["status"] == "ambiguous":
                vc = value_check(
                    answer_text,
                    expected_val,
                    expected_unit=unit,
                    rel_tol=rel_tol,
                    abs_tol=abs_tol,
                    display_tol=display_tol,
                    extracted_override=first_ext,
                    expected_currency=currency,
                )
                extraction_method = "first"
                validated_span = ""
            else:
                vc = value_check(
                    answer_text,
                    expected_val,
                    expected_unit=unit,
                    rel_tol=rel_tol,
                    abs_tol=abs_tol,
                    display_tol=display_tol,
                    extracted_override={"status": "none", "value": None, "candidates": []},
                    expected_currency=currency,
                )
                extraction_method = "none"
                validated_span = ""
    else:
        vc = value_check(
            answer_text,
            expected_val,
            expected_unit=unit,
            rel_tol=rel_tol,
            abs_tol=abs_tol,
            display_tol=display_tol,
            case_type=case_type,
            expect=expect if isinstance(expect, dict) else None,
            expected_currency=currency,
        )
        extraction_method = case_type
        validated_span = str(vc.get("validated_span") or "")

    vc["extraction_method"] = extraction_method

    ac = artifact_check(
        attributions,
        artifacts,
        expected_name=expected_artifact,
        expected_id=expected_artifact_id,
        aliases=artifact_aliases,
        decoys=decoys,
    )
    mc = model_check(trace_info, expected_model=expected_model, decoys=decoys)
    wc = why_check(
        why_text,
        why_json if isinstance(why_json, Mapping) else None,
        expected_artifact=expected_artifact,
        expected_model=expected_model,
        answer_value=vc.get("extracted") if isinstance(vc.get("extracted"), (int, float)) else None,
    )

    checks: dict[str, dict[str, Any]] = {
        "value": vc,
        "artifact": ac,
        "model": mc,
        "why": wc,
    }

    if judge is not None and ask_ok and hasattr(judge, "judge_answer"):
        j_res = judge.judge_answer(question, answer_text)
        if j_res is not None:
            checks["judge_answer"] = _with_outcome(j_res) or j_res

    trace_status = str(trace_info.get("status") or "disabled").lower()
    trace_routing = str(trace_info.get("routing_evidence") or obs.get("routing_evidence") or "")

    if gate_policy is not None:
        resolved_policy = dict(gate_policy)
        if judge_gates_verdict and "judge_answer" not in resolved_policy.get("gates", ()):
            resolved_policy["gates"] = tuple(list(resolved_policy.get("gates", ())) + ["judge_answer"])
    else:
        eff_surface = "tool_call" if trace_routing == "tool_call" else surface
        eff_trace_on = (
            trace_enabled
            if trace_enabled is not None
            else (trace_status not in ("disabled", "") and trace_routing != "tool_call")
        )
        resolved_policy = load_gate_policy(
            "auto",
            trace_enabled=eff_trace_on,
            surface=eff_surface,
            case_gates=case_gates,
            judge_gates_verdict=judge_gates_verdict,
        )

    active_gates = tuple(resolved_policy.get("gates") or GATE_CHECKS)
    inc_on_missing = bool(resolved_policy.get("incomplete_on_missing_trace", False))
    final_verdict = verdict(
        checks,
        ask_ok=ask_ok,
        trace_status=trace_status,
        gates=active_gates,
        incomplete_on_missing_trace=inc_on_missing,
    )

    effective_routing = str(
        mc.get("routing_evidence") or trace_routing or resolved_policy.get("routing_evidence") or "citations-only"
    )
    if (
        "model" not in active_gates
        and effective_routing == "engine+citations"
        and trace_status not in ("observed", "complete")
    ):
        effective_routing = "citations-only"

    j_hash = str(getattr(judge, "prompt_hash", None) or (judge_prompt_hash() if judge is not None else ""))
    j_cal = str(getattr(judge, "calibration_id", "") if judge is not None else "")

    return {
        "verdict": final_verdict,
        "passed": 1 if final_verdict == "PASS" else 0,
        "checks": checks,
        "extracted": vc.get("extracted"),
        "extracted_unit": vc.get("unit", ""),
        "rel_error": vc.get("rel_error"),
        "match_kind": vc.get("match_kind", ""),
        "extraction_method": extraction_method,
        "validated_span": validated_span,
        "routing_evidence": effective_routing,
        "correlation_confidence": str(mc.get("correlation_confidence") or "none"),
        "gate_policy_hash": str(resolved_policy.get("gate_policy_hash") or ""),
        "gate_profile": str(resolved_policy.get("profile") or ""),
        "gates": list(active_gates),
        "judge_prompt_hash": j_hash,
        "judge_calibration_id": j_cal,
    }


def trace_stats(queries: Sequence[Any], ask_start: Any) -> dict[str, Any]:
    if not queries:
        return {"count": 0, "total": 0.0, "max": 0.0, "first_offset": None}
    durations = [float(getattr(q, "duration_ms", None) or 0) for q in queries]
    first = min(q.query_time for q in queries)
    return {
        "count": len(queries),
        "total": round(sum(durations), 1),
        "max": round(max(durations), 1),
        "first_offset": round((first - ask_start).total_seconds() * 1000.0, 1),
    }


def deterministic_checks(
    q: Any,
    ask: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    trace: Mapping[str, Any],
    *,
    judge: Any = None,
    extract_mode: str = "cascade",
) -> dict[str, dict[str, Any]]:
    if ask["Status"] != "ok":
        return {}
    case_type = str(_q_get(q, "case_type") or "scalar").strip().lower()
    expect = _q_get(q, "expect")
    display_tol = float(_q_get(q, "display_tol", 0.01) if _q_get(q, "display_tol") is not None else 0.01)
    currency = str(_q_get(q, "currency") or _q_get(q, "expected_currency") or "")
    expected_art_id = str(_q_get(q, "expected_artifact_id") or "")
    answer_text = str(ask.get("Answer") or "")

    why_json_raw = ask.get("WhyJson")
    wj_map: Mapping[str, Any] | None = None
    if isinstance(why_json_raw, Mapping):
        wj_map = why_json_raw
    elif isinstance(why_json_raw, str) and why_json_raw.strip():
        try:
            parsed_wj = json.loads(why_json_raw)
            if isinstance(parsed_wj, Mapping):
                wj_map = parsed_wj
        except ValueError:
            wj_map = None

    if case_type in ("scalar", "numeric", "number"):
        first_ext = extract_answer_value(answer_text, expected_unit=q.unit, expected_currency=currency)
        if first_ext["status"] == "range" or (first_ext["status"] == "ok" and extract_mode in ("cascade", "first")):
            vc = value_check(
                answer_text,
                q.expected_value,
                expected_unit=q.unit,
                rel_tol=q.rel_tol,
                abs_tol=q.abs_tol,
                display_tol=display_tol,
                extracted_override=first_ext,
                expected_currency=currency,
            )
            vc["extraction_method"] = "first"
        else:
            resolved_cand: dict[str, Any] | None = None
            extraction_method = "none"
            if extract_mode == "explicit" or (
                extract_mode == "cascade" and first_ext["status"] in ("ambiguous", "none")
            ):
                exp_cand = _verify_explicit_candidate(answer_text, wj_map, q.unit, currency)
                if exp_cand is not None:
                    resolved_cand = exp_cand
                    extraction_method = "explicit"
            if (
                resolved_cand is None
                and (
                    extract_mode == "llm_extract"
                    or (extract_mode == "cascade" and first_ext["status"] in ("ambiguous", "none"))
                )
                and judge is not None
                and hasattr(judge, "extract_value")
            ):
                llm_raw = judge.extract_value(str(_q_get(q, "question") or ""), answer_text)
                llm_cand = _verify_llm_candidate(answer_text, llm_raw, q.unit, currency)
                if llm_cand is not None:
                    resolved_cand = llm_cand
                    extraction_method = "llm_extract"
            if resolved_cand is not None:
                vc = value_check(
                    answer_text,
                    q.expected_value,
                    expected_unit=q.unit,
                    rel_tol=q.rel_tol,
                    abs_tol=q.abs_tol,
                    display_tol=display_tol,
                    extracted_override=resolved_cand,
                    expected_currency=currency,
                )
                vc["extraction_method"] = extraction_method
            elif first_ext["status"] == "ambiguous":
                vc = value_check(
                    answer_text,
                    q.expected_value,
                    expected_unit=q.unit,
                    rel_tol=q.rel_tol,
                    abs_tol=q.abs_tol,
                    display_tol=display_tol,
                    extracted_override=first_ext,
                    expected_currency=currency,
                )
                vc["extraction_method"] = "first"
            else:
                vc = value_check(
                    answer_text,
                    q.expected_value,
                    expected_unit=q.unit,
                    rel_tol=q.rel_tol,
                    abs_tol=q.abs_tol,
                    display_tol=display_tol,
                    extracted_override={"status": "none", "value": None, "candidates": []},
                    expected_currency=currency,
                )
                vc["extraction_method"] = "none"
    else:
        vc = score_value(
            answer_text,
            q.expected_value,
            q.unit,
            q.rel_tol,
            q.abs_tol,
            display_tol=display_tol,
            case_type=case_type,
            expect=expect,
            expected_currency=currency,
        )
        vc.setdefault("extraction_method", case_type)

    checks: dict[str, dict[str, Any]] = {
        "value": vc,
        "artifact": score_artifact(
            artifacts,
            q.expected_artifact,
            q.artifact_aliases,
            q.decoys,
            expected_id=expected_art_id,
        ),
        "why": why_check(
            str(ask.get("Why") or ""),
            wj_map,
            expected_artifact=q.expected_artifact,
            expected_model=q.model,
            answer_value=vc.get("extracted") if isinstance(vc.get("extracted"), (int, float)) else None,
        ),
    }
    model = score_model(
        trace.get("status"),
        trace.get("models"),
        q.model,
        q.decoys,
        routing_evidence=str(trace.get("routing_evidence") or ""),
        correlation_confidence=str(trace.get("correlation_confidence") or "none"),
    )
    if model is not None:
        checks["model"] = model
    return checks


def _outcome(score: float | None) -> str:
    if score is None:
        return "SKIPPED"
    return {PASS: "PASS", FAIL: "FAIL"}.get(score, "INCONCLUSIVE" if score == INCONCLUSIVE else "SCORED")


def score_rows(
    run_id: str,
    ask: Mapping[str, Any],
    backend: str,
    checks: Mapping[str, Mapping[str, Any] | None],
    scored_utc: Any,
    evaluator_names: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    names = evaluator_names or EVALUATOR_NAMES
    rows: list[dict[str, Any]] = []
    for check, res in checks.items():
        if res is None:
            continue
        details = {k: v for k, v in res.items() if k not in ("score", "outcome", "reason")}
        sc_val = res.get("score")
        rows.append(
            {
                "RunId": run_id,
                "AskId": ask["AskId"],
                "QuestionId": ask["QuestionId"],
                "Backend": backend,
                "Check": check,
                "Evaluator": names.get(check, check),
                "Score": sc_val,
                "Outcome": res.get("outcome") or _outcome(sc_val),
                "Reason": res.get("reason", ""),
                "Details": details,
                "ScoredUtc": scored_utc,
            }
        )
    return rows


def result_row(
    run_id: str,
    q: Any,
    ask: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    trace: Mapping[str, Any],
    checks: Mapping[str, Mapping[str, Any] | None],
    backend: str,
    scored_utc: Any,
    gate_checks: Sequence[str] = GATE_CHECKS,
    backend_error: str = "",
) -> dict[str, Any]:
    def s(name: str) -> float | None:
        res = checks.get(name)
        return None if res is None else res.get("score")

    value = dict(checks.get("value") or {})
    decoy = bool((checks.get("artifact") or {}).get("decoy_hit") or (checks.get("model") or {}).get("decoy_hit"))
    if ask["Status"] != "ok" or backend_error:
        final = "ERROR"
    else:
        final = verdict({k: s(k) for k in gate_checks}, required=gate_checks)

    def notes(keys: Sequence[str]) -> list[str]:
        return [
            f"{k}: {r.get('reason', '')}"
            for k, r in checks.items()
            if k in keys
            and r is not None
            and r.get("reason")
            and (r.get("outcome") or _outcome(r.get("score"))) in ("FAIL", "INCONCLUSIVE")
        ]

    reasons = notes(gate_checks)
    if ask["Status"] == "ok":
        reasons += [f"{k}: required check did not return a score" for k in gate_checks if s(k) is None]
    judge_notes = notes([k for k in checks if k not in gate_checks])
    if ask["Status"] != "ok":
        reasons.insert(0, f"Copilot Chat API error: {ask.get('Error', '')}")
    if backend_error:
        reasons.insert(0, f"{backend} evaluation error: {backend_error}")
    stats = trace["stats"]
    cited = citation_artifacts(artifacts)
    routing_ev = str(
        (checks.get("model") or {}).get("routing_evidence")
        or trace.get("routing_evidence")
        or ("engine+citations" if "model" in gate_checks else "citations-only")
    )
    corr_conf = str(
        (checks.get("model") or {}).get("correlation_confidence") or trace.get("correlation_confidence") or "none"
    )
    cited_names = sorted({str(a.get("name") or a.get("url") or "") for a in cited if a.get("name") or a.get("url")})
    return {
        "RunId": run_id,
        "AskId": ask["AskId"],
        "QuestionId": q.id,
        "Attempt": ask["Attempt"],
        "Question": q.question,
        "Category": q.category,
        "Criticality": q.criticality,
        "TestUser": ask["TestUser"],
        "AskStartUtc": ask["AskStartUtc"],
        "Backend": backend,
        "Verdict": final,
        "ValueScore": s("value"),
        "ArtifactScore": s("artifact"),
        "ModelScore": s("model"),
        "JudgeAnswerScore": s("judge_answer"),
        "WhyScore": s("why"),
        "DecoyHit": int(decoy),
        "PowerBiCited": len(powerbi_artifacts(cited)),
        "ExpectedArtifact": q.expected_artifact,
        "CitedArtifacts": "; ".join(cited_names),
        "ExpectedModel": q.model,
        "QueriedModels": "; ".join(trace["models"]),
        "ExpectedValue": q.expected_value,
        "ExtractedValue": value.get("extracted"),
        "ValueErrorPct": value.get("error_pct"),
        "LatencyMs": ask["LatencyMs"],
        "WhyLatencyMs": ask["WhyLatencyMs"],
        "DaxQueryCount": stats["count"],
        "DaxTotalMs": stats["total"],
        "DaxMaxMs": stats["max"],
        "FirstDaxOffsetMs": stats["first_offset"],
        "TraceStatus": trace["status"],
        "AnswerPreview": (ask["Answer"] or "")[:1500],
        "WhyPreview": (ask["Why"] or "")[:1000],
        "Reasons": " | ".join(reasons)[:2000],
        "JudgeNotes": " | ".join(judge_notes)[:2000],
        "Error": backend_error or ask.get("Error") or "",
        "ScoredUtc": scored_utc,
        "CaseType": str(_q_get(q, "case_type") or "scalar"),
        "Persona": str(ask.get("Persona") or _q_get(q, "persona") or ""),
        "MatchKind": str(value.get("match_kind") or ""),
        "ExtractionMethod": str(value.get("extraction_method") or ""),
        "RoutingEvidence": routing_ev,
        "CorrelationConfidence": corr_conf,
    }


class LocalBackend:
    """Local scoring: deterministic scorers in Python plus an optional Foundry-hosted judge model."""

    name = "fabric-native"

    def __init__(
        self,
        judge: Any = None,
        gate_on_judge: bool = False,
        telemetry: Any = None,
        clock: Any = None,
        gate_checks: Sequence[str] | None = None,
    ) -> None:
        self.judge = judge
        base_gates = tuple(gate_checks) if gate_checks is not None else GATE_CHECKS
        self.gate = base_gates + (("judge_answer",) if gate_on_judge and "judge_answer" not in base_gates else ())
        self.telemetry = telemetry
        self.clock = clock

    def evaluate(
        self, run_id: str, items: Sequence[Mapping[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        scores: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for it in items:
            q, ask, artifacts, trace = it["q"], it["ask"], it["artifacts"], it["trace"]
            trace_enabled = str(trace.get("status") or "disabled").lower() != "disabled"
            case_gates = _q_get(q, "gates")
            if case_gates:
                policy = load_gate_policy(
                    "auto",
                    trace_enabled=trace_enabled,
                    case_gates=case_gates,
                    judge_gates_verdict=("judge_answer" in self.gate),
                )
                active_gates: Sequence[str] = policy["gates"]
            elif not trace_enabled and self.gate[:3] == GATE_CHECKS:
                policy = load_gate_policy(
                    "without_engine_evidence",
                    trace_enabled=False,
                    judge_gates_verdict=("judge_answer" in self.gate),
                )
                active_gates = policy["gates"]
            else:
                active_gates = self.gate

            checks: dict[str, dict[str, Any] | None] = dict(
                deterministic_checks(q, ask, artifacts, trace, judge=self.judge)
            )
            if self.judge and ask["Status"] == "ok":
                with self._stage("score.judge", ask["AskId"]):
                    if hasattr(self.judge, "judge_answer"):
                        checks["judge_answer"] = _with_outcome(self.judge.judge_answer(q, ask["Answer"]))
                    if hasattr(self.judge, "judge_why"):
                        cited = sorted(
                            {str(a.get("name") or "") for a in citation_artifacts(artifacts) if a.get("name")}
                        )
                        dax = "\n".join(x.dax for x in trace["queries"])[:1500]
                        checks["why"] = _with_outcome(
                            self.judge.judge_why(q, ask["Answer"], cited, ask["Why"], trace["models"], dax)
                        )
            now = self.clock.now()
            scores += score_rows(run_id, ask, self.name, checks, now)
            results.append(result_row(run_id, q, ask, artifacts, trace, checks, self.name, now, active_gates))
        return scores, results

    def _stage(self, name: str, ask_id: str) -> AbstractContextManager[Any]:
        if self.telemetry is None:
            return nullcontext()
        ctx: AbstractContextManager[Any] = self.telemetry.stage(name, ask_id)
        return ctx


def _with_outcome(res: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if res is None:
        return None
    out = dict(res)
    sc = out.get("score")
    out.setdefault(
        "outcome",
        "PASS" if sc is not None and sc >= 0.75 else "FAIL" if sc is not None and sc <= 0.25 else "INCONCLUSIVE",
    )
    if "passed" not in out:
        out["passed"] = 1 if out["outcome"] == "PASS" else 0 if out["outcome"] == "FAIL" else -1
    return out
