# Backlog

Every task in the implementation plan lives in [`tasks.yaml`](tasks.yaml) as data: the plan's own words for each task's goal and Copilot prompt, plus labels, a phase milestone, acceptance criteria and suggested dependencies. [`scripts/bootstrap_github.py`](../../scripts/bootstrap_github.py) turns it into GitHub labels, milestones and issues (PLAN §0 step 3).

## Create the issues

```bash
gh auth login                                                     # once
uv run python scripts/bootstrap_github.py --dry-run               # preview: no GitHub calls
uv run python scripts/bootstrap_github.py --dry-run --show P2.5   # see one issue body
uv run python scripts/bootstrap_github.py --repo <owner>/copilot-fabriciq-evals
```

The script is idempotent. Labels are created or updated; milestones and issues are created only when missing, and issues are recognised by their `[<id>]` title prefix. Tasks marked `done` are skipped.

## How a task becomes an issue

| Backlog field | Issue |
|---|---|
| `id`, `title` | Title `[P2.5] Scorers: ...` |
| `milestone` | Milestone *Phase N — name* |
| `labels` | `type:task`, `type:spike` or `type:manual`; `copilot-ready` when the plan provides a Copilot prompt; `layer:*` and `area:*` |
| `description` | **Goal**, verbatim from the PLAN §8 task table |
| `delivered` | **Already delivered by the repository bootstrap** (for `partial` tasks) |
| `prompt` | **Copilot prompt**, verbatim from the plan |
| `acceptance` | **Acceptance criteria** checklist, marked as from the plan or derived |
| `depends_on` | **Depends on (suggested order)**, linked to the issues once they exist |

Assign `copilot-ready` issues to GitHub Copilot, or open them in VS Code agent mode. `type:manual` issues need a person signed in to the demo tenant.

## Additions to the plan

Two tasks were added during the repository bootstrap because the plan describes their output but no task builds it (see [ADR-000](../decisions/ADR-000-repository-bootstrap.md)). Spike S7 and task P2.7 come from plan version 1.1 ([ADR-007](../decisions/ADR-007-foundry-evaluations-framework-of-record.md)), task P2.8 and tenant item T19 from version 1.2 ([ADR-009](../decisions/ADR-009-two-evaluation-backends.md)), and spike S8, tasks P1.9 and P1.10 and tenant items T20 and T21 from version 1.3 ([ADR-010](../decisions/ADR-010-joint-work-iq-fabric-iq-evaluation.md)).

- **P0.2** Infrastructure as code (`infra/` in PLAN §7).
- **P1.8** Author the full golden set (48 cases in PLAN §5.2).

## All tasks

