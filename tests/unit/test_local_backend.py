"""Unit tests for the local evaluation backend (copilot_evals.evaluation.local, PLAN §9.12, ADR-009).

The local backend must apply the committed definitions exactly as Foundry would: same evaluator
files, thresholds, data mappings and extraction messages, the same INCONCLUSIVE rule, and the same
content-addressed evaluator versions. A fake judge stands in for the Azure OpenAI deployment.
"""

import json
import re
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from copilot_evals.evaluation.backend import BackendName
from copilot_evals.evaluation.dataset import read_eval_items
from copilot_evals.evaluation.definitions import catalog_name, load_definitions
from copilot_evals.evaluation.local import LocalBackend, fill, parse_json_object, render
from copilot_evals.evaluation.verdict import attempt_outcome
from copilot_evals.schemas import EvaluatorResult, Outcome


class FakeJudge:
    """Records every request and answers the extraction step and the behaviour judge from scripts."""

    def __init__(self, *, verdict: str = '{"result": 5, "reason": "Observed: answer. Gives a figure."}') -> None:
        self.verdict = verdict
        self.extraction = '{"status": "one", "value": "$12.84M", "rows": [], "quote": "$12.84M"}'
        self.requests: list[list[dict[str, str]]] = []

    def complete(self, messages: Sequence[Mapping[str, str]], *, max_output_tokens: int | None = None) -> str:
        self.requests.append([dict(message) for message in messages])
        is_extraction = any(message["role"] == "developer" for message in messages)
        return self.extraction if is_extraction else self.verdict


def _rows(evaluators_dir: Path) -> list[dict[str, Any]]:
    """The committed sample rows, serialised exactly as the backends receive them."""
    path = evaluators_dir / "samples" / "eval-items.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _results(results: Sequence[EvaluatorResult], attempt_no: int) -> dict[str, EvaluatorResult]:
    """One attempt's results keyed by evaluator, for attempt IDs ending in ``attempt_no``."""
    suffix = f"{attempt_no:012d}"
    return {result.evaluator: result for result in results if str(result.attempt_id).endswith(suffix)}


def test_sample_rows_are_valid_eval_items(evaluators_dir: Path) -> None:
    items = read_eval_items(evaluators_dir / "samples" / "eval-items.jsonl")

    assert len(items) == 7
    assert {item.case_id for item in items} >= {"REV-001", "CLR-001", "NOA-001", "JNT-001"}
    assert [fact.key for fact in items[-1].expected_facts] == ["fy25_revenue_targets.gross_revenue_target"]


def test_code_evaluators_run_with_the_committed_thresholds(evaluators_dir: Path) -> None:
    run = LocalBackend(load_definitions(evaluators_dir)).evaluate_rows(_rows(evaluators_dir))

    clean = _results(run.results, 1)
    assert run.backend == BackendName.LOCAL
    assert clean["routing_match"].outcome == Outcome.PASS
    assert clean["routing_match"].threshold == 0.5
    assert clean["no_decoy"].outcome == Outcome.PASS
    assert clean["citation_match"].outcome == Outcome.PASS

    decoy = _results(run.results, 2)
    assert decoy["routing_match"].outcome == Outcome.FAIL
    assert decoy["no_decoy"].outcome == Outcome.FAIL
    assert attempt_outcome(decoy.values()) == Outcome.FAIL

    joint = _results(run.results, 7)
    assert joint["work_source_match"].outcome == Outcome.PASS
    assert joint["no_decoy"].outcome == Outcome.PASS


def test_an_evaluator_that_raises_is_inconclusive(evaluators_dir: Path) -> None:
    run = LocalBackend(load_definitions(evaluators_dir)).evaluate_rows(_rows(evaluators_dir))

    incomplete = _results(run.results, 3)
    assert incomplete["routing_match"].outcome == Outcome.INCONCLUSIVE
    assert "InconclusiveError" in incomplete["routing_match"].reason
    assert incomplete["routing_match"].score is None


def test_without_a_judge_the_judges_results_are_inconclusive(evaluators_dir: Path) -> None:
    run = LocalBackend(load_definitions(evaluators_dir)).evaluate_rows(_rows(evaluators_dir))

    behavior = [result for result in run.results if result.evaluator == "behavior_match"]
    assert len(behavior) == 7
    assert {result.outcome for result in behavior} == {Outcome.INCONCLUSIVE}
    assert run.extractions == {}


def test_the_judge_never_sees_the_expected_value(evaluators_dir: Path) -> None:
    judge = FakeJudge()
    rows = _rows(evaluators_dir)

    LocalBackend(load_definitions(evaluators_dir), judge=judge).evaluate_rows(rows)

    sent = "\n".join(message["content"] for request in judge.requests for message in request)
    assert judge.requests
    for row in rows:
        if row["expected_value"] is not None:
            assert row["expected_value"] not in sent
            assert row["expected_value"].rstrip("0").rstrip(".") not in sent


def test_judge_results_use_the_prompt_threshold(evaluators_dir: Path) -> None:
    definitions = load_definitions(evaluators_dir)
    rows = _rows(evaluators_dir)

    passed = LocalBackend(definitions, judge=FakeJudge()).evaluate_rows(rows)
    failed = LocalBackend(definitions, judge=FakeJudge(verdict='{"result": 2, "reason": "Observed: refuse."}'))

    assert _results(passed.results, 1)["behavior_match"].outcome == Outcome.PASS
    result = _results(failed.evaluate_rows(rows).results, 1)["behavior_match"]
    assert result.outcome == Outcome.FAIL
    assert result.score == 2
    assert result.threshold == 4
    assert result.reason == "Observed: refuse."


