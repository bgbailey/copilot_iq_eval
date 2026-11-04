# Getting started

This guide takes the repository from a folder on your machine to a backlog that GitHub Copilot can work through, and then to a live evaluation pipeline, scored in Microsoft Foundry or locally. Steps 1 to 4 need no tenant.

1. [Create the GitHub repository](#1-create-the-github-repository)
2. [Create the backlog issues](#2-create-the-backlog-issues)
3. [Set up a development environment](#3-set-up-a-development-environment)
4. [Configure settings](#4-configure-settings)
5. [Prepare and deploy the demo tenant](#5-prepare-and-deploy-the-demo-tenant)
6. [Choose and prepare an evaluation path](#6-choose-and-prepare-an-evaluation-path)
7. [Work an issue with GitHub Copilot](#7-work-an-issue-with-github-copilot)
8. [Enable the live evaluation workflows](#8-enable-the-live-evaluation-workflows)

## 1. Create the GitHub repository

The repository starts **private**. From the repository folder:

```bash
uv lock                                   # pin dependency versions in uv.lock (recommended before the first commit)
git init -b main
git add .
git commit -m "Bootstrap repository from the implementation plan"
gh repo create <owner>/copilot-fabriciq-evals --private --source . --remote origin --push
```

Then, in the repository settings on GitHub:

- **About**: add a description and topics, for example `microsoft-365-copilot`, `microsoft-fabric`, `power-bi`, `llm-evaluation`.
- **Branch protection** for `main`: require a pull request and the CI status check `Lint, type-check, test, validate`.
- **Code security**: turn on Dependabot alerts and security updates, and secret scanning with push protection where your plan includes it.
- **Copilot**: make sure the Copilot cloud agent is enabled for the repository if you want to assign issues to it.
- **CODEOWNERS**: replace `@OWNER` in [`.github/CODEOWNERS`](../.github/CODEOWNERS) and uncomment the rules.

> Before the repository becomes public, work through [open-source-release.md](open-source-release.md).

## 2. Create the backlog issues

Every task in the plan is in [`docs/backlog/tasks.yaml`](backlog/tasks.yaml). One command turns it into labels, one milestone per phase, and one issue per task:

```bash
gh auth login
uv run python scripts/bootstrap_github.py --dry-run             # preview, no GitHub calls
uv run python scripts/bootstrap_github.py --repo <owner>/copilot-fabriciq-evals
```

Re-running it is safe: it creates only what is missing. See [backlog/README.md](backlog/README.md) for how fields map to issues.

## 3. Set up a development environment

Install [Python 3.12](https://www.python.org/downloads/), [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git, then:

```bash
uv sync                       # .venv with runtime and dev dependencies
uv run pre-commit install     # ruff, mypy, secret scanning and file hygiene on every commit
make check                    # ruff, mypy --strict, pytest, golden-set and evaluator definition checks
```

On Windows without `make`, run the commands in the [Makefile](../Makefile) directly; each target is a plain `uv run ...` command.

VS Code users get the recommended extensions (Python, Ruff, Mypy, GitHub Copilot Chat, YAML, TOML, Jupyter, Microsoft 365 Agents Toolkit, Mermaid preview) from [`.vscode/extensions.json`](../.vscode/extensions.json).

## 4. Configure settings

```bash
cp config/settings.example.toml config/settings.toml
```

Fill in the tenant, workspace, evaluation backend, model and agent values. The file is gitignored and holds no secrets: token caches, the daemon certificate and the Teams webhook URL live in Azure Key Vault, and the settings file only names them. Point the harness at another file with the `COPILOT_EVALS_SETTINGS` environment variable. The schema, with the plan's defaults, is in [`src/copilot_evals/config.py`](../src/copilot_evals/config.py).

## 5. Prepare and deploy the demo tenant

Work through the `[T1-T21] Tenant prerequisites and setup checklist` issue, which mirrors [PLAN §6](PLAN.md#6-tenant-prerequisites-and-setup-checklist), then follow [deployment.md](deployment.md): it creates the app registrations and Azure resources from [`infra/`](../infra/README.md), and deploys the Fabric estate and the Work IQ documents with `evals deploy`. The checklist covers:

- **Licences**: Microsoft 365 Copilot for the three personas and the builder; Power BI Pro if the capacity is smaller than F64.
- **Capacity and Azure**: a Fabric capacity (F2 or larger, F8 recommended for nightly runs); a model deployment, plus a Foundry project on the Foundry path (step 6); Key Vault and a runner VM.
- **Tenant settings**: Fabric data in Microsoft 365 Copilot, sharing Fabric data with Microsoft 365 services, the Execute Queries REST API, service principals for Fabric APIs, Purview audit.
- **Identities** ([PLAN §11](PLAN.md#11-identity-and-token-strategy)): the `exec`, `east` and `noaccess` personas with MFA registered; the `copilot-eval-public`, `copilot-eval-setup`, `copilot-eval-daemon` and `copilot-eval-ci` app registrations with admin consent; a GitHub OIDC federated credential. [`infra/entra/`](../infra/README.md) scripts them.
- **Work IQ content**: two SharePoint sites with the personas as members (T20), and Work IQ enabled if you want spike S8's Work IQ API surface (T21).

Then run the Phase 0 spikes ([spikes/README.md](../spikes/README.md)). Each spike's result is an ADR, and confirmed values replace the `TODO(spike-Sx)` markers in [`config/contracts.yaml`](../config/contracts.yaml).

## 6. Choose and prepare an evaluation path

The same evaluators in [`evals/evaluators/`](../evals/evaluators/README.md) run on either of two backends ([ADR-009](decisions/ADR-009-two-evaluation-backends.md)). [Choosing an evaluation path](evaluation-paths.md) compares them. Set your choice under `[evaluation]` in `config/settings.toml` (`backend = "foundry"` or `"local"`) and, for the live workflows, in the repository variable `EVALS_BACKEND`.

You can try the evaluators before you prepare either path. This scores seven sample attempts on the local backend, with no Azure resources:

```bash
uv run evals score evals/evaluators/samples/eval-items.jsonl
```

### 6.1 Model deployment (both paths)

The L1 reference orchestrator needs a chat model on either path, and the local backend's AI judge uses the same resource.

1. **Deployment**: in an Azure OpenAI or Microsoft Foundry resource, deploy a GPT model that supports chat completion, for example `gpt-5-mini`. Give it enough tokens-per-minute quota for a nightly run. [`infra/azure`](../infra/README.md) deploys `gpt-5-mini` for you.
2. **Access** (tenant item T19): the builder and the runner's GitHub OIDC identity need **Foundry User** on a Foundry resource, or **Cognitive Services OpenAI User** on an Azure OpenAI resource, to call it with Microsoft Entra ID. `infra/azure` assigns the right one for the resource kind.
3. **Settings**: set `[azure_openai] endpoint` to the resource's v1 address, `https://<resource>.openai.azure.com/openai/v1/`, and the model names.

### 6.2 Foundry path (`backend = "foundry"`)

Microsoft Foundry Evaluations runs the evaluators and keeps every verdict, with a report page per run ([ADR-007](decisions/ADR-007-foundry-evaluations-framework-of-record.md)).

1. **Project**: create a Foundry project in a region that supports batch evaluations ([region list](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-regions-limits-virtual-network)). `infra/azure/deploy.sh` creates one with the default `--kind AIServices`.
2. **Judge model**: deploy the judge model in the project, or reuse the deployment from 6.1 if it lives in the same Foundry resource. It serves the AI judge and the expected-blind extraction step. A run with too little capacity stays in *Running* while the service retries.
3. **Access** (tenant item T18): assign the **Foundry User** role (formerly *Azure AI User*) to the builder and to the runner's GitHub OIDC identity at the **Foundry account** scope. A project-only assignment can't call the judge deployment during a run.
4. **Settings**: set `[foundry] endpoint` and `judge_deployment` in `config/settings.toml`.
5. **Spike S7**: run `uv run python spikes/s7_foundry_eval.py` to register the evaluators under their content-addressed names and score the seven sample rows in Foundry. Record the findings as ADR-008 and update `foundry_evaluations` in [`config/contracts.yaml`](../config/contracts.yaml).

After task P2.7, `uv run evals foundry sync` registers the evaluators under content-addressed names. The live workflows run it before every evaluation on this path, so you rarely need it by hand. Open **Evaluation** in the Foundry portal to see the evaluator catalog and every run's report page.

### 6.3 Local path (`backend = "local"`)

The harness runs the evaluators itself, on the GitHub Actions runner or your machine. No Foundry project is needed.

1. **AI judge**: the local backend calls the judge model from 6.1 (`[azure_openai] judge_model`). Without it, the AI judge's results are INCONCLUSIVE and every other evaluator still runs. The Azure OpenAI judge client is built by task P2.8.
2. **Parallelism**: `[azure_openai] judge_max_workers` sets how many rows are scored at once; raise it if a nightly run is slow and your quota allows it.
3. **Where verdicts live**: each run writes `evaluator_results.jsonl` and `evaluation_run.json` to its output folder; the live workflows upload them as artifacts and publish them to the Lakehouse.

## 7. Work an issue with GitHub Copilot

- **Cloud agent**: assign a `copilot-ready` issue to Copilot. It works in its own environment (prepared by [`copilot-setup-steps.yml`](../.github/workflows/copilot-setup-steps.yml)) and opens a pull request for you to review.
- **Agent mode in VS Code**: open the issue, paste its Copilot prompt into Copilot Chat in agent mode, and iterate locally.

In both cases Copilot reads [`.github/copilot-instructions.md`](../.github/copilot-instructions.md) and the path-specific files in [`.github/instructions/`](../.github/instructions). Review every pull request against the issue's acceptance criteria and the plan section it cites. The definition of done is:

```bash
uv run ruff check && uv run mypy src && uv run pytest
```

Issues labelled `type:manual` need a person signed in to the demo tenant.

## 8. Enable the live evaluation workflows

[`pr-gate.yml`](../.github/workflows/pr-gate.yml), [`nightly.yml`](../.github/workflows/nightly.yml) and [`reconcile.yml`](../.github/workflows/reconcile.yml) are wired as in PLAN §10 but stay disabled until you turn them on, because they need a tenant, a self-hosted runner and harness commands that later phases add. When P2.3, P2.6, P8.1, P9.2 and the backend you chose (P2.7 for Foundry, P2.8 for local) are done:

1. **Runner**: deploy the VM with `infra/azure/deploy.sh --runner` and register it with `infra/azure/register-runner.sh`: labels `self-hosted` and `copilot-evals`, uv and Node 24 installed, and a managed identity that can read the Key Vault.
2. **Environment**: create a GitHub environment named `eval-demo` with the variables `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID`. Azure sign-in uses OIDC federation, so no client secret is stored in GitHub. The same identity needs the model role from step 6 (Foundry User, or Cognitive Services OpenAI User on an Azure OpenAI resource); `infra/azure` assigns it when you pass `--ci-principal-id`.
3. **Backend**: set the repository variable `EVALS_BACKEND` to `foundry` (the default) or `local`.
4. **Dry run**: run each workflow once with *Run workflow* (`workflow_dispatch`) after setting the variable below, and check the job summary.
5. **Switch on**: set the repository variable `EVALS_LIVE_ENABLED` to `true`.
6. **Gate**: make the `eval-l0-l1` check (workflow `pr-gate`) a required status check on `main`.

Before production use, pin every action to a full commit SHA (PLAN §10).
