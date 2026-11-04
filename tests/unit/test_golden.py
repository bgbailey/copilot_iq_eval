"""Unit tests for golden-set loading and cross-file checks (copilot_evals.golden)."""

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from copilot_evals.golden import GoldenSetError, Severity, check_golden_set, load_golden_set


def _copy_golden(src: Path, dst: Path) -> Path:
    """Copy the committed golden set to a scratch folder the test can modify."""
    target = dst / "golden"
    shutil.copytree(src, target)
    return target


def _edit_cases(golden: Path, edit: Callable[[list[dict[str, Any]]], object]) -> None:
    """Load cases.yaml, apply ``edit(cases)`` and write it back."""
    path = golden / "cases.yaml"
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))
    edit(cases)
    path.write_text(yaml.safe_dump(cases, sort_keys=False), encoding="utf-8")


def test_committed_golden_set_is_valid(golden_dir: Path) -> None:
    golden = load_golden_set(golden_dir)

    assert check_golden_set(golden) == []
    assert len(golden.cases) >= 10
    assert {"exec", "east", "noaccess"} <= set(golden.personas)
    assert any(model.decoy for model in golden.models.values())


def test_case_ids_are_unique_in_committed_set(golden_dir: Path) -> None:
    ids = [case.id for case in load_golden_set(golden_dir).cases]

    assert len(ids) == len(set(ids))


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(GoldenSetError, match="missing golden-set file"):
        load_golden_set(tmp_path)


def test_schema_errors_name_the_file(golden_dir: Path, tmp_path: Path) -> None:
    golden = _copy_golden(golden_dir, tmp_path)
    _edit_cases(golden, lambda cases: cases[0].update({"runs": 0}))

    with pytest.raises(GoldenSetError, match="cases.yaml"):
        load_golden_set(golden)


def test_unknown_references_are_errors(golden_dir: Path, tmp_path: Path) -> None:
    golden = _copy_golden(golden_dir, tmp_path)

    def break_references(cases: list[dict[str, Any]]) -> None:
        cases[0]["persona"] = "ghost"
        cases[0]["expect"]["decoys"] = ["no_such_model"]
        cases[0]["expect"]["doc_decoys"] = ["no_such_document"]

    _edit_cases(golden, break_references)
    findings = check_golden_set(load_golden_set(golden))
    messages = [finding.message for finding in findings if finding.severity == Severity.ERROR]

    assert any("unknown persona 'ghost'" in message for message in messages)
    assert any("unknown model 'no_such_model'" in message for message in messages)
    assert any("unknown document decoy 'no_such_document'" in message for message in messages)


def test_duplicate_case_ids_are_errors(golden_dir: Path, tmp_path: Path) -> None:
    golden = _copy_golden(golden_dir, tmp_path)
    _edit_cases(golden, lambda cases: cases.append(dict(cases[0], prompt="A different prompt")))

    findings = check_golden_set(load_golden_set(golden))

    assert any("duplicate case id" in finding.message for finding in findings)


def test_expected_decoy_model_is_an_error(golden_dir: Path, tmp_path: Path) -> None:
    golden = _copy_golden(golden_dir, tmp_path)

    def expect_the_decoy(cases: list[dict[str, Any]]) -> None:
        cases[0]["expect"]["models"] = ["sales_sandbox"]
        cases[0]["expect"]["decoys"] = []

    _edit_cases(golden, expect_the_decoy)
    findings = check_golden_set(load_golden_set(golden))

    assert any("decoy model 'sales_sandbox' is listed as an expected model" in f.message for f in findings)


def test_weak_critical_case_is_a_warning(golden_dir: Path, tmp_path: Path) -> None:
    golden = _copy_golden(golden_dir, tmp_path)

    def weaken(cases: list[dict[str, Any]]) -> None:
        cases[0]["criticality"] = "critical"
        cases[0]["runs"] = 1

    _edit_cases(golden, weaken)
    findings = check_golden_set(load_golden_set(golden))

    assert [finding.severity for finding in findings] == [Severity.WARNING]
