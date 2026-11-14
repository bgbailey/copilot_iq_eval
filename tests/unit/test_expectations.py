"""Unit tests for rich non-scalar expectation types (M1-05)."""

from __future__ import annotations

from cfeval.scorers import value_check


def test_ranked_list_expectations() -> None:
    expect = {"items": ["Alpine Ski House", "Northwind Traders", "Tailspin Toys"], "top_n": 3, "ordered": True}
    numbered = "1. Alpine Ski House ($1.2M)\n2. Northwind Traders ($0.95M)\n3. Tailspin Toys ($0.82M)"
    r_ok = value_check(numbered, case_type="ranked_list", expect=expect)
    assert r_ok["passed"] == 1
    assert r_ok["match_kind"] == "ranked_list_match"

    prose = "By ARR, Alpine Ski House ranked first, ahead of Northwind Traders and Tailspin Toys."
    assert value_check(prose, case_type="ranked_list", expect=expect)["passed"] == 1

    wrong_order = "1. Northwind Traders\n2. Alpine Ski House\n3. Tailspin Toys"
    r_bad = value_check(wrong_order, case_type="ranked_list", expect=expect)
    assert r_bad["passed"] == 0
    assert r_bad["match_kind"] == "wrong_order"

    missing = "1. Alpine Ski House\n2. Northwind Traders"
    r_miss = value_check(missing, case_type="ranked_list", expect=expect)
    assert r_miss["passed"] == 0
    assert r_miss["match_kind"] == "missing_items"


def test_set_expectations_with_forbidden_items() -> None:
    expect = {
        "items": ["North America", "EMEA", "APAC"],
        "forbidden_items": ["Antarctica"],
    }
    text_ok = "Active commercial regions are EMEA, APAC, and North America."
    r_ok = value_check(text_ok, case_type="set", expect=expect)
    assert r_ok["passed"] == 1
    assert r_ok["match_kind"] == "set_match"

    text_forbid = "Active regions include North America, EMEA, APAC, and Antarctica."
    r_forbid = value_check(text_forbid, case_type="set", expect=expect)
    assert r_forbid["passed"] == 0
    assert r_forbid["match_kind"] == "forbidden_item"


def test_table_and_record_expectations() -> None:
    md_table = (
        "| Region | Revenue | Margin |\n|---|---|---|\n| North America | $7.20M | 44.0% |\n| EMEA | $5.64M | 39.7% |\n"
    )
    table_expect = {
        "key": "Region",
        "rows": [
            {"Region": "North America", "Revenue": 7_200_000, "Margin": 44.0},
            {"Region": "EMEA", "Revenue": 5_640_000, "Margin": 39.7},
        ],
    }
    r_tab = value_check(md_table, case_type="table", expect=table_expect)
    assert r_tab["passed"] == 1
    assert r_tab["match_kind"] == "table_match"

    bad_table_expect = {
        "key": "Region",
        "rows": [
            {"Region": "North America", "Revenue": 9_900_000, "Margin": 44.0},
        ],
    }
    r_tab_bad = value_check(md_table, case_type="table", expect=bad_table_expect)
    assert r_tab_bad["passed"] == 0
    assert r_tab_bad["match_kind"] == "table_mismatch"

    kv_text = "- Revenue: $12.84M\n- Gross Margin: 42.1%\n- Region: North America"
    rec_expect = {"fields": {"Revenue": 12_840_000, "Gross Margin": 0.421, "Region": "North America"}}
    r_rec = value_check(kv_text, case_type="record", expect=rec_expect)
    assert r_rec["passed"] == 1
    assert r_rec["match_kind"] == "record_match"


def test_abstention_and_negative_expectations() -> None:
    valid_abstain = (
        "I cannot answer that question because employee salary records are not available in the Contoso Sales model."
    )
    r_ok = value_check(valid_abstain, case_type="abstention", expect={"forbidden": ["$165,000"]})
    assert r_ok["passed"] == 1
    assert r_ok["match_kind"] == "abstention_verified"

    hallucinated = "Contoso sales engineers earn a base salary of $162,400."
    r_hal = value_check(hallucinated, case_type="abstention")
    assert r_hal["passed"] == 0
    assert r_hal["match_kind"] == "hallucinated_on_abstention"

    hedged_leak = "Data is not available in the primary table, though estimated salary is $162,400."
    r_leak = value_check(hedged_leak, case_type="negative")
    assert r_leak["passed"] == 0
    assert r_leak["match_kind"] == "hallucinated_on_abstention"


def test_direction_citation_only_and_categorical_expectations() -> None:
    r_up = value_check(
        "Operating margin increased by 185 bps year over year.",
        case_type="direction",
        expect={"direction": "up", "value": 185, "unit": "bps"},
    )
    assert r_up["passed"] == 1
    assert r_up["match_kind"] == "direction_match"

    r_wrong_dir = value_check(
        "Operating margin dropped sharply this quarter.",
        case_type="direction",
        expect={"direction": "up"},
    )
    assert r_wrong_dir["passed"] == 0

    r_cit = value_check("Miriam Graham owns the Q4 pricing sign-off.", case_type="citation_only")
    assert r_cit["passed"] == 1
    assert r_cit["match_kind"] == "citation_only"

    r_cit_abstain = value_check("I don't have access to those emails.", case_type="citation_only")
    assert r_cit_abstain["passed"] == 0

    r_cat = value_check(
        "The top performing segment was Enterprise Cloud.",
        case_type="categorical",
        expect={"value": "Enterprise Cloud", "forbidden": ["Consumer Hardware"]},
    )
    assert r_cat["passed"] == 1
    assert r_cat["match_kind"] == "categorical_match"
