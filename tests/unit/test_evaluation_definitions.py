"""Unit tests for the offline evaluation definition checks (copilot_evals.evaluation.definitions)."""

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from copilot_evals.evaluation.definitions import (
    SANDBOX_PACKAGES,
    DefinitionError,
    check_definitions,
    load_definitions,
)
from copilot_evals.golden import Severity
from copilot_evals.schemas import EvalItem


def _copy(evaluators_dir: Path, tmp_path: Path) -> Path:
    """Copy the committed definitions to a scratch folder the test can modify."""
    target = tmp_path / "evaluators"
    shutil.copytree(evaluators_dir, target)
    return target


def _errors(root: Path) -> list[str]:
    findings = check_definitions(load_definitions(root))
    return [finding.message for finding in findings if finding.severity == Severity.ERROR]


def _edit_definition(root: Path, edit: Any) -> None:
    """Load eval-definition.yaml, apply ``edit(definition)`` and write it back."""
    path = root / "eval-definition.yaml"
    definition = yaml.safe_load(path.read_text(encoding="utf-8"))
    edit(definition)
    path.write_text(yaml.safe_dump(definition, sort_keys=False), encoding="utf-8")


def _criterion(definition: dict[str, Any], name: str) -> dict[str, Any]:
    criterion: dict[str, Any] = next(c for c in definition["testing_criteria"] if c["name"] == name)
    return criterion


def test_committed_definitions_are_valid(evaluators_dir: Path) -> None:
    definitions = load_definitions(evaluators_dir)

    assert check_definitions(definitions) == []
    assert {"value_match", "routing_match", "no_decoy", "citation_match", "behavior_match"} <= set(
        definitions.evaluators
    )


def test_item_schema_matches_the_eval_item_model(evaluators_dir: Path) -> None:
    definitions = load_definitions(evaluators_dir)
    required = set(definitions.definition["data_source_config"]["item_schema"]["required"])

    assert definitions.item_fields == set(EvalItem.model_fields)
    assert required == definitions.item_fields


def test_sandbox_rejects_third_party_imports(evaluators_dir: Path, tmp_path: Path) -> None:
    root = _copy(evaluators_dir, tmp_path)
    source = root / "code" / "citation_match.py"
    source.write_text("import requests\n" + source.read_text(encoding="utf-8"), encoding="utf-8")

    assert "import not available in the Foundry sandbox: requests" in _errors(root)


def test_evaluators_cannot_import_the_harness(evaluators_dir: Path, tmp_path: Path) -> None:
    root = _copy(evaluators_dir, tmp_path)
    source = root / "code" / "routing_match.py"
    source.write_text("from copilot_evals import schemas\n" + source.read_text(encoding="utf-8"), encoding="utf-8")

    assert "import not available in the Foundry sandbox: copilot_evals" in _errors(root)


def test_undeclared_field_read_is_reported(evaluators_dir: Path, tmp_path: Path) -> None:
    root = _copy(evaluators_dir, tmp_path)
    source = root / "code" / "routing_match.py"
    extra = '\n\ndef _peek(item):\n    return item.get("expected_value")\n'
    source.write_text(source.read_text(encoding="utf-8") + extra, encoding="utf-8")

    assert "reads 'expected_value' but does not declare it in 'reads'" in _errors(root)


def test_missing_grade_function_is_reported(evaluators_dir: Path, tmp_path: Path) -> None:
    root = _copy(evaluators_dir, tmp_path)
    (root / "code" / "no_decoy.py").write_text("def score(sample, item):\n    return 1.0\n", encoding="utf-8")

    assert "source must define a top-level function grade(sample, item)" in _errors(root)


def test_judge_mapping_cannot_reveal_the_expected_value(evaluators_dir: Path, tmp_path: Path) -> None:
    root = _copy(evaluators_dir, tmp_path)
    _edit_definition(
        root, lambda d: _criterion(d, "behavior_match")["data_mapping"].update(response="{{item.expected_value}}")
    )

    assert "'expected_value' would show the expected answer to an LLM" in _errors(root)


def test_extraction_template_cannot_reveal_the_expected_value(evaluators_dir: Path, tmp_path: Path) -> None:
    root = _copy(evaluators_dir, tmp_path)

    def leak(definition: dict[str, Any]) -> None:
        content = definition["run_data_source"]["input_messages"]["template"][1]["content"]
        content["text"] += "\nHint: {{item.expected_value}}"

    _edit_definition(root, leak)

    assert "'expected_value' would show the expected answer to an LLM" in _errors(root)


def test_unknown_item_field_is_reported(evaluators_dir: Path, tmp_path: Path) -> None:
    root = _copy(evaluators_dir, tmp_path)
    _edit_definition(root, lambda d: _criterion(d, "behavior_match")["data_mapping"].update(query="{{item.question}}"))

    assert "unknown item field 'question'" in _errors(root)


def test_code_evaluator_needs_a_pass_threshold(evaluators_dir: Path, tmp_path: Path) -> None:
    root = _copy(evaluators_dir, tmp_path)
    _edit_definition(root, lambda d: _criterion(d, "value_match")["initialization_parameters"].pop("pass_threshold"))

    assert "initialization_parameters needs 'pass_threshold' for a code-based evaluator" in _errors(root)


def test_missing_definition_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DefinitionError, match="missing evaluation definition file"):
        load_definitions(tmp_path)


def test_sandbox_package_list_matches_the_contract(repo_root: Path) -> None:
    contracts = yaml.safe_load((repo_root / "config" / "contracts.yaml").read_text(encoding="utf-8"))
    distributions = contracts["foundry_evaluations"]["code_evaluator"]["packages"]
    import_names = {"scikit-learn": "sklearn", "rouge-score": "rouge_score", "pyyaml": "yaml"}

    assert {import_names.get(name, name) for name in distributions} == SANDBOX_PACKAGES
