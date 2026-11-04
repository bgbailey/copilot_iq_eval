---
applyTo: "src/**/*.py,tests/**/*.py,scripts/**/*.py,spikes/**/*.py"
---

# Python code in this repository

These rules add detail to `.github/copilot-instructions.md`; where they overlap, both apply.

- The package never scores an answer. Every check is an evaluator in `evals/evaluators/`, run by Microsoft Foundry Evaluations or by the local backend (ADR-007, ADR-009); the package drives surfaces, gathers evidence, hands rows to the backend through `copilot_evals.evaluation.backend.EvaluationBackend` and applies the gate to the results. The local backend runs the evaluators but must never add evaluation logic of its own.
- Start every module with a docstring that says what it is for and which plan section it implements, for example "PLAN §9.6.1". Use Google-style `Args:`, `Returns:` and `Raises:` sections on public functions. Comment the *why*; the code shows the *what*.
- Use the contracts in `copilot_evals.schemas` at module boundaries instead of raw dicts. Add a model there when a new record crosses a module boundary.
- Compare numbers as `decimal.Decimal`, never `float`. Timestamps are timezone-aware UTC (`datetime.UTC`); ruff's DTZ rules reject naive datetimes.
- Put every external call in an adapter package (`auth`, `ground_truth`, `targets`, `evidence`, `sinks`) behind a protocol, with explicit timeouts, tenacity retries that honour `Retry-After`, and structured JSON logs carrying `attempt_id`, `case_id`, `persona` and `surface`.
- Read endpoints, scopes, headers and field names from `config/contracts.yaml`; read settings with `copilot_evals.config.load_settings()`. Never log tokens or write them to disk outside the Key Vault-backed cache.
- Missing or incomplete evidence must reach the evaluators as data (`evidence_complete: false`, `status`), so the evaluators raise and the gate reports INCONCLUSIVE, never FAIL. Report transport errors through `AttemptResult.status`; don't raise out of an adapter.
- Tests: `tests/unit` uses fakes and never touches the network; contract tests replay sanitised fixtures from `tests/fixtures/` and are marked `@pytest.mark.contract`. Name tests after the behaviour they prove, for example `test_rejects_naive_timestamps`.
- New CLI commands go in `copilot_evals/cli.py` (or a module it imports) and use Typer's `Annotated` style.
- Before you finish: `uv run ruff check && uv run mypy src && uv run pytest`.
