# Documentation

| Document | Read it when |
|---|---|
| [PLAN.md](PLAN.md) | You need the specification. Issues, docstrings and comments cite its sections (for example *PLAN §9.6.1*). |
| [architecture/](architecture/README.md) | You want the big picture: components, who does what, evaluation layers and the life of one attempt. |
| [evaluation-paths.md](evaluation-paths.md) | You are choosing between evaluating with Microsoft Foundry and evaluating locally, or switching between them. |
| [../evals/evaluators/](../evals/evaluators/README.md) | You want to know how every attempt is scored: the evaluators, the AI judge, the dataset row and the two backends that run them. |
| [getting-started.md](getting-started.md) | You are setting up the repository, a development environment or the demo tenant. |
| [deployment.md](deployment.md) | You are deploying the demo environment: app registrations, Azure resources, the Fabric estate and the Work IQ documents. |
| [backlog/](backlog/README.md) | You want to see every task, or create the GitHub issues. |
| [decisions/](decisions/README.md) | You are recording or looking up an architecture decision, including Phase 0 spike results. |
| [research/](research) | You want the evidence behind the design: what Microsoft documents (as of 3 November 2026) and what it doesn't. |
| [runbook.md](runbook.md) | You are preparing or giving the demo. |
| [open-source-release.md](open-source-release.md) | The repository is about to become public. |

## The plan is the source of truth

[PLAN.md](PLAN.md) is the specification (version 1.3, 3 November 2026; *Changes in 1.3*, *1.2* and *1.1* at the top list what changed from 1.0). When the design changes:

1. record the decision as an ADR in [decisions/](decisions/README.md);
2. update the plan section it affects, and [backlog/tasks.yaml](backlog/tasks.yaml) if tasks change;
3. update [config/contracts.yaml](../config/contracts.yaml) if an API contract changes.

## Research notes

| Note | Scope |
|---|---|
| [copilot-fabric-iq-eval-harness-report.md](research/copilot-fabric-iq-eval-harness-report.md) | What each Copilot surface and Fabric component exposes for automated routing and answer evaluation; telemetry; ground truth; tenant prerequisites. |
| [copilot-fabric-ai-eval-framework-report.md](research/copilot-fabric-ai-eval-framework-report.md) | Evaluation frameworks compared: Microsoft Foundry, Copilot Studio, the Fabric data agent SDK and open-source runners; NL-to-query methodology. |
