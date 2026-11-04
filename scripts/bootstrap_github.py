"""Create the project's GitHub labels, milestones and issues from docs/backlog/tasks.yaml.

PLAN §0 step 3: "Create one GitHub issue per task in §8 ... Put the task's Copilot prompt in the
issue body and its acceptance criteria as a checklist." This script does that from the backlog
file, so the issues in GitHub always match the plan in the repository.

Usage (needs the GitHub CLI, signed in with ``gh auth login``):

    uv run python scripts/bootstrap_github.py --dry-run                  # preview, no GitHub calls
    uv run python scripts/bootstrap_github.py --dry-run --show P2.5      # print one issue body
    uv run python scripts/bootstrap_github.py --repo <owner>/<repo>      # create everything

It is safe to run more than once: labels are created or updated, while milestones and issues are
only created when missing (issues are matched on their "[<id>] " title prefix). Tasks with
``status: done`` are skipped unless ``--include-done`` is given.
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKLOG = REPO_ROOT / "docs" / "backlog" / "tasks.yaml"
DEFAULT_BRANCH = "main"
EXECUTORS = {
    "copilot": "GitHub Copilot (agent mode or cloud agent)",
    "manual": "Manual: needs a person in the demo tenant",
}
ACCEPTANCE_SOURCES = {
    "plan": "_From the plan._",
    "derived": "_Derived from the task description: the plan gives no task-level criteria._",
}
PAUSE_BETWEEN_ISSUES_S = 1.0  # stay well under GitHub's secondary rate limits for content creation


class BacklogError(Exception):
    """The backlog file is inconsistent."""


class GhError(Exception):
    """A GitHub CLI call failed."""


@dataclass
class Backlog:
    """The parsed backlog: label definitions, milestones (phases) and tasks, in file order."""

    labels: list[dict[str, str]]
    milestones: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    milestone_by_key: dict[str, dict[str, Any]] = field(init=False)

    def __post_init__(self) -> None:
        self.milestone_by_key = {milestone["key"]: milestone for milestone in self.milestones}


def load_backlog(path: Path = DEFAULT_BACKLOG) -> Backlog:
    """Load the backlog file and check that its parts refer to each other correctly.

    Raises:
        BacklogError: IDs are duplicated, or a task refers to an unknown label, milestone or task.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    backlog = Backlog(labels=data["labels"], milestones=data["milestones"], tasks=data["tasks"])

    label_names = {label["name"] for label in backlog.labels}
    task_ids = [task["id"] for task in backlog.tasks]
    problems = [f"duplicate task id {task_id}" for task_id in sorted(set(task_ids)) if task_ids.count(task_id) > 1]
    for task in backlog.tasks:
        where = f"task {task['id']}"
        problems += [f"{where}: unknown label {name}" for name in task["labels"] if name not in label_names]
        problems += [f"{where}: unknown dependency {dep}" for dep in task.get("depends_on", []) if dep not in task_ids]
        if task["milestone"] not in backlog.milestone_by_key:
            problems.append(f"{where}: unknown milestone {task['milestone']}")
        if task["executor"] not in EXECUTORS:
            problems.append(f"{where}: unknown executor {task['executor']}")
        if task["status"] in ("partial", "done") and not task.get("delivered"):
            problems.append(f"{where}: status {task['status']} needs a 'delivered' list")
        if not task.get("acceptance"):
            problems.append(f"{where}: no acceptance criteria")
    if problems:
        raise BacklogError("; ".join(problems))
    return backlog


def issue_title(task: dict[str, Any]) -> str:
    """Return the issue title. The ``[<id>]`` prefix is how existing issues are recognised."""
    return f"[{task['id']}] {task['title']}"


