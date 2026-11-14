"""Unit tests for cascade extraction, literal span verification, and gate policies (M1-02, M1-04)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from cfeval.golden import GoldenQuestion
from cfeval.judge import MockJudge
from cfeval.scoring import LocalBackend, score_observation


class _RecordingJudge:
    """Stub judge recording exact arguments to verify blind extraction and span guards."""

    def __init__(self, span_response: dict[str, Any] | None) -> None:
        self.span_response = span_response
        self.extract_calls: list[tuple[str, str]] = []
        self.prompt_hash = "stubhash12345678"
        self.calibration_id = "stubcal123456789"

    def extract_value(self, question: str, answer: str) -> dict[str, Any] | None:
        self.extract_calls.append((question, answer))
        return self.span_response

    def judge_answer(self, q: Any, answer: str) -> dict[str, Any]:
        return {"passed": 1, "score": 1.0, "outcome": "PASS", "reason": "stub pass"}


def _make_question(**overrides: Any) -> GoldenQuestion:
    defaults: dict[str, Any] = {
        "id": "Q-100",
        "question": "What was EMEA revenue in FY2025?",
        "category": "regional",
        "expected_artifact": "Contoso Sales Report",
        "expected_model": "Contoso Sales Model",
        "expected_value": 5_640_000.0,
        "unit": "currency",
        "currency": "USD",
        "rel_tol": 0.005,
        "display_tol": 0.01,
    }
    defaults.update(overrides)
    return GoldenQuestion(**defaults)


def _base_obs(answer: str, **extra: Any) -> dict[str, Any]:
    obs: dict[str, Any] = {
        "answer_text": answer,
        "ask_ok": True,
        "artifacts": [{"source": "citation", "name": "Contoso Sales Report"}],
        "trace": {
            "status": "observed",
            "correlation_confidence": "high",
            "queries": [{"model": "Contoso Sales Model", "dax": "EVALUATE ROW(...)"}],
        },
    }
    obs.update(extra)
    return obs


def test_cascade_step1_first_wins_without_calling_judge() -> None:
    q = _make_question()
    judge = _RecordingJudge({"span": "$5.64M", "value": 5_640_000.0})
    res = score_observation(q, _base_obs("EMEA revenue in FY2025 was **$5.64M**."), judge=judge)

    assert res["verdict"] == "PASS"
    assert res["extraction_method"] == "first"
    assert res["match_kind"] == "exact_match"
    assert res["validated_span"] == "$5.64M"
    assert judge.extract_calls == []


def test_range_rejection_is_terminal_and_never_bypassed_by_cascade() -> None:
    q = _make_question()
    judge = _RecordingJudge({"span": "$5.64M", "value": 5_640_000.0})
    obs = _base_obs(
        "EMEA revenue was between $5M and $6M.",
        why_json={"answer": "$5.64M"},
    )
    res = score_observation(q, obs, judge=judge, extract_mode="cascade")

    assert res["verdict"] == "FAIL"
    assert res["match_kind"] == "range_rejected"
    assert res["extraction_method"] == "first"
    assert judge.extract_calls == []


def test_cascade_step2_explicit_verifies_literal_substring() -> None:
    q = _make_question()
    ambig_text = "North America was $7.20M and EMEA was $5.64M in FY2025."

    # Verified literal answer in why_json -> resolves cleanly via 'explicit'
    judge_unused = _RecordingJudge(None)
    res_ok = score_observation(
        q,
        _base_obs(ambig_text, why_json={"answer": "$5.64M"}),
        judge=judge_unused,
    )
    assert res_ok["verdict"] == "PASS"
    assert res_ok["extraction_method"] == "explicit"
    assert res_ok["validated_span"] == "$5.64M"
    assert judge_unused.extract_calls == []

    # Fabricated why_json value NOT in answer_text -> rejected by span guard, falls through
    res_unverified = score_observation(
        q,
        _base_obs("North America was $7.20M and APAC was $3.10M.", why_json={"answer": "$5.64M"}),
        judge=None,
    )
    assert res_unverified["verdict"] == "INCONCLUSIVE"
    assert res_unverified["match_kind"] == "ambiguous"


def test_cascade_step3_blind_llm_extract_and_hallucination_guard() -> None:
    q = _make_question()
    ambig_text = "North America recorded $7.20M, while EMEA recorded $5.64M."

    # Offline MockJudge resolves EMEA blindly from question context
    mock_judge = MockJudge()
    res_mock = score_observation(q, _base_obs(ambig_text), judge=mock_judge)
    assert res_mock["verdict"] == "PASS"
    assert res_mock["extraction_method"] == "llm_extract"
    assert res_mock["validated_span"] == "$5.64M"
    assert len(res_mock["judge_prompt_hash"]) == 16

    # Hallucinated span not present in answer_text MUST be rejected
    bad_span_judge = _RecordingJudge({"span": "$5.64M", "value": 5_640_000.0})
    wrong_text = "North America recorded $7.20M, while EMEA recorded $4.10M."
    res_hallucinated = score_observation(q, _base_obs(wrong_text), judge=bad_span_judge)
    assert len(bad_span_judge.extract_calls) == 1
    assert bad_span_judge.extract_calls[0] == (q.question, wrong_text)
    assert res_hallucinated["checks"]["value"]["passed"] == -1
    assert res_hallucinated["match_kind"] == "ambiguous"

    # Mismatched value vs span parse MUST also be rejected
    mismatch_val_judge = _RecordingJudge({"span": "$4.10M", "value": 5_640_000.0})
    res_val_lie = score_observation(q, _base_obs(wrong_text), judge=mismatch_val_judge)
    assert res_val_lie["checks"]["value"]["passed"] == -1
    assert res_val_lie["match_kind"] == "ambiguous"


def test_diagnostic_closest_mode_and_gate_profiles() -> None:
    q = _make_question()
    ambig_text = "North America recorded $7.20M, while EMEA recorded $5.64M."

    res_closest = score_observation(q, _base_obs(ambig_text), extract_mode="closest")
    assert res_closest["verdict"] == "PASS"
    assert res_closest["extraction_method"] == "closest"

    # Missing trace is INCONCLUSIVE under with_engine_evidence, PASS under without_engine_evidence
    obs_no_trace = {
        "answer_text": "EMEA revenue was $5.64M.",
        "ask_ok": True,
        "artifacts": [{"source": "citation", "name": "Contoso Sales Report"}],
        "trace": {"status": "missing", "queries": []},
    }
    res_strict = score_observation(q, obs_no_trace, trace_enabled=True)
    assert res_strict["verdict"] == "INCONCLUSIVE"
    assert res_strict["gate_profile"] == "with_engine_evidence"

    obs_disabled = {
        "answer_text": "EMEA revenue was $5.64M.",
        "ask_ok": True,
        "artifacts": [{"source": "citation", "name": "Contoso Sales Report"}],
        "trace": {"status": "disabled", "queries": []},
    }
    res_citations_only = score_observation(q, obs_disabled, trace_enabled=False)
    assert res_citations_only["verdict"] == "PASS"
    assert res_citations_only["gate_profile"] == "without_engine_evidence"
    assert res_citations_only["routing_evidence"] == "citations-only"

    with pytest.raises(ValueError, match="extract_mode"):
        score_observation(q, _base_obs("$5.64M"), extract_mode="invalid_mode")


def test_local_backend_preserves_v1_and_emits_v2_columns() -> None:
    class _Clock:
        def now(self) -> datetime:
            return datetime(2025, 11, 5, 12, 0, tzinfo=timezone.utc)

    q = _make_question(persona="exec_sponsor")
    ask = {
        "AskId": "ask-1",
        "QuestionId": q.id,
        "Attempt": 1,
        "Status": "ok",
        "Answer": "EMEA revenue was $5.6M in FY2025.",
        "Why": "Sourced from Contoso Sales Model.",
        "TestUser": "alex.wilber@contoso.com",
        "AskStartUtc": datetime(2025, 11, 5, 11, 59, tzinfo=timezone.utc),
        "LatencyMs": 1250.0,
        "WhyLatencyMs": 420.0,
        "Error": "",
    }
    artifacts = [{"source": "citation", "name": "Contoso Sales Report", "kind": "Report"}]
    trace = {
        "status": "disabled",
        "models": [],
        "queries": [],
        "stats": {"count": 0, "total": 0.0, "max": 0.0, "first_offset": None},
    }
    backend = LocalBackend(judge=MockJudge(), gate_on_judge=False, clock=_Clock())
    scores, results = backend.evaluate("run-001", [{"q": q, "ask": ask, "artifacts": artifacts, "trace": trace}])

    assert len(results) == 1
    row = results[0]
    assert row["Verdict"] == "PASS"
    assert row["MatchKind"] == "display_rounded"
    assert row["CaseType"] == "scalar"
    assert row["Persona"] == "exec_sponsor"
    assert row["RoutingEvidence"] == "citations-only"
    assert len(scores) >= 3
