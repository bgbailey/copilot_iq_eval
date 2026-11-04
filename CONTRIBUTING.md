# Contributing

Thank you for helping build the Copilot × Fabric IQ evaluation harness. This guide explains how work is organised, how to set up a development environment, and the rules every change must follow.

- [Contributor License Agreement](#contributor-license-agreement)
- [How this repository is built](#how-this-repository-is-built)
- [Development setup](#development-setup)
- [Definition of done](#definition-of-done)
- [Pull requests](#pull-requests)
- [Golden-set changes](#golden-set-changes)
- [Evaluator changes](#evaluator-changes)
- [Decisions and contracts](#decisions-and-contracts)
- [Security and data rules](#security-and-data-rules)
- [Working with GitHub Copilot](#working-with-github-copilot)

## Contributor License Agreement

This project welcomes contributions and suggestions. Most contributions require you to agree to a Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us the rights to use your contribution. For details, visit <https://cla.opensource.microsoft.com>.

When you submit a pull request, a CLA bot will automatically determine whether you need to provide a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/). For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## How this repository is built

The repository is built incrementally from the implementation plan in [docs/PLAN.md](docs/PLAN.md). The plan is the specification: section numbers in issues, docstrings and comments (for example *PLAN §9.6.1*) refer to it.

1. **One issue per task.** Every task in PLAN §8 (`P0.1` … `P10.3`, plus the Phase 0 spikes `S1`–`S6`) is an issue created from [docs/backlog/tasks.yaml](docs/backlog/tasks.yaml) by [scripts/bootstrap_github.py](scripts/bootstrap_github.py). Each issue carries the task's goal, its Copilot prompt where the plan provides one, and its acceptance criteria as a checklist.
2. **Milestones are phases.** Phase 0 de-risks the preview services; nothing that depends on an unconfirmed API contract is built before its spike is recorded as an ADR.
3. **`[MANUAL]` tasks need a person in the tenant** — licences, admin settings, consent and UI-only configuration. They are labelled `type:manual`.

If you want to change the plan itself, open an issue first: the plan, the backlog file and the open issues must stay in step.

## Development setup

You need [Python 3.12](https://www.python.org/downloads/), [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git. The [GitHub CLI](https://cli.github.com/) is only needed to bootstrap the backlog.

```bash
uv sync                                # create .venv with runtime and dev dependencies
uv run pre-commit install              # lint, format and secret checks on every commit
uv run evals --help                    # the harness CLI
```

Day-to-day commands (the `Makefile` wraps the same commands for convenience):

| Task | Command |
|---|---|
| Lint | `uv run ruff check` |
| Format | `uv run ruff format` |
| Type-check | `uv run mypy src` |
| Unit tests | `uv run pytest` |
| Validate the golden set and evaluator definitions | `uv run evals validate` |
| Score the sample rows on the local backend | `uv run evals score evals/evaluators/samples/eval-items.jsonl` |
| Everything CI runs | `make check` |

Tests under `tests/unit` must never touch the network or a tenant. Use fakes for every adapter.

## Definition of done

A change is done when (from [.github/copilot-instructions.md](.github/copilot-instructions.md)):

- the acceptance criteria in its issue are met and unit tests are added;
- `uv run ruff check && uv run mypy src && uv run pytest` pass;
- `docs/` is updated when behaviour or contracts change, and new decisions are recorded as ADRs.

## Pull requests

- Branch from `main`; name the branch after the task, for example `p2-5-numeric-scorer`.
- Keep a pull request to one task. Link it with `Closes #<issue>` so the backlog stays accurate.
- Fill in the [pull request template](.github/PULL_REQUEST_TEMPLATE.md), including the plan sections the change implements.
- CI must be green. Changes under `evals/`, `agents/`, `fabric/`, `src/` or `config/` also run the live evaluation gate once it is enabled (see [docs/getting-started.md](docs/getting-started.md#8-enable-the-live-evaluation-workflows)).

## Golden-set changes

The golden set in [evals/golden](evals/golden) is the contract the whole demo is judged against, so it has extra rules:

- **Case IDs are stable and never reused.** Retire a case by deleting it; never recycle its ID.
- **Every key must resolve.** Personas, models, decoys and document decoys must exist in `personas.yaml` and `models.yaml`.
- **Reference DAX uses the business-friendly names** in PLAN §4.2 (`'Date'[Fiscal Year]`, `[Gross Revenue]`, …).
- **Synthetic data only.** No real customer names, people or figures.
- Run `uv run evals validate --strict` before you push. To propose a case without writing YAML, use the *Golden case proposal* issue template.

## Evaluator changes

Every pass or fail comes from an evaluator in [evals/evaluators](evals/evaluators/README.md), and the same evaluator runs on both evaluation backends: Microsoft Foundry Evaluations (the default, [ADR-007](docs/decisions/ADR-007-foundry-evaluations-framework-of-record.md)) and the local backend ([ADR-009](docs/decisions/ADR-009-two-evaluation-backends.md)). No other code scores an answer, and no evaluator may depend on the backend that runs it.

- **Code-based evaluators run as they are, on both backends.** Foundry uploads each file and the local backend executes it the same way. Keep each one a self-contained `grade(sample, item)` file: standard library or the Foundry sandbox packages only, no network, no imports from `copilot_evals`.
- **Declare what you read.** Every row field an evaluator reads must be listed under `reads` in `evaluators.yaml` and exist in the item schema in `eval-definition.yaml`. A new field means changing `EvalItem` and the runner in the same pull request.
- **Can't decide? Raise.** When evidence is incomplete, raise `InconclusiveError` instead of returning a score, so the attempt is INCONCLUSIVE rather than a false failure.
- **The AI judge never sees the expected answer.** Don't map `expected_value`, `expected_table` or `tolerance` into any prompt.
- **Test as the sandbox runs.** Unit tests execute each evaluator file standalone (see `tests/unit/test_evaluators.py`). Run `uv run evals validate --strict` and `uv run evals score evals/evaluators/samples/eval-items.jsonl` before you push.
- **Keep the backends equivalent.** A change to how evaluators are run belongs in both backends, or in the shared definition; `tests/unit/test_local_backend.py` and the parity tests (P2.7) must keep passing.

## Decisions and contracts

- **Never invent an API contract.** Endpoints, scopes, headers and response field names come only from [config/contracts.yaml](config/contracts.yaml), which is filled in from PLAN §9 and the ADRs. If something is missing, add `TODO(spike-Sx)` and stop.
- **Record decisions as ADRs** in [docs/decisions](docs/decisions) using the [template](docs/decisions/adr-template.md). Phase 0 spikes produce ADR-001 to ADR-006.
- **One routing policy.** [agents/policy/routing-policy.md](agents/policy/routing-policy.md) is used verbatim by every layer. Change it only through a pull request so the evaluation gate shows the effect.

## Security and data rules

- Never commit secrets, tokens, token caches, certificates or connection strings. Settings live in `config/settings.toml` (gitignored); secrets live in Azure Key Vault.
- Never commit tenant identifiers: tenant IDs and domains, user principal names, workspace or item IDs, report URLs. Templates such as `{tenant_domain}` are resolved at run time.
- Spike outputs (`spikes/out/`), run outputs (`out/`) and token caches (`.cache/`) are gitignored because they contain tenant data. Summarise findings in an ADR instead.
- Recorded fixtures under `tests/fixtures/` must be sanitised before they are committed.

The pre-commit hooks include a secret scanner, but they are a safety net, not a substitute for these rules.

## Working with GitHub Copilot

The repository is designed to be built with GitHub Copilot — agent mode in VS Code or the Copilot cloud agent assigned to an issue:

- [.github/copilot-instructions.md](.github/copilot-instructions.md) holds the repository-wide rules from PLAN Appendix A.
- [.github/instructions/](.github/instructions) adds path-specific rules for Python, evaluators, the golden set, Fabric assets and agent assets.
- [.github/workflows/copilot-setup-steps.yml](.github/workflows/copilot-setup-steps.yml) prepares the cloud agent's environment (Python 3.12, uv and dependencies).

Review a Copilot pull request exactly as you would any other: check it against the issue's acceptance criteria and the plan section it cites.
