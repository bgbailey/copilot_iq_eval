"""Unit tests for the Microsoft Foundry code-based evaluators in evals/evaluators/code/.

Foundry uploads each evaluator file as standalone code and calls ``grade(sample, item)`` once per
dataset row. These tests load the files the same way (executed as standalone code, not imported from
a package), so they prove the behaviour Foundry will run. The rows mimic ``EvalItem`` serialised
with ``model_dump(mode="json")``: decimals are strings and enums are plain values.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

EVALUATORS_DIR = Path(__file__).resolve().parents[2] / "evals" / "evaluators" / "code"

Grade = Callable[[dict[str, Any], dict[str, Any]], float]


def _load(name: str) -> dict[str, Any]:
    """Execute one evaluator file as standalone code, as the Foundry sandbox does, and return its namespace."""
    path = EVALUATORS_DIR / f"{name}.py"
    namespace: dict[str, Any] = {"__name__": f"foundry_evaluator_{name}"}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    return namespace


ROUTING = _load("routing_match")
NO_DECOY = _load("no_decoy")
CITATION = _load("citation_match")
VALUE = _load("value_match")
WORK_SOURCE = _load("work_source_match")


def _row(**overrides: Any) -> dict[str, Any]:
    """A clean 'answer' row for REV-001, as the runner would build it."""
    row: dict[str, Any] = {
        "attempt_id": "6f0c3c1e-8f53-4a5e-9a52-2f8a0f1d9b11",
        "run_id": "1d2c3b4a-0000-4000-8000-000000000001",
        "case_id": "REV-001",
        "intent": "gross_revenue_fy",
        "surface": "agent_cli",
        "variant": "default",
        "layer": "L2",
        "persona": "exec",
        "attempt_no": 1,
        "criticality": "critical",
        "status": "ok",
        "latency_ms": 9100,
        "query": "What was gross revenue in FY2025?",
        "response": "Gross revenue for FY2025 was $12.84M. Source: Sales Analytics semantic model.",
        "citations": [{"title": "Sales Analytics", "url": "https://app.powerbi.example/reports/1", "kind": "powerbi"}],
        "expected_behavior": "answer",
        "expected_shape": "scalar",
        "expected_unit": "currency_usd",
        "expected_value": "12840000",
        "expected_table": [],
        "table_match": None,
        "table_n": None,
        "tolerance": {"rel": "0.005", "abs": "0", "display_aware": True, "max_display_rel": "0.05"},
        "expected_models": ["sales_analytics"],
        "route_mode": "includes",
        "decoy_models": ["sales_sandbox", "finance"],
        "doc_decoy_patterns": ["FY2025 revenue - DRAFT"],
        "citation_required": True,
        "expected_sources": ["Sales Analytics"],
        "work_sources": [],
        "expected_facts": [],
        "observed_models": ["sales_analytics"],
        "observed_by_source": {"engine_log": ["sales_analytics"]},
        "evidence_complete": True,
    }
    row.update(overrides)
    return row


def _grade(namespace: dict[str, Any], row: dict[str, Any]) -> float:
    grade: Grade = namespace["grade"]
    return grade({}, row)


def _inconclusive(namespace: dict[str, Any]) -> type[Exception]:
    error: type[Exception] = namespace["InconclusiveError"]
    return error


# --- Shared behaviour ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "namespace",
    [ROUTING, NO_DECOY, CITATION, VALUE, WORK_SOURCE],
    ids=["routing", "no_decoy", "citation", "value", "work_source"],
)
def test_failed_surface_call_is_inconclusive(namespace: dict[str, Any]) -> None:
    with pytest.raises(_inconclusive(namespace), match="surface status 'timeout'"):
        _grade(namespace, _row(status="timeout", response=""))


# --- routing_match ------------------------------------------------------------------------------


def test_routing_includes_passes_when_expected_model_queried() -> None:
    assert _grade(ROUTING, _row()) == 1.0


def test_routing_includes_allows_other_certified_models() -> None:
    assert _grade(ROUTING, _row(observed_models=["sales_analytics", "service_operations"])) == 1.0


def test_routing_fails_when_expected_model_missing_and_logs_complete() -> None:
    assert _grade(ROUTING, _row(observed_models=["finance"])) == 0.0


def test_routing_fails_when_no_fabric_query_and_logs_complete() -> None:
    assert _grade(ROUTING, _row(observed_models=[])) == 0.0


def test_routing_is_inconclusive_when_logs_incomplete_and_model_not_seen() -> None:
    with pytest.raises(_inconclusive(ROUTING), match="incomplete"):
        _grade(ROUTING, _row(observed_models=[], evidence_complete=False))


def test_routing_passes_on_positive_evidence_even_if_logs_incomplete() -> None:
    assert _grade(ROUTING, _row(evidence_complete=False)) == 1.0


def test_routing_exclusive_fails_on_extra_model_even_if_logs_incomplete() -> None:
    row = _row(route_mode="exclusive", observed_models=["sales_analytics", "finance"], evidence_complete=False)

    assert _grade(ROUTING, row) == 0.0


def test_routing_exclusive_needs_complete_logs_to_pass() -> None:
    with pytest.raises(_inconclusive(ROUTING), match="later logs"):
        _grade(ROUTING, _row(route_mode="exclusive", evidence_complete=False))

    assert _grade(ROUTING, _row(route_mode="exclusive")) == 1.0


def test_routing_any_of_needs_one_expected_model() -> None:
    row = _row(route_mode="any_of", expected_models=["finance", "sales_analytics"])

    assert _grade(ROUTING, row) == 1.0
    assert _grade(ROUTING, {**row, "observed_models": ["service_operations"]}) == 0.0


def test_routing_is_not_asserted_for_non_answer_cases() -> None:
    row = _row(expected_behavior="clarify", expected_shape="none", expected_models=[], observed_models=[])

    assert _grade(ROUTING, row) == 1.0


def test_routing_unknown_mode_is_inconclusive() -> None:
    with pytest.raises(_inconclusive(ROUTING), match="unknown route_mode"):
        _grade(ROUTING, _row(route_mode="most"))


# --- no_decoy -----------------------------------------------------------------------------------


def test_no_decoy_passes_when_clean_and_logs_complete() -> None:
    assert _grade(NO_DECOY, _row()) == 1.0


def test_no_decoy_fails_when_decoy_model_queried_even_if_logs_incomplete() -> None:
    row = _row(observed_models=["sales_analytics", "sales_sandbox"], evidence_complete=False)

    assert _grade(NO_DECOY, row) == 0.0


def test_no_decoy_fails_when_document_decoy_cited_by_title() -> None:
    citation = {"title": "FY2025 revenue - DRAFT.docx", "url": None, "kind": "sharepoint"}

    assert _grade(NO_DECOY, _row(citations=[citation])) == 0.0


def test_no_decoy_fails_when_document_decoy_cited_by_encoded_url() -> None:
    url = "https://contoso.example/sites/finance/Shared%20Documents/FY2025%20revenue%20-%20DRAFT.docx"
    citation = {"title": "Document", "url": url, "kind": "sharepoint"}

    assert _grade(NO_DECOY, _row(citations=[citation])) == 0.0


def test_no_decoy_fails_when_figure_answered_from_documents_only() -> None:
    citation = {"title": "Quarterly business review.pptx", "url": None, "kind": "sharepoint"}
    row = _row(observed_models=[], citations=[citation], response="Revenue in FY2025 was $13.1M.")

    assert _grade(NO_DECOY, row) == 0.0


def test_no_decoy_ignores_fiscal_labels_when_looking_for_figures() -> None:
    citation = {"title": "Quarterly business review.pptx", "url": None, "kind": "sharepoint"}
    row = _row(observed_models=[], citations=[citation], response="I couldn't find FY2025 Q2 revenue in 2025.")

    assert _grade(NO_DECOY, row) == 1.0  # no figure was given; routing_match reports the missing query


def test_no_decoy_is_inconclusive_when_clean_but_logs_incomplete() -> None:
    with pytest.raises(_inconclusive(NO_DECOY), match="incomplete"):
        _grade(NO_DECOY, _row(evidence_complete=False))


def test_no_decoy_passes_for_no_access_persona_with_no_queries() -> None:
    row = _row(
        persona="noaccess",
        expected_behavior="no_access",
        expected_shape="none",
        expected_value=None,
        expected_models=[],
        observed_models=[],
        citations=[],
        response="You don't have access to the certified sales data for that question.",
    )

    assert _grade(NO_DECOY, row) == 1.0


# --- citation_match -----------------------------------------------------------------------------


def test_citation_passes_when_not_required() -> None:
    assert _grade(CITATION, _row(citation_required=False, citations=[], response="$12.84M")) == 1.0


def test_citation_passes_when_source_named_in_citation_title() -> None:
    assert _grade(CITATION, _row(response="It was $12.84M.")) == 1.0


def test_citation_passes_when_source_named_only_in_text() -> None:
    row = _row(citations=[], response="Gross revenue was $12.84M (Sales Analytics).")

    assert _grade(CITATION, row) == 1.0


def test_citation_fails_when_source_not_named() -> None:
    row = _row(citations=[{"title": "Finance", "url": None, "kind": "powerbi"}], response="It was $12.84M.")

    assert _grade(CITATION, row) == 0.0


def test_citation_is_inconclusive_without_expected_sources() -> None:
    with pytest.raises(_inconclusive(CITATION), match="no expected sources"):
        _grade(CITATION, _row(expected_sources=[]))


# --- value_match (skeleton until P2.5) ------------------------------------------------------------


def test_value_match_passes_rows_that_expect_no_value() -> None:
    row = _row(expected_behavior="clarify", expected_shape="none", expected_value=None, tolerance=None)

    assert _grade(VALUE, row) == 1.0


def test_value_match_reads_the_expected_blind_extraction() -> None:
    read_extraction = VALUE["read_extraction"]
    row = _row(sample={"output_text": '{"status": "one", "value": "$12.84M", "rows": [], "quote": "was $12.84M"}'})

    extraction = read_extraction(row)

    assert extraction.status == "one"
    assert extraction.value == "$12.84M"
    assert read_extraction(_row(sample={"output_text": "not json"})) is None
    assert read_extraction(_row()) is None


# --- work_source_match (joint Work IQ + Fabric IQ cases) ---------------------------------------

TARGETS = {"key": "fy25_revenue_targets", "match": ["FY2025 Revenue Targets - APPROVED"]}
OBJECTIVES = {"key": "fy25_service_objectives", "match": ["FY2025 Service Level Objectives"]}
MEMO_URL = (
    "https://contoso.sharepoint.com/sites/planning/Shared%20Documents/FY2025%20Revenue%20Targets%20-%20APPROVED.docx"
)
MODEL_CITATION = {"title": "Sales Analytics", "url": "https://app.powerbi.example/reports/1", "kind": "powerbi"}
MEMO_CITATION = {"title": "FY2025 Revenue Targets - APPROVED.docx", "url": MEMO_URL, "kind": "file"}


def _joint_row(**overrides: Any) -> dict[str, Any]:
    """A joint case row: the answer should cite the approved targets memo as well as the model."""
    fields: dict[str, Any] = {
        "response": "FY2025 gross revenue was $12.84M against the approved $12.5M target, so the target was hit.",
        "citations": [MODEL_CITATION, MEMO_CITATION],
        "work_sources": [TARGETS],
    }
    return _row(**{**fields, **overrides})


def test_work_source_passes_rows_without_work_sources() -> None:
    assert _grade(WORK_SOURCE, _row()) == 1.0
    assert _grade(WORK_SOURCE, _row(expected_behavior="no_access", work_sources=[TARGETS])) == 1.0


def test_work_source_passes_when_document_cited() -> None:
    assert _grade(WORK_SOURCE, _joint_row()) == 1.0


def test_work_source_matches_encoded_urls_and_answer_text() -> None:
    by_url = _joint_row(citations=[{"title": "Memo", "url": MEMO_URL, "kind": "file"}])
    by_text = _joint_row(citations=[], response="Per FY2025 Revenue Targets - APPROVED, the target was $12.5M.")

    assert _grade(WORK_SOURCE, by_url) == 1.0
    assert _grade(WORK_SOURCE, by_text) == 1.0


def test_work_source_fails_when_document_not_cited() -> None:
    row = _joint_row(citations=[MODEL_CITATION], response="Revenue was $12.84M against a $12.5M target.")

    assert _grade(WORK_SOURCE, row) == 0.0


def test_work_source_needs_every_document() -> None:
    row = _joint_row(work_sources=[TARGETS, OBJECTIVES])

    assert _grade(WORK_SOURCE, row) == 0.0


def test_work_source_without_match_fragments_is_inconclusive() -> None:
    with pytest.raises(_inconclusive(WORK_SOURCE), match="no match fragments"):
        _grade(WORK_SOURCE, _joint_row(work_sources=[{"key": "fy25_revenue_targets", "match": []}]))
