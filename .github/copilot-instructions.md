# Copilot instructions — copilot-fabriciq-evals

## What this repo is
An automated evaluation harness proving that Microsoft 365 Copilot surfaces route business questions to the
intended Power BI semantic model (via Fabric IQ) and return the expected value, consistently, per persona.
Read docs/PLAN.md before any task. Section numbers in issues refer to that plan.

## Non-negotiables
- Never invent API endpoints, scopes, headers or response fields. Use only config/contracts.yaml (filled from
  docs/PLAN.md §9 and docs/decisions/ADR-*.md). If something is missing, add a TODO(spike-Sx) and stop.
- Verdicts come only from the evaluators in evals/evaluators/, run by Microsoft Foundry Evaluations (the default
  backend) or by the local backend (ADR-007, ADR-009). Never add scoring logic anywhere else, and never make an
  evaluator depend on the backend that runs it. Code-based evaluators are self-contained grade() files (standard
  library and the Foundry sandbox packages only, no network). The AI judge (prompt-based evaluators) is only for
  behaviour classification and expected-blind value extraction, and never sees the expected value.
- Never commit secrets, tokens, token caches or tenant-specific IDs. Settings come from config/settings.toml
  (gitignored) and Key Vault. Use synthetic data only; no customer data or names.
- All time values are UTC (datetime with tzinfo). All numeric comparisons use decimal.Decimal.
- Every external call goes through an adapter with timeouts, retries (tenacity, honour Retry-After) and
  structured JSON logging (attempt_id, case_id, persona, surface). Missing evidence => the evaluator raises, so the
  attempt is INCONCLUSIVE, never FAIL.

## Stack and conventions
- Python 3.12, uv, src/ layout, Typer CLI `evals`, pydantic v2 models in src/copilot_evals/schemas.py,
  httpx (async), msal, azure-identity, azure-keyvault-secrets, azure-kusto-data, azure-ai-projects, mcp, openai,
  deltalake, pandas.
- ruff (line length 120), mypy --strict on src/, pytest with fakes for every adapter; tests/unit must not touch the network.
- Contract tests replay recorded fixtures under tests/fixtures/; re-record only via `evals fixtures record`.
- Evaluator definitions live in evals/evaluators/ (evaluators.yaml, eval-definition.yaml); `evals validate` checks
  them offline, `evals foundry sync` registers them in Foundry and `evals score` runs them locally. Unit-test every
  evaluator by executing its file as the sandbox does.
- Fabric notebooks: PySpark, parameter cell first, idempotent, no hard-coded workspace IDs.
- Keep agents/policy/routing-policy.md as the single routing policy; scripts/build_agent.py regenerates agent
  instructions and fails CI on drift.

## Definition of done for any task
- Acceptance criteria in the issue are met; unit tests added; `uv run ruff check && uv run mypy src && uv run pytest` pass.
- docs/ updated when behaviour or contracts change; new decisions recorded as ADRs.
