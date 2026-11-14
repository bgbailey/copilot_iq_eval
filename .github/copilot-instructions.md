# Instructions for GitHub Copilot in this repository

## What this repository is

`copilot_iq_eval` (`cfeval`) is an open accelerator that evaluates answers from Microsoft 365 Copilot Chat, Fabric IQ semantic models, Work IQ workplace content, and other agents to business-data questions. A Python harness (`src/cfeval`) asks a golden set of test cases through a pluggable `Target`, collects evidence (citations, Fabric Workspace Monitoring `SemanticModelLogs` query traces, MCP tool traces), scores each answer with deterministic assertions and an optional calibrated judge, and writes local JSONL plus optional Fabric Eventhouse telemetry. `app/` is an optional scorecard for Microsoft Fabric and local preview.

## Layout

- `src/cfeval/` — the Python 3.10+ harness (`cfeval` CLI). `scorers.py` and `stats.py` are standard-library only.
- `src/cfeval/schema.py` — the single source of truth for the seven telemetry tables (`EvalRun`, `EvalQuestion`, `EvalAsk`, `FabricIqQuery`, `EvalScore`, `EvalResult`, `EvalEvent`).
- `src/cfeval/targets/` — pluggable targets (`copilot-chat`, `transcript-import` / `import`, `mcp-agent`, `fabric-data-agent`) and `cfeval.targets` entry-point discovery.
- `tests/` — `unit/`, `contract/`, `e2e_offline/`, `data/` (live tests carry `@pytest.mark.live` and are skipped unless `CFEVAL_LIVE=1`).
- `data/golden/` & `samples/` — synthetic Contoso test sets (`@contoso.com`), star-schema CSVs, and Work IQ documents.
- `config/` — gate policy (`gates.yaml`), personas, and public wording denylist (`wording-denylist.txt`).
- `app/overlay/` — shared React/TypeScript scorecard source. `app/standalone/` — offline Vite preview and `node --test` suites. `app/connectors/evals/` — generated connector entities.
- `docs/` — Diátaxis documentation (`get-started/`, `concepts/`, `how-to/`, `reference/`, `responsible-use/`, `decisions/`, `validation/`). `docs/PLAN.md` records the engineering plan and Microsoft Learn references.

## Rules

1. **Offline only.** Never call Microsoft Graph, Fabric, Power BI, or Microsoft Foundry from tests, CI, or an agent session. Use `--mock`, deterministic fakes, and synthetic fixtures.
2. **Do not invent service contracts.** If a field, endpoint, or permission is not in the repository or in a source listed in `docs/PLAN.md` Section 12 (`docs/reference/platform-status.md`), add `TODO(verify-live)`, add a skipped `@pytest.mark.live` test, and state the assumption in the pull request.
3. **Evidence integrity.** `ERROR` and `INCONCLUSIVE` never become `PASS`. Never replace a missing remote score with a local one. Never use the expected value to choose which number to extract from an answer, and never treat Copilot's follow-up explanation (`Why`) as routing proof (`RoutingEvidence`: `engine+citations`, `engine-only`, `tool_call`, `citations-only`, `unverified`).
4. **Every behaviour change comes with tests.** Scoring changes also add rows to `tests/data/value_cases.jsonl` (or corresponding unit/contract fixtures).
5. **Standard-library scorers.** `src/cfeval/scorers.py` (`< 256 KB`) and `src/cfeval/stats.py` stay standard-library only so Foundry Evaluations can bundle `scorers.py` as a custom code evaluator.
6. **Lazy optional SDK imports.** Import optional SDKs (`msal`, `azure-kusto-data`, `azure-kusto-ingest`, `openai`, `azure-identity`, `azure-ai-projects`, `fabric-data-agent-sdk`) lazily inside functions.
7. **Explicit identity & non-destructive Fabric operations.** Live commands bind explicitly to `CFEVAL_TENANT_ID`, `CFEVAL_OPERATOR_UPN`, and `CFEVAL_TEST_USER_UPN` (`runtime.py`, `auth.py`)—never fall back to `DefaultAzureCredential` or ambient CLI profiles. Setup commands use `.create-merge`, `.create-or-alter`, and `shortcutConflictPolicy=Abort`; never delete workspaces, databases, lakehouses, or semantic models.
8. **Regenerate derived contracts.** After a `src/cfeval/schema.py`, CLI, or config change, regenerate `kql/setup.kql`, `app/overlay/src/eval/generated/contract.ts`, `app/connectors/evals/*.ts`, and `docs/reference/*.md` in the same change.
9. **Additive telemetry schema.** Add new nullable/defaulted columns only; do not rename or retype existing columns.
10. **Synthetic public hygiene & focused PRs.** Use Contoso names (`@contoso.com`) only; never commit tenant IDs, workspace/item GUIDs, UPNs, secrets, or real answers. Describe environments as `"demo tenant"` and `"demo Azure subscription"`. Run `python tools/check_public_wording.py` before finishing. Keep changes focused to one work item per pull request.

## Before you open a pull request

Run the commands in `AGENTS.md` and paste the summary lines into the pull request. State what you could not verify offline.
