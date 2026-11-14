---
applyTo: "src/**/*.py,tests/**/*.py,tools/**/*.py"
---

# Python conventions (`cfeval`)

- Target Python 3.10 and later (`3.10`–`3.13`). Format and lint with `ruff` (`line-length = 120`).
- Add type hints on every function you add or change. `mypy src/cfeval` runs in CI.
- Keep `src/cfeval/scorers.py` (`< 256 KB`) and `src/cfeval/stats.py` standard-library only so Foundry Evaluations can upload `scorers.py` as a custom code evaluator without third-party wheels.
- Import optional SDKs (`msal`, `azure-kusto-data`, `azure-kusto-ingest`, `openai`, `azure-identity`, `azure-ai-projects`, `fabric-data-agent-sdk`) lazily inside the function that needs them.
- Use `logging.getLogger(__name__)`, not `print`, in `src/cfeval/` library code. User-facing console output goes through `src/cfeval/cli.py` only.
- Catch specific exceptions (`ValueError`, `OSError`, `requests.RequestException`, domain errors). Do not add `except Exception` unless the handler records the failure as `ERROR` evidence or re-raises at a CLI boundary.
- Extend `RunConfig` (`src/cfeval/interfaces.py`) for new run options rather than adding positional/keyword sprawl to `EvalHarness.__init__` or `build_harness`.
- Tests use `pytest`, the simulated clock (`src/cfeval/clock.py`), and deterministic fakes—no network calls, no `time.sleep`, and no dependence on wall-clock time. Scoring changes also add cases to `tests/data/value_cases.jsonl` or `tests/unit/`.
- Tests that touch live Microsoft endpoints must carry `@pytest.mark.live` (skipped unless `CFEVAL_LIVE=1`) and load explicit credentials via `Settings.load()`.
