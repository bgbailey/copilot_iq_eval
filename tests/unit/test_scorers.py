"""Unit tests for deterministic scorers v2 (M1-01, M1-03, M1-04, M2-04)."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from cfeval import scorers
from cfeval.scorers import (
    VERDICTS,
    artifact_check,
    extract_answer_value,
    extract_numbers,
    load_gate_policy,
    model_check,
    parse_markdown_table,
    score_artifact,
    score_model,
    score_value,
    value_check,
    verdict,
    why_check,
)


def test_public_names_and_bundle_size_guard() -> None:
    assert set(VERDICTS) == {"PASS", "FAIL", "INCONCLUSIVE", "ERROR"}
    src_bytes = Path(scorers.__file__).read_bytes()
    assert len(src_bytes) < 200_000, "scorers.py must stay comfortably under Foundry 256 KB limit"


def test_extract_answer_value_is_strictly_blind_to_expected() -> None:
    sig = inspect.signature(extract_answer_value)
    assert "expected" not in sig.parameters
    assert "expected_value" not in sig.parameters


def test_extract_numbers_metadata_fields() -> None:
    text = "In FY2025, Contoso revenue reached **$12.84M** ($10.00M in FY2024)."
    nums = extract_numbers(text)
    assert len(nums) == 2
    lead, prior = nums[0], nums[1]
    for key in (
        "value",
        "unit",
        "raw",
        "currency",
        "span",
        "scale",
        "in_parens",
        "is_bold",
        "in_first_sentence",
        "is_change_target",
        "is_change_prior",
        "is_table_cell",
    ):
        assert key in lead
    assert lead["value"] == pytest.approx(12_840_000.0)
    assert lead["currency"] == "USD"
    assert lead["unit"] == "currency"
    assert lead["scale"] == 1e6
    assert lead["is_bold"] is True
    assert lead["in_parens"] is False
    assert lead["in_first_sentence"] is True
    assert prior["value"] == pytest.approx(10_000_000.0)
    assert prior["in_parens"] is True


@pytest.mark.parametrize(
    ("text", "expected_val", "expected_unit"),
    [
        ("In FY2025, Contoso closed 418 deals.", 418.0, "count"),
        ("For FY 2025, net additions reached 95.", 95.0, "count"),
        ("During CY2025, total shipments hit 1,240.", 1240.0, "count"),
        ("In Q3 2025, gross margin stood at 42.1%.", 42.1, "percent"),
        ("For H1 2025, EMEA onboarded 312 partners.", 312.0, "count"),
        ("In 2025, Contoso opened 14 hubs.", 14.0, "count"),
        ("Since 2024, active seats grew to 8,900.", 8900.0, "count"),
        ("Performance vs. 2024 improved by 185 bps.", 185.0, "bps"),
        ("As of 2025-11-01, backlog was $4.2M.", 4_200_000.0, "currency"),
        ("In Nov 2025, active accounts reached 640.", 640.0, "count"),
        ("In November 2025, renewal rate was 91.5%.", 91.5, "percent"),
        ("Warehouse 4 shipped 2025 units in Q3 2025.", 2025.0, "units"),
        ("Online store logged 2,025 orders during 2025.", 2025.0, "orders"),
        ("Average partner rebate was $2,025 in FY2025.", 2025.0, "currency"),
    ],
)
def test_temporal_year_stripping_preserves_counts_and_amounts(
    text: str, expected_val: float, expected_unit: str
) -> None:
    ext = extract_answer_value(text, expected_unit=expected_unit)
    assert ext["status"] == "ok", f"Failed on {text!r}: {ext}"
    assert ext["value"] == pytest.approx(expected_val)


@pytest.mark.parametrize(
    ("text", "expected_target"),
    [
        ("Revenue rose from $10M to $12.84M.", 12_840_000.0),
        ("ARR increased from $40.0M to $51.2M in FY2025.", 51_200_000.0),
        ("Gross margin grew from 38.5% to 42.1%.", 42.1),
        ("Cloud profit grew by $2.84M to $12.84M.", 12_840_000.0),
        ("Active users went from 1.2M to 1.85M.", 1_850_000.0),
        ("Orders climbed from 9,100 to 11,450.", 11_450.0),
        ("Churn fell from 8.2% to 5.9%.", 5.9),
        ("Returns dropped from 3,400 units to 2,150 units.", 2150.0),
        ("Legacy revenue declined from $9.8M to $6.45M.", 6_450_000.0),
        ("Unit cost decreased from $1.85 to $1.32.", 1.32),
        ("Revenue reached $12.84M, up from $10.0M last year.", 12_840_000.0),
        ("Compared with $10.0M in FY2024, sales rose to $12.84M.", 12_840_000.0),
    ],
)
def test_change_clauses_classified_before_ranges(text: str, expected_target: float) -> None:
    ext = extract_answer_value(text)
    assert ext["status"] == "ok", f"Change clause misclassified on {text!r}: {ext}"
    assert ext["value"] == pytest.approx(expected_target)


@pytest.mark.parametrize(
    "text",
    [
        "Revenue was between $12M and $13M.",
        "Revenue landed at $12M\u2013$13M.",
        "Estimated revenue: $12M - $13M.",
        "Full-year revenue was $12M to $13M.",
        "Guidance is from $12M to $13M.",
        "Gross margin was 10% - 12%.",
    ],
)
def test_true_ranges_rejected_terminally(text: str) -> None:
    ext = extract_answer_value(text)
    assert ext["status"] == "range"
    res = value_check(text, 12_500_000.0 if "$" in text else 11.0)
    assert res["passed"] == 0
    assert res["match_kind"] == "range_rejected"


def test_scale_aware_rounding_crucial_invariant() -> None:
    expected = 12_840_000

    r_exact_raw = value_check("$12,840,000", expected, expected_unit="currency", rel_tol=0.005, display_tol=0.01)
    assert r_exact_raw["passed"] == 1
    assert r_exact_raw["match_kind"] == "exact_match"

    r_exact_scale = value_check("$12.84M", expected, expected_unit="currency", rel_tol=0.005, display_tol=0.01)
    assert r_exact_scale["passed"] == 1
    assert r_exact_scale["match_kind"] == "exact_match"

    r_disp_pass = value_check("$12.8M", expected, expected_unit="currency", rel_tol=0.005, display_tol=0.01)
    assert r_disp_pass["passed"] == 1
    assert r_disp_pass["match_kind"] == "display_rounded"

    r_disp_fail = value_check("About $13M", expected, expected_unit="currency", rel_tol=0.005, display_tol=0.01)
    assert r_disp_fail["passed"] == 0
    assert r_disp_fail["match_kind"] == "mismatch"


def test_markdown_table_scalar_ambiguity_and_parser() -> None:
    md_only = "| Region | Revenue |\n|---|---|\n| North America | $7,200,000 |\n| EMEA | $5,640,000 |"
    parsed = parse_markdown_table(md_only)
    assert parsed is not None
    assert parsed["headers"] == ["Region", "Revenue"]
    assert len(parsed["rows"]) == 2

    ext_ambig = extract_answer_value(md_only, expected_unit="currency")
    assert ext_ambig["status"] == "ambiguous"
    assert ext_ambig["value"] is None

    with_summary = "Total global revenue was $12.84M.\n\n" + md_only
    ext_ok = extract_answer_value(with_summary, expected_unit="currency")
    assert ext_ok["status"] == "ok"
    assert ext_ok["value"] == pytest.approx(12_840_000.0)


def test_currency_conflict_rejected() -> None:
    res_eur_vs_usd = value_check(
        "EMEA revenue was \u20ac12.84M.",
        12_840_000,
        expected_unit="currency",
        expected_currency="USD",
    )
    assert res_eur_vs_usd["passed"] == 0
    assert res_eur_vs_usd["match_kind"] == "no_number"

    res_eur_ok = value_check(
        "EMEA revenue was \u20ac12.84M.",
        12_840_000,
        expected_unit="currency",
        expected_currency="EUR",
    )
    assert res_eur_ok["passed"] == 1


def test_artifact_and_model_checks_v2_and_v1() -> None:
    artifacts = [
        {
            "source": "citation",
            "id": "art-uuid-001",
            "name": "Exec Sales Scorecard",
            "url": "https://app.powerbi.com/groups/me/reports/art-uuid-001",
        }
    ]
    by_id = artifact_check([], artifacts, expected_name="Different Name", expected_id="ART-UUID-001")
    assert by_id["passed"] == 1
    assert by_id["matched_by"] == "id"

    by_name = artifact_check([], artifacts, expected_name="Exec Sales Scorecard", expected_id="")
    assert by_name["passed"] == 1
    assert by_name["matched_by"] == "name"

    empty = artifact_check([], artifacts, expected_name="", expected_id="")
    assert empty["passed"] == -1

    # v1 alias compatibility
    v1_art = score_artifact(artifacts, "Exec Sales Scorecard")
    assert v1_art["score"] == 1.0

    # model_check with tool_call routing evidence
    mc_tool = model_check(
        {
            "status": "disabled",
            "routing_evidence": "tool_call",
            "correlation_confidence": "high",
            "queries": [{"model": "Contoso Sales Model", "dax": "EVALUATE ROW(...)"}],
        },
        expected_model="Contoso Sales Model",
    )
    assert mc_tool["passed"] == 1
    assert mc_tool["routing_evidence"] == "tool_call"
    assert mc_tool["correlation_confidence"] == "high"

    v1_mod = score_model("ok", ["Contoso Sales Model"], "Contoso Sales Model")
    assert v1_mod is not None and v1_mod["score"] == 1.0


def test_why_check_and_gate_policies_and_verdict() -> None:
    wc = why_check(
        "Calculated from the Contoso Sales Model at $12.84M.",
        {"answer": "$12.84M"},
        expected_artifact="Contoso Sales Report",
        expected_model="Contoso Sales Model",
        answer_value=12_840_000.0,
    )
    assert wc["passed"] == 1

    pol_engine = load_gate_policy("auto", trace_enabled=True, surface="copilot-chat")
    assert pol_engine["profile"] == "with_engine_evidence"
    assert pol_engine["gates"] == ("value", "artifact", "model")
    assert pol_engine["incomplete_on_missing_trace"] is True
    assert len(pol_engine["gate_policy_hash"]) == 16

    pol_no_trace = load_gate_policy("auto", trace_enabled=False, surface="copilot-chat", judge_gates_verdict=True)
    assert pol_no_trace["profile"] == "without_engine_evidence"
    assert pol_no_trace["gates"] == ("value", "artifact", "judge_answer")
    assert pol_no_trace["incomplete_on_missing_trace"] is False

    pol_wiq = load_gate_policy("auto", trace_enabled=False, surface="work-iq")
    assert pol_wiq["profile"] == "work_iq"
    assert pol_wiq["gates"] == ("value", "artifact")

    checks = {"value": {"passed": 1}, "artifact": {"passed": 1}, "model": {"passed": 1}}
    assert verdict(checks, ask_ok=True, trace_status="observed") == "PASS"
    assert verdict(checks, ask_ok=False, trace_status="observed") == "ERROR"
    assert verdict(checks, ask_ok=True, trace_status="missing", incomplete_on_missing_trace=True) == "INCONCLUSIVE"
    assert (
        verdict(
            checks, ask_ok=True, trace_status="missing", gates=("value", "artifact"), incomplete_on_missing_trace=False
        )
        == "PASS"
    )

    # v1 float scores compatibility
    v1_scores = {"value": score_value("$100", 100, "currency")["score"], "artifact": 1.0, "model": 1.0}
    assert verdict(v1_scores) == "PASS"
