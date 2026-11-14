"""Offline unit tests for Foundry v2 code_bundle execution, foundry_row, and FoundryEvaluation.run."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cfeval.foundry import (
    CODE_EVALUATORS,
    FIELDS,
    FoundryEvaluation,
    code_bundle,
    foundry_row,
    parse_output_items,
)
from cfeval.golden import GoldenQuestion


def _compile_grade(check: str) -> Any:
    bundle = code_bundle(check)
    # Ensure `from __future__ import annotations` remains before executable statements
    compiled = compile(bundle, f"<foundry-{check}>", "exec")
    ns: dict[str, Any] = {"__name__": f"foundry_eval_{check}"}
    exec(compiled, ns)
    return ns["grade"]


def test_code_bundle_value_covers_scalar_display_ranked_list_and_abstention() -> None:
    grade_value = _compile_grade("value")

    # 1. Scalar exact match
    assert (
        grade_value(
            None,
            {
                "response": "Gross revenue in FY2025 was $12,840,000.",
                "expected_value": "12840000.0",
                "unit": "currency",
                "rel_tol": "0.005",
                "abs_tol": "0.0",
                "display_tol": "0.01",
                "case_type": "scalar",
                "expect_json": "",
                "currency": "USD",
            },
        )
        == 1.0
    )

    # 2. Display-rounded ($12.8M vs 12,840,000) passes with display_tol=0.01, fails when display_tol=0.0
    rounded_item = {
        "response": "Gross revenue reached $12.8M.",
        "expected_value": "12840000.0",
        "unit": "currency",
        "rel_tol": "0.001",
        "abs_tol": "0.0",
        "display_tol": "0.01",
        "case_type": "scalar",
        "expect_json": "",
        "currency": "USD",
    }
    assert grade_value(None, rounded_item) == 1.0
    assert grade_value(None, {**rounded_item, "display_tol": "0.0"}) == 0.0

    # 3. Ranked list (ordered)
    ranked_expect = json.dumps({"items": ["North America", "EMEA", "APAC"], "ordered": True})
    assert (
        grade_value(
            None,
            {
                "response": "1. North America\n2. EMEA\n3. APAC",
                "expected_value": "",
                "unit": "",
                "case_type": "ranked_list",
                "expect_json": ranked_expect,
            },
        )
        == 1.0
    )
    assert (
        grade_value(
            None,
            {
                "response": "1. APAC\n2. EMEA\n3. North America",
                "expected_value": "",
                "unit": "",
                "case_type": "ranked_list",
                "expect_json": ranked_expect,
            },
        )
        == 0.0
    )

    # 4. Abstention
    abstention_expect = json.dumps({"forbidden": ["$500,000"]})
    assert (
        grade_value(
            None,
            {
                "response": "That information is not available in the semantic model.",
                "expected_value": "",
                "case_type": "abstention",
                "expect_json": abstention_expect,
            },
        )
        == 1.0
    )
    assert (
        grade_value(
            None,
            {
                "response": "The projected budget is $500,000.",
                "expected_value": "",
                "case_type": "abstention",
                "expect_json": abstention_expect,
            },
        )
        == 0.0
    )


def test_code_bundle_artifact_and_model_support_artifact_id_and_tool_call() -> None:
    grade_artifact = _compile_grade("artifact")
    grade_model = _compile_grade("model")

    art_uuid = "e084ee51-d06c-5bf0-bfcb-4aede296f141"
    cited_arts = [
        {
            "item_id": art_uuid,
            "kind": "powerbi_report",
            "name": "Renamed Executive Report",
            "source": "attribution",
            "url": f"https://app.powerbi.com/groups/ws-1/reports/{art_uuid}",
        }
    ]
    assert (
        grade_artifact(
            None,
            {
                "artifacts_json": json.dumps(cited_arts),
                "expected_artifact": "Original Sales Report",
                "expected_artifact_id": art_uuid,
                "artifact_aliases": "",
                "decoys": "Sales Forecast Legacy",
            },
        )
        == 1.0
    )

    # Model check with routing_evidence="tool_call" passes even when workspace monitoring trace_status="disabled"
    assert (
        grade_model(
            None,
            {
                "trace_status": "disabled",
                "queried_models_json": json.dumps(["Sales Analytics"]),
                "expected_model": "Sales Analytics",
                "decoys": "Sales Legacy",
                "routing_evidence": "tool_call",
                "correlation_confidence": "high",
            },
        )
        == 1.0
    )
    # Without tool_call, disabled trace returns inconclusive (0.5)
    assert (
        grade_model(
            None,
            {
                "trace_status": "disabled",
                "queried_models_json": "[]",
                "expected_model": "Sales Analytics",
                "decoys": "",
                "routing_evidence": "citations-only",
                "correlation_confidence": "none",
            },
        )
        == 0.5
    )


def test_foundry_row_populates_v2_fields_with_string_schema() -> None:
    q = GoldenQuestion(
        id="Q05",
        question="Rank the three regions by FY2025 gross revenue.",
        category="multi-row",
        expected_artifact="Sales Analytics",
        expected_artifact_id="e084ee51-d06c-5bf0-bfcb-4aede296f141",
        expected_model="Sales Analytics",
        decoys="Sales Legacy",
        expected_value=None,
        unit="",
        case_type="ranked_list",
        expect={"items": ["North America", "EMEA", "APAC"], "ordered": True},
        display_tol=0.02,
        currency="USD",
    )
    ask = {"AskId": "run1:Q05:1", "Answer": "1. North America, 2. EMEA, 3. APAC", "Why": "Queried Sales Analytics"}
    artifacts = [
        {
            "name": "Sales Analytics",
            "kind": "powerbi_report",
            "source": "attribution",
            "url": "https://app.powerbi.com/groups/g/reports/e084ee51-d06c-5bf0-bfcb-4aede296f141",
        }
    ]
    trace = {
        "status": "observed",
        "models": ["Sales Analytics"],
        "queries": [{"Dax": "EVALUATE SUMMARIZECOLUMNS('Region'[Name])", "ItemName": "Sales Analytics"}],
        "routing_evidence": "tool_call",
        "correlation_confidence": "high",
    }

    row = foundry_row(q, ask, artifacts, trace)
    assert set(row.keys()) == set(FIELDS)
    assert all(isinstance(v, str) for v in row.values())
    assert row["case_type"] == "ranked_list"
    assert json.loads(row["expect_json"])["ordered"] is True
    assert row["expected_artifact_id"] == "e084ee51-d06c-5bf0-bfcb-4aede296f141"
    assert row["routing_evidence"] == "tool_call"
    assert row["correlation_confidence"] == "high"
    assert row["display_tol"] == "0.02"
    assert row["currency"] == "USD"


class _FakeEvaluatorsAPI:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], dict[str, Any]] = {}
        self.create_calls = 0

    def create_version(self, *, name: str, evaluator_version: dict[str, Any]) -> dict[str, Any]:
        self.create_calls += 1
        ver = str(self.create_calls)
        record = {
            "name": name,
            "version": ver,
            "definition": dict(evaluator_version["definition"]),
        }
        self.store[(name, ver)] = record
        return record

    def get_version(self, *, name: str, version: str) -> dict[str, Any]:
        return self.store[(name, str(version))]


class _FakeProjectClient:
    def __init__(self) -> None:
        self.evaluators = _FakeEvaluatorsAPI()
        self.created_evals: list[dict[str, Any]] = []
        self.created_runs: list[dict[str, Any]] = []
        self._retrieve_Count = 0

        outer = self

        class _OutputItems:
            def list(self, *, run_id: str, eval_id: str) -> list[dict[str, Any]]:
                rows = outer.created_runs[-1]["data_source"]["source"]["content"]
                items: list[dict[str, Any]] = []
                for entry in rows:
                    ask_item = entry["item"]
                    results = []
                    for check_name, (eval_name, _expr) in CODE_EVALUATORS.items():
                        grade_fn = _compile_grade(check_name)
                        sc = grade_fn(None, ask_item)
                        results.append({"name": eval_name, "score": sc, "reason": "ok"})
                    results.append({"name": "cfeval_answer_correctness", "score": 5, "reason": "exact"})
                    results.append({"name": "cfeval_why_consistency", "score": 4, "reason": "consistent"})
                    results.append({"name": "builtin.coherence", "score": 5, "reason": "coherent"})
                    results.append({"name": "builtin.similarity", "score": 5, "reason": "similar"})
                    items.append({"datasource_item": ask_item, "status": "completed", "results": results})
                return items

        class _Runs:
            output_items = _OutputItems()

            def create(self, **kwargs: Any) -> SimpleNamespace:
                outer.created_runs.append(kwargs)
                return SimpleNamespace(id="evalrun-001", status="in_progress", report_url="")

            def retrieve(self, *, run_id: str, eval_id: str) -> SimpleNamespace:
                outer._retrieve_Count += 1
                return SimpleNamespace(
                    id=run_id,
                    status="completed",
                    report_url="https://ai.azure.example/evals/evalrun-001",
                    error=None,
                )

        class _Evals:
            runs = _Runs()

            def create(self, **kwargs: Any) -> SimpleNamespace:
                outer.created_evals.append(kwargs)
                return SimpleNamespace(id="eval-001")

        self._openai = SimpleNamespace(evals=_Evals())

    def get_openai_client(self) -> Any:
        return self._openai


def test_foundry_evaluation_full_offline_lifecycle_and_cache(tmp_path: Path) -> None:
    fake_project = _FakeProjectClient()
    cache_file = tmp_path / "cache" / "foundry_evaluators.json"

    fe = FoundryEvaluation(
        project_endpoint="https://contoso-foundry.services.ai.azure.example/api/projects/demo",
        deployment="gpt-4o",
        project_client=fake_project,
        cache_path=cache_file,
        poll_seconds=0.0,
        timeout_seconds=10.0,
        log=lambda _m: None,
    )

    q = GoldenQuestion(
        id="Q01",
        question="What was gross revenue in FY2025?",
        expected_artifact="Sales Analytics",
        expected_model="Sales Analytics",
        expected_value=12840000.0,
        unit="currency",
        expected_answer="Gross revenue in FY2025 was $12,840,000.",
    )
    row = foundry_row(
        q,
        {"AskId": "run1:Q01:1", "Answer": "Gross revenue in FY2025 was $12.84M.", "Why": "Sales Analytics"},
        [
            {
                "name": "Sales Analytics",
                "kind": "powerbi_report",
                "source": "attribution",
                "url": "https://app.powerbi.com/groups/g/reports/r1",
            }
        ],
        {
            "status": "observed",
            "models": ["Sales Analytics"],
            "queries": [{"Dax": "EVALUATE {12840000}"}],
            "routing_evidence": "engine+citations",
            "correlation_confidence": "high",
        },
    )

    result = fe.run([row], "unit-test-eval")
    assert result["status"] == "completed"
    assert result["eval_id"] == "eval-001"
    assert result["run_id"] == "evalrun-001"
    assert fake_project.evaluators.create_calls == 5  # 3 code + 2 prompt evaluators

    ask_scores = result["scores"]["run1:Q01:1"]
    assert ask_scores["value"]["score"] == 1.0
    assert ask_scores["artifact"]["score"] == 1.0
    assert ask_scores["model"]["score"] == 1.0
    assert ask_scores["judge_answer"]["score"] == 1.0
    assert ask_scores["why"]["score"] == pytest.approx(0.75)
    assert Path(result["operation_path"]).exists()

    # Second run reuses cached evaluator versions without re-creating
    fe2 = FoundryEvaluation(
        project_endpoint="https://contoso-foundry.services.ai.azure.example/api/projects/demo",
        deployment="gpt-4o",
        project_client=fake_project,
        cache_path=cache_file,
        poll_seconds=0.0,
        timeout_seconds=10.0,
        log=lambda _m: None,
    )
    fe2.ensure_evaluators()
    assert fake_project.evaluators.create_calls == 5


def test_parse_output_items_handles_conflicts_and_invalid_scores() -> None:
    items = [
        {
            "datasource_item": {"ask_id": "ask-1"},
            "status": "completed",
            "results": [
                {"name": "cfeval_value_match", "score": 1.0, "reason": "ok"},
                {"name": "cfeval_value_match", "score": 0.0, "reason": "conflict"},
                {"name": "cfeval_answer_correctness", "score": 99, "reason": "out of range"},
            ],
        }
    ]
    parsed = parse_output_items(items, ["value", "judge_answer"])
    assert parsed["ask-1"]["value"]["outcome"] == "INCONCLUSIVE"
    assert "conflicting" in parsed["ask-1"]["value"]["error"]
    assert parsed["ask-1"]["judge_answer"]["outcome"] == "INCONCLUSIVE"
