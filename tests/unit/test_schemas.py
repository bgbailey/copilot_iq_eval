"""Unit tests for the data contracts in copilot_evals.schemas (PLAN §5.1, §9.1)."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from copilot_evals.schemas import (
    Attempt,
    Behavior,
    Case,
    CaseResult,
    EvalItem,
    Persona,
    TableExpectation,
    Tolerance,
)


def _answer_case(**expect_overrides: Any) -> dict[str, Any]:
    """A minimal valid 'answer' case as raw YAML-like data."""
    expect: dict[str, Any] = {
        "behavior": "answer",
        "models": ["sales_analytics"],
        "decoys": ["sales_sandbox"],
        "value": {
            "reference_dax": 'EVALUATE ROW("v", [Gross Revenue])',
            "unit": "currency_usd",
            "tolerance": {"rel": 0.005, "display_aware": True},
        },
    }
    expect.update(expect_overrides)
    return {
        "id": "REV-001",
        "intent": "gross_revenue_fy",
        "prompt": "What was gross revenue?",
        "persona": "exec",
        "expect": expect,
    }


def _case_result(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "run_id": uuid4(),
        "case_id": "REV-001",
        "surface": "ref_mcp",
        "persona": "exec",
        "k": 3,
        "passes": 2,
        "verdict": "FAIL",
    }
    record.update(overrides)
    return record


def _attempt(**overrides: Any) -> dict[str, Any]:
    start = datetime(2026, 11, 4, 7, 1, 2, tzinfo=UTC)
    record: dict[str, Any] = {
        "attempt_id": uuid4(),
        "run_id": uuid4(),
        "case_id": "REV-001",
        "surface": "agent_cli",
        "persona": "exec",
        "persona_upn": "eval.exec@contoso.example",
        "attempt_no": 1,
        "t0_utc": start,
        "t1_utc": start + timedelta(seconds=12),
        "latency_ms": 12000,
        "status": "ok",
    }
    record.update(overrides)
    return record


def test_valid_answer_case_parses_with_defaults() -> None:
    case = Case.model_validate(_answer_case())

    assert case.expect.behavior == Behavior.ANSWER
    assert case.runs == 3
    assert case.surfaces is None
    assert case.expect.value is not None
    assert case.expect.value.tolerance.display_aware


@pytest.mark.parametrize("case_id", ["rev-001", "REV-1", "REV_001", "TOOLONG-001"])
def test_rejects_malformed_case_ids(case_id: str) -> None:
    with pytest.raises(ValidationError, match="id"):
        Case.model_validate({**_answer_case(), "id": case_id})


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Case.model_validate({**_answer_case(), "expected_model": "sales_analytics"})


def test_answer_case_needs_an_expected_value() -> None:
    with pytest.raises(ValidationError, match="needs an expected 'value' or 'table'"):
        Case.model_validate(_answer_case(value=None))


def test_answer_case_needs_an_expected_model() -> None:
    with pytest.raises(ValidationError, match="at least one expected model"):
        Case.model_validate(_answer_case(models=[]))


def test_non_answer_case_must_not_define_a_value() -> None:
    with pytest.raises(ValidationError, match="must not define an expected value"):
        Case.model_validate(_answer_case(behavior="clarify"))


def test_clarify_case_needs_no_models() -> None:
    case = Case.model_validate({**_answer_case(), "expect": {"behavior": "clarify"}})

    assert case.expect.models == []


def test_model_cannot_be_both_expected_and_decoy() -> None:
    with pytest.raises(ValidationError, match="both expected and decoy"):
        Case.model_validate(_answer_case(decoys=["sales_analytics"]))


def test_value_needs_exactly_one_ground_truth_source() -> None:
    both = {"reference_dax": "EVALUATE ROW(\"v\", 1)", "composite": "top_region", "unit": "count"}
    neither = {"unit": "count"}

    with pytest.raises(ValidationError, match="exactly one of 'reference_dax' or 'composite'"):
        Case.model_validate(_answer_case(value=both))
    with pytest.raises(ValidationError, match="exactly one of 'reference_dax' or 'composite'"):
        Case.model_validate(_answer_case(value=neither))


def test_composite_ground_truth_is_accepted() -> None:
    value = {"composite": "top_sev1_region_gross_revenue", "unit": "currency_usd"}

    case = Case.model_validate(_answer_case(value=value))

    assert case.expect.value is not None
    assert case.expect.value.composite == "top_sev1_region_gross_revenue"


def test_top_n_table_match_needs_n() -> None:
    with pytest.raises(ValidationError, match="'n' is required"):
        TableExpectation.model_validate({"reference_dax": "EVALUATE x", "unit": "count", "match": "top_n"})

    table = TableExpectation.model_validate({"reference_dax": "EVALUATE x", "unit": "count", "match": "top_n", "n": 3})
    assert table.n == 3


def test_tolerance_rejects_negative_values() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        Tolerance.model_validate({"rel": -0.1})


def test_tolerance_values_are_decimals() -> None:
    tolerance = Tolerance.model_validate({"rel": "0.005", "abs": 0})

    assert isinstance(tolerance.rel, Decimal)
    assert tolerance.rel == Decimal("0.005")


def test_persona_upn_template_resolves() -> None:
    persona = Persona.model_validate(
        {
            "key": "exec",
            "upn": "eval.exec@{tenant_domain}",
            "keyvault_secret": "msal-cache-exec",
            "workspaces": ["ws-eval-certified"],
            "rls": "All regions",
            "purpose": "Baseline",
        }
    )

    assert persona.resolve_upn("contoso.example") == "eval.exec@contoso.example"


def test_attempt_rejects_naive_timestamps() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        Attempt.model_validate(_attempt(t0_utc="2026-11-04T07:01:02"))


def test_attempt_normalises_timestamps_to_utc() -> None:
    eastern = timezone(timedelta(hours=-5))
    attempt = Attempt.model_validate(
        _attempt(
            t0_utc=datetime(2026, 11, 4, 2, 1, 2, tzinfo=eastern),
            t1_utc=datetime(2026, 11, 4, 2, 1, 14, tzinfo=eastern),
        )
    )

    assert attempt.t0_utc == datetime(2026, 11, 4, 7, 1, 2, tzinfo=UTC)
    assert attempt.t0_utc.utcoffset() == timedelta(0)


def test_attempt_window_must_be_ordered() -> None:
    start = datetime(2026, 11, 4, 7, 1, 2, tzinfo=UTC)

    with pytest.raises(ValidationError, match="t1_utc must not be earlier than t0_utc"):
        Attempt.model_validate(_attempt(t0_utc=start, t1_utc=start - timedelta(seconds=1)))


def test_case_result_derives_pass_rate() -> None:
    result = CaseResult.model_validate(_case_result(passes=2))

    assert result.pass_rate == Decimal(2) / Decimal(3)
    assert not result.pass_all_k


def test_case_result_passes_cannot_exceed_k() -> None:
    with pytest.raises(ValidationError, match="passes cannot exceed k"):
        CaseResult.model_validate(_case_result(passes=4, verdict="PASS"))


def _eval_item(**overrides: Any) -> dict[str, Any]:
    """A valid evaluation row for an 'answer' case."""
    record: dict[str, Any] = {
        "attempt_id": uuid4(),
        "run_id": uuid4(),
        "case_id": "REV-001",
        "intent": "gross_revenue_fy",
        "surface": "agent_cli",
        "layer": "L2",
        "persona": "exec",
        "attempt_no": 1,
        "criticality": "critical",
        "status": "ok",
        "latency_ms": 9100,
        "query": "What was gross revenue in FY2025?",
        "response": "Gross revenue for FY2025 was $12.84M.",
        "expected_behavior": "answer",
        "expected_shape": "scalar",
        "expected_unit": "currency_usd",
        "expected_value": "12840000.25",
        "tolerance": {"rel": "0.005", "display_aware": True},
        "expected_models": ["sales_analytics"],
        "evidence_complete": True,
    }
    record.update(overrides)
    return record


def test_eval_item_serialises_decimals_as_strings() -> None:
    item = EvalItem.model_validate(_eval_item())

    dumped = item.model_dump(mode="json")

    assert dumped["expected_value"] == "12840000.25"
    assert dumped["tolerance"]["rel"] == "0.005"
    assert dumped["expected_behavior"] == "answer"


def test_eval_item_non_answer_rows_carry_no_expected_value() -> None:
    with pytest.raises(ValidationError, match="only 'answer' rows carry an expected value"):
        EvalItem.model_validate(_eval_item(expected_behavior="clarify", expected_shape="none"))


def test_eval_item_scalar_rows_need_an_expected_value() -> None:
    with pytest.raises(ValidationError, match="needs expected_value and expected_unit"):
        EvalItem.model_validate(_eval_item(expected_value=None))


def test_eval_item_table_rows_need_rows_and_a_match_rule() -> None:
    row = _eval_item(expected_shape="table", expected_value=None, expected_table=[{"key": "East", "value": "12"}])

    with pytest.raises(ValidationError, match="needs expected_table and table_match"):
        EvalItem.model_validate(row)

    assert EvalItem.model_validate({**row, "table_match": "all_keys"}).expected_table[0].key == "East"
