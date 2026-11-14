"""Value extraction and rounding corpus regression suite (>= 155 labeled cases)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from cfeval.scorers import value_check

CORPUS_PATH = Path(__file__).resolve().parents[1] / "data" / "value_cases.jsonl"


def _load_corpus() -> list[dict]:
    lines = CORPUS_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_corpus_size_and_category_coverage() -> None:
    cases = _load_corpus()
    assert len(cases) >= 155, f"Expected >= 155 corpus cases, found {len(cases)}"
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "Duplicate case IDs in value_cases.jsonl"

    counts = Counter(c["category"] for c in cases)
    required_categories = {
        "bold_headline",
        "lead_answer",
        "change_clause_up",
        "change_clause_down",
        "parenthetical_comparator",
        "temporal_years",
        "currency_matching",
        "percent_bps_units",
        "scale_suffixes",
        "display_rounding",
        "range_rejection",
        "markdown_table_ambiguous",
        "ties_and_wrong_values",
    }
    missing = required_categories - set(counts)
    assert not missing, f"Missing required corpus categories: {missing}"


def test_value_corpus_accuracy_and_zero_false_positives() -> None:
    cases = _load_corpus()
    correct = 0
    false_positives: list[str] = []
    mismatches: list[str] = []

    for c in cases:
        res = value_check(
            c["text"],
            c["expected"],
            expected_unit=c.get("unit") or "",
            rel_tol=c.get("rel_tol", 0.005),
            abs_tol=c.get("abs_tol"),
            display_tol=c.get("display_tol", 0.01),
            expected_currency=c.get("currency") or "",
        )
        got_passed = res["passed"]
        got_kind = res["match_kind"]
        exp_passed = c["expected_passed"]
        exp_kind = c["expected_match_kind"]

        if exp_passed != 1 and got_passed == 1:
            false_positives.append(
                f"{c['id']} ({c['category']}): expected passed={exp_passed} ({exp_kind}), "
                f"got PASS ({got_kind}) on {c['text']!r}"
            )

        if got_passed == exp_passed and got_kind == exp_kind:
            correct += 1
        else:
            mismatches.append(
                f"{c['id']} ({c['category']}): expected ({exp_passed}, {exp_kind}), "
                f"got ({got_passed}, {got_kind}) — {res.get('reason')}"
            )

    assert not false_positives, "Zero false positives allowed:\n" + "\n".join(false_positives)
    accuracy = correct / len(cases)
    assert accuracy >= 0.98, f"Corpus accuracy {accuracy:.3f} < 0.98:\n" + "\n".join(mismatches)
