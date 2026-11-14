"""Unit tests for AnswerJudge, MockJudge, blind extraction, and calibration kappa (M1-07)."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cfeval.judge import (
    PROMPT_VERSION,
    AnswerJudge,
    FoundryJudge,
    MockJudge,
    calibrate_judge,
    cohens_kappa,
    judge_prompt_hash,
)

CALIBRATION_PATH = Path(__file__).resolve().parents[2] / "data" / "judge_calibration" / "answers.jsonl"


class _FakeCompletions:
    def __init__(self, payloads: list[str]) -> None:
        self._payloads = list(payloads)

    def create(self, **kwargs: object) -> object:
        content = self._payloads.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class _FakeOpenAIClient:
    def __init__(self, payloads: list[str]) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(payloads))


def test_prompt_version_and_deterministic_hash() -> None:
    assert PROMPT_VERSION == "v2"
    h1 = judge_prompt_hash()
    h2 = judge_prompt_hash()
    assert h1 == h2
    assert len(h1) == 16


def test_extract_value_signatures_are_strictly_blind() -> None:
    for cls in (AnswerJudge, FoundryJudge, MockJudge):
        sig = inspect.signature(cls.extract_value)
        assert list(sig.parameters) == ["self", "question", "answer"]


def test_cohens_kappa_edge_cases() -> None:
    assert cohens_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == pytest.approx(1.0)
    assert cohens_kappa([1, 1, 1, 1], [1, 1, 1, 1]) == pytest.approx(1.0)
    assert cohens_kappa([1, 1, 0, 0], [1, 0, 1, 0]) == pytest.approx(0.0)
    assert cohens_kappa([1, 1, 0, 0], [0, 0, 1, 1]) < 0.0

    with pytest.raises(ValueError):
        cohens_kappa([1, 0], [1])
    with pytest.raises(ValueError):
        cohens_kappa([], [])


def test_calibration_dataset_integrity_and_mock_judge_kappa() -> None:
    assert CALIBRATION_PATH.exists(), f"Missing calibration set at {CALIBRATION_PATH}"
    rows = [json.loads(line) for line in CALIBRATION_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) >= 125, f"Expected >= 125 calibration pairs, found {len(rows)}"

    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "Duplicate calibration IDs"

    negatives = sum(1 for r in rows if r["human_pass"] == 0)
    assert negatives / len(rows) >= 0.40, "Calibration dataset must contain >= 40% negatives"

    judge = MockJudge()
    report = calibrate_judge(judge, CALIBRATION_PATH, min_kappa=0.70)
    assert report["total"] == len(rows)
    assert report["kappa"] >= 0.85, (
        f"Expected MockJudge kappa >= 0.85, got {report['kappa']:.3f}: {report['disagreements']}"
    )
    assert report["passed"] is True
    assert len(report["calibration_id"]) == 16
    assert judge.calibration_id == report["calibration_id"]
    assert "work_iq" in report["by_slice"]
    assert "abstention" in report["by_slice"]


def test_answer_judge_offline_client_and_call_cap() -> None:
    client = _FakeOpenAIClient(
        [
            '{"correct": true, "reason": "Matches $12.84M"}',
            '{"score": 5, "reason": "Consistent with model"}',
            '{"span": "$5.64M", "value": 5640000, "unit": "currency", "reason": "EMEA clause"}',
            '{"span": "$99.9M", "value": 99900000, "unit": "currency", "reason": "Not in text"}',
        ]
    )
    judge = AnswerJudge(client=client, deployment="gpt-judge-test", max_calls=4)

    ans_res = judge.judge_answer(
        {"question": "Revenue?", "expected_value": 12_840_000, "unit": "currency", "rel_tol": 0.005},
        "Revenue was $12.84M.",
    )
    assert ans_res is not None
    assert ans_res["passed"] == 1
    assert ans_res["score"] == 1.0

    why_res = judge.judge_why(
        {"question": "Revenue?"},
        "Revenue was $12.84M.",
        ["Sales Report"],
        "From Sales Report and Sales Model.",
        ["Sales Model"],
        "EVALUATE ...",
    )
    assert why_res is not None
    assert why_res["raw_score"] == 5
    assert why_res["score"] == 1.0

    ext_ok = judge.extract_value("EMEA revenue?", "North America was $7.20M and EMEA was $5.64M.")
    assert ext_ok is not None
    assert ext_ok["span"] == "$5.64M"
    assert ext_ok["value"] == pytest.approx(5_640_000.0)

    # Hallucinated span rejected by AnswerJudge._validate_extracted_span
    ext_bad = judge.extract_value("EMEA revenue?", "North America was $7.20M and EMEA was $5.64M.")
    assert ext_bad is None

    # 5th call hits max_calls=4 limit
    with pytest.raises(RuntimeError, match="Maximum judge call limit reached"):
        judge.extract_value("EMEA revenue?", "EMEA was $5.64M.")