def render_issue_body(
    task: dict[str, Any], backlog: Backlog, repo_url: str, issue_numbers: dict[str, int] | None = None
) -> str:
    """Render the Markdown body of a task's issue.

    Args:
        task: One entry of the backlog's ``tasks`` list.
        backlog: The whole backlog, for phase details.
        repo_url: Repository URL used to link to docs/PLAN.md.
        issue_numbers: Known issue numbers by task ID, used to link dependencies.
    """
    numbers = issue_numbers or {}
    milestone = backlog.milestone_by_key[task["milestone"]]
    plan_link = f"[docs/PLAN.md]({repo_url}/blob/{DEFAULT_BRANCH}/docs/PLAN.md)"
    lines = [
        f"<!-- backlog-id: {task['id']} -->",
        f"**Plan:** {plan_link} {', '.join(task['plan'])}  ",
        f"**Phase:** {milestone['title']} (days {milestone['days']})  ",
        f"**Executor:** {EXECUTORS[task['executor']]}",
        "",
        "### Goal",
        "",
        task["description"].strip(),
    ]
    if task.get("delivered"):
        lines += ["", "### Already delivered by the repository bootstrap", ""]
        lines += [f"- {item}" for item in task["delivered"]]
    if task.get("prompt"):
        lines += ["", "### Copilot prompt", ""]
        lines += [f"> {line}" if line else ">" for line in task["prompt"].strip().splitlines()]
    lines += ["", "### Acceptance criteria", "", ACCEPTANCE_SOURCES[task["acceptance_source"]], ""]
    lines += [f"- [ ] {item}" for item in task["acceptance"]]
    if milestone.get("exit_criteria") and milestone["exit_criteria"] != task["acceptance"]:
        lines += ["", f"### Phase exit criteria ({milestone['title']})", ""]
        lines += [f"- {item}" for item in milestone["exit_criteria"]]
    if task.get("notes"):
        lines += ["", "### Notes", "", task["notes"].strip()]
    if task.get("depends_on"):
        lines += ["", "### Depends on (suggested order)", ""]
        for dep in task["depends_on"]:
            lines.append(f"- #{numbers[dep]} [{dep}]" if dep in numbers else f"- [{dep}]")
    lines += ["", "---", "_Created from `docs/backlog/tasks.yaml` by `scripts/bootstrap_github.py`._", ""]
    return "\n".join(lines)


def markdown_table(backlog: Backlog) -> str:
    """Return a Markdown table of every task, for docs/backlog/README.md."""
    rows = ["| ID | Task | Phase | Executor | Status |", "|---|---|---|---|---|"]
    for task in backlog.tasks:
        phase = task["milestone"].removeprefix("P")
        rows.append(f"| {task['id']} | {task['title']} | {phase} | {task['executor']} | {task['status']} |")
    return "\n".join(rows)


