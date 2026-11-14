"""Unit and Hypothesis property tests for statistical engine (M1-06)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cfeval.stats import (
    compare_runs,
    mcnemar_exact_p,
    pass_at_k,
    pass_pow_k,
    summarize_run_stats,
    wilson_interval,
)


def test_wilson_known_values_and_validation() -> None:
    assert wilson_interval(0, 0) == (0.0, 0.0)
    lo_all, hi_all = wilson_interval(20, 20)
    assert 0.83 < lo_all < 0.85
    assert hi_all == pytest.approx(1.0)

    lo_zero, hi_zero = wilson_interval(0, 20)
    assert lo_zero == pytest.approx(0.0)
    assert 0.15 < hi_zero < 0.17

    with pytest.raises(ValueError):
        wilson_interval(5, 4)
    with pytest.raises(ValueError):
        wilson_interval(-1, 4)


def test_pass_at_k_and_pass_pow_k_semantics() -> None:
    # Single trial with k=3 clamps k_eff=1 for pass_at_k while pass_pow_k uses exponent k
    assert pass_at_k(1, 1, 3) == pytest.approx(1.0)
    assert pass_at_k(1, 0, 3) == pytest.approx(0.0)
    assert pass_pow_k(4, 2, 3) == pytest.approx(0.125)
    # n=4, c=2, k=2 -> 1 - C(2,2)/C(4,2) = 1 - 1/6 = 5/6
    assert pass_at_k(4, 2, 2) == pytest.approx(5.0 / 6.0)
    assert pass_at_k(0, 0, 1) == 0.0
    assert pass_pow_k(0, 0, 1) == 0.0


def test_mcnemar_exact_p_known_cases_and_large_n() -> None:
    assert mcnemar_exact_p(0, 0) == 1.0
    assert mcnemar_exact_p(5, 5) == pytest.approx(1.0)
    # b=8, c=0 -> 2 * (0.5**8) = 2 / 256 = 0.0078125
    assert mcnemar_exact_p(8, 0) == pytest.approx(2.0 / 256.0)
    # Large discordant counts must not underflow
    p_large = mcnemar_exact_p(1200, 1200)
    assert p_large == pytest.approx(1.0)


@given(
    n=st.integers(min_value=1, max_value=500),
    frac=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_property_wilson_bounds_and_symmetry(n: int, frac: float) -> None:
    s = min(n, max(0, int(round(frac * n))))
    lo, hi = wilson_interval(s, n)
    p_hat = s / n
    assert 0.0 <= lo <= p_hat + 1e-12
    assert p_hat - 1e-12 <= hi <= 1.0

    # Monotonicity in successes
    if s < n:
        lo_next, hi_next = wilson_interval(s + 1, n)
        assert lo <= lo_next + 1e-12
        assert hi <= hi_next + 1e-12

    # Complement symmetry
    lo_comp, hi_comp = wilson_interval(n - s, n)
    assert lo == pytest.approx(1.0 - hi_comp, abs=1e-12)
    assert hi == pytest.approx(1.0 - lo_comp, abs=1e-12)


@given(
    p_num=st.integers(min_value=1, max_value=9),
)
def test_property_wilson_shrinks_with_sample_size(p_num: int) -> None:
    lo_small, hi_small = wilson_interval(p_num, 10)
    lo_large, hi_large = wilson_interval(p_num * 10, 100)
    assert (hi_large - lo_large) < (hi_small - lo_small)


@given(
    n=st.integers(min_value=1, max_value=30),
    c=st.integers(min_value=0, max_value=30),
    k=st.integers(min_value=1, max_value=10),
)
def test_property_pass_at_k_dominates_pass_pow_k(n: int, c: int, k: int) -> None:
    c_clamped = min(c, n)
    pk = pass_at_k(n, c_clamped, k)
    ppk = pass_pow_k(n, c_clamped, k)
    assert 0.0 <= ppk <= pk + 1e-12 <= 1.0 + 1e-12


@given(
    b=st.integers(min_value=0, max_value=80),
    c=st.integers(min_value=0, max_value=80),
)
def test_property_mcnemar_symmetry_and_range(b: int, c: int) -> None:
    p_bc = mcnemar_exact_p(b, c)
    p_cb = mcnemar_exact_p(c, b)
    assert 0.0 <= p_bc <= 1.0
    assert p_bc == pytest.approx(p_cb, abs=1e-12)


def test_summarize_run_stats_and_compare_runs() -> None:
    baseline = [
        {"QuestionId": "Q1", "Verdict": "PASS", "Category": "kpi", "Criticality": "critical"},
        {"QuestionId": "Q1", "Verdict": "PASS", "Category": "kpi", "Criticality": "critical"},
        {"QuestionId": "Q2", "Verdict": "FAIL", "Category": "kpi", "Criticality": "critical"},
        {"QuestionId": "Q3", "Verdict": "PASS", "Category": "routing", "Criticality": "standard"},
        {"QuestionId": "Q4", "Verdict": "INCONCLUSIVE", "Category": "routing", "Criticality": "standard"},
    ]
    summary = summarize_run_stats(baseline, k=2)
    assert summary["total_questions"] == 4
    assert summary["total_rows"] == 5
    assert summary["inconclusive_count"] == 1
    assert summary["critical_failures"] == 1
    assert "Q2" in summary["critical_failure_ids"]
    assert set(summary["by_category"]) == {"kpi", "routing"}

    candidate = [
        {"QuestionId": "Q1", "Verdict": "PASS", "Category": "kpi", "Criticality": "critical"},
        {"QuestionId": "Q2", "Verdict": "PASS", "Category": "kpi", "Criticality": "critical"},
        {"QuestionId": "Q3", "Verdict": "FAIL", "Category": "routing", "Criticality": "standard"},
        {"QuestionId": "Q4", "Verdict": "PASS", "Category": "routing", "Criticality": "standard"},
    ]
    comp = compare_runs(baseline, candidate, k=1)
    assert comp["paired_questions"] == 4
    assert comp["regressions"] == ["Q3"]
    assert set(comp["improvements"]) == {"Q2", "Q4"}
    assert comp["b"] == 1
    assert comp["c"] == 2
    assert 0.0 <= comp["mcnemar_p"] <= 1.0