| ID | Task | Phase | Executor | Status |
|---|---|---|---|---|
| T1-T21 | Tenant prerequisites and setup checklist | 0 | manual | todo |
| P0.1 | Spike scripts for S1, S2, S3, S6, S7 and S8 | 0 | copilot | partial |
| S1 | Does the Copilot Chat API trigger Fabric IQ / Power BI answering? | 0 | manual | todo |
| S2 | What does a Copilot-issued query look like in the engine log, and how fast is it ingested? | 0 | manual | todo |
| S3 | Can the Agent Evaluations CLI run headless as different personas, and what does its JSON contain? | 0 | manual | todo |
| S4 | Can Copilot Studio evaluation test an agent that uses the Fabric IQ MCP or data agent tool? | 0 | manual | todo |
| S5 | Do Purview audit and Interaction Export show Fabric usage per access point? | 0 | manual | todo |
| S6 | Fabric IQ MCP from our own client: tool contract and argument names | 0 | manual | todo |
| S7 | Does our Foundry project run the evaluation design end to end? | 0 | manual | todo |
| S8 | Which surfaces answer joint Work IQ + Fabric IQ questions, and how well? | 0 | manual | todo |
| P0.2 | Infrastructure as code: Entra app registrations and Azure resources | 0 | copilot | partial |
| P1.1 | Create workspaces, enable monitoring and grant access | 1 | copilot | partial |
| P1.2 | Notebook nb_01_generate_data: seeded synthetic data | 1 | copilot | partial |
| P1.3 | Notebook nb_02_build_models: Direct Lake models, measures and RLS | 1 | copilot | partial |
| P1.4 | Prep data for AI, endorsement, reports and the document decoy | 1 | manual | todo |
| P1.5 | Connect workspaces to Fabric Git integration | 1 | copilot | todo |
| P1.6 | Engine-log KQL: semantic_model_logs.kql and heartbeat.kql | 1 | copilot | done |
| P1.7 | Notebook nb_03_validate_and_snapshot: validation and expected snapshot per persona | 1 | copilot | partial |
| P1.8 | Author the full golden set (48 cases) | 1 | copilot | todo |
| P1.9 | `evals deploy fabric`: deploy and validate the Fabric estate | 1 | copilot | partial |
| P1.10 | Work IQ content pack and `evals deploy workiq` | 1 | copilot | partial |
| P2.1 | Python scaffold: uv, src layout, Typer CLI, ruff, mypy, pytest, pre-commit | 2 | copilot | partial |
| P2.2 | Schemas and `evals validate`, including ItemId resolution | 2 | copilot | partial |
| P2.3 | Auth: persona tokens, Key Vault token cache, app-only credential | 2 | copilot | todo |
| P2.4 | Ground truth: executeQueries, refresh time and composite resolvers | 2 | copilot | todo |
| P2.5 | Evaluators: value_match, routing, decoys, citations and the AI judge | 2 | copilot | partial |
| P2.6 | Runner and gate: persona lanes, scoring on either backend, JUnit and summary | 2 | copilot | todo |
| P2.7 | Foundry backend: evaluator sync, dataset upload, runs and results | 2 | copilot | todo |
| P2.8 | Local backend: Azure OpenAI judge client and parity | 2 | copilot | partial |
| P3.1 | Fabric IQ MCP client wrapper | 3 | copilot | todo |
| P3.2 | Reference orchestrator loop: Azure OpenAI Responses API with MCP tools | 3 | copilot | todo |
| P3.3 | Tool-trace capture with semantic-model ID and DAX | 3 | copilot | todo |
| P3.4 | Score L1 routing from the tool trace and cross-check engine logs | 3 | copilot | todo |
| P4.1 | Declarative agent project: manifest v1.9, Fabric capability, routing skill | 4 | copilot | todo |
| P4.2 | Provision and share the declarative agent | 4 | manual | todo |
| P4.3 | Agent Evaluations CLI adapter, one run per attempt | 4 | copilot | todo |
| P4.4 | Agent variants v1 and v2 for the routing A/B demo | 4 | copilot | todo |
| P5.1 | Kusto client for the monitoring Eventhouses | 5 | copilot | todo |
| P5.2 | Per-attempt engine-log correlation with heartbeat completeness | 5 | copilot | todo |
| P5.3 | Normalise attributions, citations and tool traces into Evidence | 5 | copilot | todo |
| P5.4 | ApplicationName signatures from S2 in contracts.yaml | 5 | copilot | todo |
| P6.1 | Copilot Chat API adapter (beta) | 6 | copilot | todo |
| P6.2 | Interaction Export harvester for tester sessions | 6 | copilot | todo |
| P6.3 | Purview audit evidence | 6 | copilot | todo |
| P7.1 | Copilot Studio adapter (only if ADR-004 is positive) | 7 | copilot | todo |
| P7.2 | Fabric data agent adapter and evaluate_data_agent notebook | 7 | copilot | todo |
| P8.1 | OneLake results sink | 8 | copilot | todo |
| P8.2 | Power BI scorecard: Copilot × Fabric IQ Eval Scorecard | 8 | copilot | todo |
| P8.3 | Teams alerts when a gate fails | 8 | copilot | todo |
| P9.1 | CI/CD workflows | 9 | copilot | partial |
| P9.2 | Self-hosted runner VM | 9 | manual | partial |
| P9.3 | Gate policy and baseline handling | 9 | copilot | partial |
| P10.1 | Judge calibration | 10 | copilot | todo |
| P10.2 | Regression injection scripts with automatic revert | 10 | copilot | todo |
| P10.3 | Demo runbook | 10 | copilot | todo |

Regenerate this table with `uv run python scripts/bootstrap_github.py --table` when `tasks.yaml` changes.
