"""Files that must stay in step with each other, checked on every push."""

import re
from pathlib import Path

import yaml


def _appendix_a(plan: str) -> str:
    """The Markdown block in PLAN Appendix A, which is the repository's Copilot instructions."""
    start = plan.index("## Appendix A")
    block_start = plan.index("```markdown\n", start) + len("```markdown\n")
    block_end = plan.index("\n```\n", block_start)
    return plan[block_start:block_end] + "\n"


def test_copilot_instructions_are_plan_appendix_a(repo_root: Path) -> None:
    plan = (repo_root / "docs" / "PLAN.md").read_text(encoding="utf-8")
    instructions = (repo_root / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")

    assert instructions == _appendix_a(plan)


def test_contract_todos_name_spikes_in_the_backlog(repo_root: Path) -> None:
    contracts = (repo_root / "config" / "contracts.yaml").read_text(encoding="utf-8")
    backlog = yaml.safe_load((repo_root / "docs" / "backlog" / "tasks.yaml").read_text(encoding="utf-8"))
    spikes = {task["id"] for task in backlog["tasks"] if "type:spike" in task["labels"]}

    referenced = set(re.findall(r"TODO\(spike-(S\d+)\)", contracts))

    assert referenced
    assert referenced <= spikes
