"""Unit tests for Golden v2 JSON Schema, YAML/CSV loaders, paraphrase expansion, and linter."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cfeval.golden import GoldenQuestion, load_golden, sample_golden_path, validate_golden_file, write_golden
from cfeval.golden_v2 import (
    GoldenValidationError,
    convert_csv_to_yaml,
    lint_golden_file,
    load_golden_schema,
    validate_golden_dict,
)


def test_schema_is_valid_draft_2020_12() -> None:
    schema = load_golden_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_v1_positional_backwards_compatibility(tmp_path: Path) -> None:
    q = GoldenQuestion(
        "Q-001",
        "What was FY2025 net revenue?",
        "revenue",
        "Contoso Sales Report",
        "Sales Scorecard",
        "Contoso Sales Model",
        "Archive 2022",
        12_840_000.0,
        "currency",
        0.005,
        0.0,
        "$12.84M",
        'EVALUATE ROW("Rev", [Net Revenue])',
        "critical",
        "Core KPI",
    )
    assert q.expected == 12_840_000.0
    assert q.model == "Contoso Sales Model"
    row = q.to_row("run-123")
    assert row["QuestionId"] == "Q-001"
    assert row["CaseType"] == "scalar"

    out_csv = tmp_path / "out.csv"
    write_golden([q], out_csv)
    reloaded = load_golden(out_csv)
    assert len(reloaded) == 1
    assert reloaded[0].id == "Q-001"
    assert reloaded[0].expected_value == 12_840_000.0


def test_v2_nested_and_flat_yaml_loading_and_paraphrases(tmp_path: Path) -> None:
    yaml_doc = {
        "schema": "cfeval.golden/v2",
        "dataset": "contoso-v2",
        "as_of": "2025-11-01",
        "defaults": {"repeats": 3, "rel_tol": 0.005, "display_tol": 0.01},
        "cases": [
            {
                "id": "Q001",
                "question": "What was total net revenue in FY2025?",
                "paraphrases": [
                    "Show FY2025 total net revenue.",
                    "How much net revenue did we book in FY2025?",
                ],
                "category": "kpi",
                "criticality": "critical",
                "persona": "finance_analyst",
                "tags": ["revenue", "fy2025"],
                "gates": ["value", "artifact"],
                "expectation": {
                    "type": "numeric",
                    "value": 12840000,
                    "unit": "currency",
                    "currency": "USD",
                    "reference_dax": 'EVALUATE ROW("v", [Net Revenue])',
                },
                "routing": {
                    "expected_model": {"name": "Contoso Sales", "id": "11111111-2222-3333-4444-555555555555"},
                    "expected_artifacts": [{"name": "Executive Sales", "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}],
                    "decoys": [{"name": "Legacy FY22 Sales"}],
                },
            },
            {
                "id": "Q002",
                "question": "Rank the top 2 customers by ARR.",
                "case_type": "ranked_list",
                "expect": {"items": ["Alpine Ski House", "Northwind Traders"], "ordered": True},
            },
        ],
    }
    yaml_file = tmp_path / "suite.yaml"
    yaml_file.write_text(yaml.safe_dump(yaml_doc, sort_keys=False), encoding="utf-8")

    base_qs = load_golden(yaml_file, expand_paraphrases=False)
    assert len(base_qs) == 2
    assert base_qs[0].expected_artifact_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert base_qs[0].currency == "USD"
    assert base_qs[0].gates == ["value", "artifact"]
    assert base_qs[1].case_type == "ranked_list"

    expanded = load_golden(yaml_file, expand_paraphrases=True)
    assert len(expanded) == 4
    assert [q.id for q in expanded] == ["Q001", "Q001__p1", "Q001__p2", "Q002"]
    assert expanded[1].paraphrase_of == "Q001"
    assert expanded[1].question == "Show FY2025 total net revenue."


def test_validation_rejects_duplicates_and_malformed_expectations() -> None:
    bad_dup = {
        "cases": [
            {"id": "DUP-1", "question": "First?", "expected_value": 10},
            {"id": "DUP-1", "question": "Second?", "expected_value": 20},
        ]
    }
    with pytest.raises(GoldenValidationError, match="DUP-1"):
        validate_golden_dict(bad_dup)

    bad_ranked = {
        "cases": [{"id": "BAD-RK", "question": "Rank top 3", "case_type": "ranked_list", "expect": {"items": []}}]
    }
    res = validate_golden_dict(bad_ranked, raise_on_error=False)
    assert res["valid"] is False
    assert any("BAD-RK" in e for e in res["errors"])

    bad_tol = {"cases": [{"id": "BAD-TOL", "question": "Revenue?", "expected_value": 100, "rel_tol": -0.05}]}
    with pytest.raises(GoldenValidationError, match="BAD-TOL"):
        validate_golden_dict(bad_tol)


def test_csv_to_yaml_conversion_and_linter(tmp_path: Path) -> None:
    sample_csv = sample_golden_path()
    yaml_out = tmp_path / "converted.yaml"
    rendered = convert_csv_to_yaml(sample_csv, yaml_out)
    assert "cfeval.golden/v2" in rendered

    val = validate_golden_file(yaml_out)
    assert val["valid"] is True
    loaded_yaml = load_golden(yaml_out)
    loaded_csv = load_golden(sample_csv)
    assert len(loaded_yaml) == len(loaded_csv)
    assert [q.id for q in loaded_yaml] == [q.id for q in loaded_csv]

    warnings = lint_golden_file(yaml_out)
    assert isinstance(warnings, list)