class GitHub:
    """Thin wrapper over the GitHub CLI. Every call goes through ``_gh`` with an argument list."""

    def __init__(self, repo: str | None) -> None:
        executable = shutil.which("gh")
        if executable is None:
            raise GhError("GitHub CLI not found. Install it from https://cli.github.com and run 'gh auth login'.")
        self._gh_path = executable
        view = json.loads(self._gh("repo", "view", *([repo] if repo else []), "--json", "nameWithOwner,url"))
        self.repo: str = view["nameWithOwner"]
        self.url: str = view["url"]

    def _gh(self, *args: str, stdin: str | None = None) -> str:
        """Run one gh command (no shell) and return its standard output."""
        result = subprocess.run([self._gh_path, *args], input=stdin, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise GhError(f"gh {' '.join(args[:3])} failed: {result.stderr.strip()}")
        return result.stdout

    def upsert_label(self, label: dict[str, str]) -> None:
        """Create a label, or update its colour and description if it exists."""
        args = ["label", "create", label["name"], "--repo", self.repo, "--force"]
        self._gh(*args, "--color", label["color"], "--description", label["description"])

    def milestone_titles(self) -> set[str]:
        """Titles of every milestone in the repository, open or closed."""
        milestones = json.loads(self._gh("api", f"repos/{self.repo}/milestones?state=all&per_page=100"))
        return {milestone["title"] for milestone in milestones}

    def create_milestone(self, title: str, description: str) -> None:
        """Create an open milestone."""
        fields = ["-f", f"title={title}", "-f", f"description={description}"]
        self._gh("api", "--method", "POST", f"repos/{self.repo}/milestones", *fields)

    def issue_numbers_by_id(self, task_ids: list[str]) -> dict[str, int]:
        """Map task IDs to the numbers of issues that already exist for them."""
        args = ["issue", "list", "--repo", self.repo, "--state", "all", "--limit", "1000", "--json", "number,title"]
        issues = json.loads(self._gh(*args))
        found: dict[str, int] = {}
        for issue in issues:
            for task_id in task_ids:
                if issue["title"].startswith(f"[{task_id}] "):
                    found[task_id] = issue["number"]
        return found

    def create_issue(self, title: str, body: str, labels: list[str], milestone: str) -> int:
        """Create an issue and return its number."""
        args = ["issue", "create", "--repo", self.repo, "--title", title, "--body-file", "-", "--milestone", milestone]
        for label in labels:
            args += ["--label", label]
        url = self._gh(*args, stdin=body).strip()
        return int(url.rstrip("/").rsplit("/", 1)[-1])


def bootstrap(backlog: Backlog, github: GitHub, *, only: str | None, include_done: bool) -> None:
    """Create or update labels, milestones and issues in GitHub."""
    if only in (None, "labels"):
        for label in backlog.labels:
            github.upsert_label(label)
        print(f"labels: {len(backlog.labels)} created or updated")

    if only in (None, "milestones"):
        existing = github.milestone_titles()
        missing = [m for m in backlog.milestones if m["title"] not in existing]
        for milestone in missing:
            github.create_milestone(milestone["title"], f"Days {milestone['days']}. {milestone['description']}")
        print(f"milestones: {len(missing)} created, {len(backlog.milestones) - len(missing)} already present")

    if only in (None, "issues"):
        numbers = github.issue_numbers_by_id([task["id"] for task in backlog.tasks])
        created = 0
        for task in backlog.tasks:
            if task["id"] in numbers or (task["status"] == "done" and not include_done):
                continue
            body = render_issue_body(task, backlog, github.url, numbers)
            milestone = backlog.milestone_by_key[task["milestone"]]["title"]
            numbers[task["id"]] = github.create_issue(issue_title(task), body, task["labels"], milestone)
            created += 1
            print(f"  #{numbers[task['id']]} {issue_title(task)}")
            time.sleep(PAUSE_BETWEEN_ISSUES_S)
        print(f"issues: {created} created")


def dry_run(backlog: Backlog, repo: str | None, *, include_done: bool) -> None:
    """Print what ``bootstrap`` would create, without calling GitHub."""
    print(f"labels ({len(backlog.labels)}): {', '.join(label['name'] for label in backlog.labels)}")
    print(f"milestones ({len(backlog.milestones)}):")
    for milestone in backlog.milestones:
        print(f"  {milestone['title']} (days {milestone['days']})")
    selected = [task for task in backlog.tasks if include_done or task["status"] != "done"]
    print(f"issues ({len(selected)} of {len(backlog.tasks)} tasks; target {repo or '<current gh repository>'}):")
    for task in selected:
        print(f"  {issue_title(task)}  [{', '.join(task['labels'])}]")


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", help="Target repository as OWNER/NAME. Default: the repository gh finds here.")
    parser.add_argument("--backlog", type=Path, default=DEFAULT_BACKLOG, help="Backlog file to read.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be created; make no GitHub calls.")
    parser.add_argument("--only", choices=["labels", "milestones", "issues"], help="Create only this kind of item.")
    parser.add_argument("--include-done", action="store_true", help="Also create issues for tasks marked done.")
    parser.add_argument("--show", metavar="ID", help="Print the rendered issue body for one task and exit.")
    parser.add_argument("--table", action="store_true", help="Print a Markdown table of all tasks and exit.")
    args = parser.parse_args(argv)

    try:
        backlog = load_backlog(args.backlog)
        if args.table:
            print(markdown_table(backlog))
            return 0
        if args.show:
            task = next((t for t in backlog.tasks if t["id"] == args.show), None)
            if task is None:
                print(f"no task with id {args.show}", file=sys.stderr)
                return 2
            print(render_issue_body(task, backlog, f"https://github.com/{args.repo or 'OWNER/REPO'}"))
            return 0
        if args.dry_run:
            dry_run(backlog, args.repo, include_done=args.include_done)
            return 0
        bootstrap(backlog, GitHub(args.repo), only=args.only, include_done=args.include_done)
    except (BacklogError, GhError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
