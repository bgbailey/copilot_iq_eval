# Configuration

| File | Purpose | Committed? |
|---|---|---|
| [`settings.example.toml`](settings.example.toml) | Template for `settings.toml`: tenant and workspace identifiers, the evaluation backend, model deployments, the Foundry project and the agent. Non-secret. Schema: `src/copilot_evals/config.py`. | Yes |
| `settings.toml` | Your tenant's copy of the template. | **No** (gitignored) |
| [`contracts.yaml`](contracts.yaml) | The API contracts registry: endpoints, scopes, headers and field names, including Microsoft Foundry Evaluations (`foundry_evaluations`) and the Azure OpenAI v1 API (`azure_openai_v1`). Adapters read contracts **only** from here, never from memory. | Yes |
| [`gates.yaml`](gates.yaml) | The gate policy for the `pr` and `nightly` suites (PLAN §9.10), applied to the evaluator results from either backend. | Yes |

## Where things live

- **Settings** (tenant-specific, non-secret): `settings.toml`, including the evaluation backend (`[evaluation] backend = "foundry"` or `"local"`), the model deployments and, on the Foundry path, the Foundry project endpoint.
- **Evaluation logic**: [`evals/evaluators/`](../evals/evaluators/README.md). Every check is an evaluator that runs unchanged on Microsoft Foundry or locally ([choosing a path](../docs/evaluation-paths.md)).
- **Secrets** (token caches, the daemon certificate, the Teams webhook URL): Azure Key Vault. Settings only name them.
- **Contracts** (how Microsoft APIs behave): `contracts.yaml`, each entry marked `documented` (from PLAN §9) or `confirmed` (observed by a Phase 0 spike and recorded in an ADR). Unknowns are `null` with a `TODO(spike-Sx)` marker; code that needs one must stop rather than guess.