@pytest.mark.parametrize("reply", ["no JSON here", '{"reason": "missing result"}', '{"result": "high"}'])
def test_an_unusable_judge_reply_is_inconclusive(evaluators_dir: Path, reply: str) -> None:
    backend = LocalBackend(load_definitions(evaluators_dir), judge=FakeJudge(verdict=reply))

    result = _results(backend.evaluate_rows(_rows(evaluators_dir)).results, 1)["behavior_match"]

    assert result.outcome == Outcome.INCONCLUSIVE
    assert result.reason.startswith("judge error:")


def test_extraction_runs_for_answer_rows_and_reaches_the_evaluators(evaluators_dir: Path, tmp_path: Path) -> None:
    root = _with_probe_evaluator(evaluators_dir, tmp_path)
    judge = FakeJudge()

    run = LocalBackend(load_definitions(root), judge=judge).evaluate_rows(_rows(evaluators_dir))

    probe = {str(result.attempt_id)[-1]: result.outcome for result in run.results if result.evaluator == "probe"}
    assert probe["1"] == Outcome.PASS  # answer row: the extraction arrived as item["sample"]["output_text"]
    assert probe["5"] == Outcome.FAIL  # clarify row: no extraction step
    answer_rows = {row["attempt_id"] for row in _rows(evaluators_dir) if row["expected_behavior"] == "answer"}
    assert set(run.extractions) == answer_rows


def test_a_slow_evaluator_is_inconclusive(evaluators_dir: Path) -> None:
    backend = LocalBackend(load_definitions(evaluators_dir), seconds_per_call=-1.0)

    result = _results(backend.evaluate_rows(_rows(evaluators_dir)).results, 1)["routing_match"]

    assert result.outcome == Outcome.INCONCLUSIVE
    assert "Foundry sandbox stops a call" in result.reason


def test_versions_are_the_content_addressed_catalog_names(evaluators_dir: Path) -> None:
    definitions = load_definitions(evaluators_dir)

    run = LocalBackend(definitions).evaluate_rows(_rows(evaluators_dir)[:1])

    for result in run.results:
        assert result.evaluator_version == catalog_name(definitions, result.evaluator)
        assert re.fullmatch(rf"cfiq_{result.evaluator}_[0-9a-f]{{8}}", result.evaluator_version or "")
    assert dict(run.evaluator_versions) == {result.evaluator: result.evaluator_version for result in run.results}


def test_catalog_name_changes_when_the_source_changes(evaluators_dir: Path, tmp_path: Path) -> None:
    root = _with_probe_evaluator(evaluators_dir, tmp_path)
    before = catalog_name(load_definitions(root), "probe")

    source = root / "code" / "probe.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

    assert catalog_name(load_definitions(root), "probe") != before
    assert catalog_name(load_definitions(root), "routing_match") == catalog_name(
        load_definitions(evaluators_dir), "routing_match"
    )


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        ([Outcome.PASS, Outcome.PASS], Outcome.PASS),
        ([Outcome.PASS, Outcome.INCONCLUSIVE], Outcome.INCONCLUSIVE),
        ([Outcome.INCONCLUSIVE, Outcome.FAIL], Outcome.FAIL),
        ([], Outcome.INCONCLUSIVE),
    ],
)
def test_attempt_outcome(outcomes: list[Outcome], expected: Outcome) -> None:
    results = [
        EvaluatorResult(
            attempt_id="00000000-0000-4000-8000-000000000001", evaluator=f"e{index}", outcome=outcome
        )
        for index, outcome in enumerate(outcomes)
    ]

    assert attempt_outcome(results) == expected


def test_render_fills_item_and_sample_references_once() -> None:
    item = {"query": "Revenue {{item.query}}?", "expected_unit": None, "sample": {"output_text": "x"}}

    text = render("Q: {{item.query}} U: {{ item.expected_unit }} S: {{sample.output_text}}", item)

    assert text == "Q: Revenue {{item.query}}? U: null S: x"


def test_fill_and_parse_json_object() -> None:
    assert fill("{{a}} and {{b}}", {"a": "1"}) == "1 and {{b}}"
    assert parse_json_object('```json\n{"result": 4, "reason": "ok"}\n```') == {"result": 4, "reason": "ok"}
    with pytest.raises(ValueError, match="no JSON object"):
        parse_json_object("4")


def _with_probe_evaluator(evaluators_dir: Path, tmp_path: Path) -> Path:
    """A copy of the definitions with one extra code evaluator that passes only when it sees an extraction."""
    root = tmp_path / "evaluators"
    shutil.copytree(evaluators_dir, root)
    (root / "code" / "probe.py").write_text(
        "def grade(sample, item):\n"
        '    text = (item.get("sample") or {}).get("output_text") or ""\n'
        '    return 1.0 if "12.84" in text else 0.0\n',
        encoding="utf-8",
    )
    catalog = root / "evaluators.yaml"
    catalog.write_text(
        catalog.read_text(encoding="utf-8")
        + "\n  probe:\n    type: code\n    source: code/probe.py\n    reads: [sample]\n",
        encoding="utf-8",
    )
    definition = root / "eval-definition.yaml"
    definition.write_text(
        definition.read_text(encoding="utf-8").replace(
            "testing_criteria:\n",
            "testing_criteria:\n"
            "  - type: azure_ai_evaluator\n"
            "    name: probe\n"
            '    evaluator_name: "{catalog:probe}"\n'
            "    initialization_parameters: {deployment_name: x, pass_threshold: 0.5}\n",
            1,
        ),
        encoding="utf-8",
    )
    return root
