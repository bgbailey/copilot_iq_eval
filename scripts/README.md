# Scripts

Repository tooling. Run scripts with `uv run python scripts/<name>.py` so they use the project's environment.

| Script | Purpose | Added by |
|---|---|---|
| [`bootstrap_github.py`](bootstrap_github.py) | Creates the GitHub labels, phase milestones and one issue per plan task from `docs/backlog/tasks.yaml`. Idempotent; `--dry-run` makes no GitHub calls. | Bootstrap |
| `build_agent.py` | Regenerates the declarative agent's instructions from `agents/policy/routing-policy.md` and fails CI if they drift. | P4.1 |
| `inject_*.py` | Scripted regression injections for the demo, each with an automatic revert. | P10.2 |
