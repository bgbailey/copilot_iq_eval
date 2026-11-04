"""Unit tests for the backlog file and scripts/bootstrap_github.py (no GitHub calls)."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_script(repo_root: Path) -> ModuleType:
    """Import scripts/bootstrap_github.py, which is a script rather than a package module."""
    path = repo_root / "scripts" / "bootstrap_github.py"
    spec = importlib.util.spec_from_file_location("bootstrap_github", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script(repo_root: Path) -> ModuleType:
    return _load_script(repo_root)


def test_backlog_is_consistent(script: ModuleType) -> None:
    backlog = script.load_backlog()

    ids = [task["id"] for task in backlog.tasks]
    assert len(ids) == len(set(ids))
    assert {f"P{n}" for n in range(11)} == set(backlog.milestone_by_key)


def test_every_plan_prompt_is_marked_copilot_ready(script: ModuleType) -> None:
    for task in script.load_backlog().tasks:
        assert ("copilot-ready" in task["labels"]) == bool(task.get("prompt")), task["id"]


def test_manual_tasks_carry_the_manual_label(script: ModuleType) -> None:
    for task in script.load_backlog().tasks:
        assert (task["executor"] == "manual") == ("type:manual" in task["labels"]), task["id"]


def test_issue_body_has_prompt_and_checklist(script: ModuleType) -> None:
    backlog = script.load_backlog()
    task = next(t for t in backlog.tasks if t["id"] == "P2.5")

    body = script.render_issue_body(task, backlog, "https://github.com/OWNER/REPO", {"P2.2": 7})

    assert body.startswith("<!-- backlog-id: P2.5 -->")
    assert "### Copilot prompt" in body
    assert "> Implement the code-based evaluator `evals/evaluators/code/value_match.py`" in body
    assert "- [ ] " in body
    assert "- #7 [P2.2]" in body


def test_issue_title_prefix_is_the_task_id(script: ModuleType) -> None:
    task = {"id": "P2.5", "title": "Evaluators"}

    assert script.issue_title(task) == "[P2.5] Evaluators"


def test_backlog_readme_lists_every_task(script: ModuleType, repo_root: Path) -> None:
    readme = (repo_root / "docs" / "backlog" / "README.md").read_text(encoding="utf-8")

    for task in script.load_backlog().tasks:
        assert f"| {task['id']} |" in readme, task["id"]


def test_dry_run_makes_no_github_calls(script: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    assert script.main(["--dry-run"]) == 0

    assert "issues (" in capsys.readouterr().out
