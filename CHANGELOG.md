# Changelog

All notable changes to this project are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **A deployable demo environment, and joint Work IQ + Fabric IQ questions** (implementation plan version 1.3; [ADR-010](docs/decisions/ADR-010-joint-work-iq-fabric-iq-evaluation.md); [docs/deployment.md](docs/deployment.md)).
  - `evals deploy fabric`: creates or finds the workspaces, lakehouses and workspace monitoring, imports and runs three notebooks, makes the personas Viewers with Read and Build on their models, and downloads an expected-value snapshot. Idempotent, with `--dry-run` and `--no-run`; package `copilot_evals.setup` (standard-library REST client with retries and long-running operations, Fabric, Power BI, OneLake and Graph clients), tested end to end against an in-memory fake tenant.
  - Fabric notebooks, built from reviewable Python sources by `scripts/build_notebooks.py`: nb_01 generates the synthetic data with FY2025 figures calibrated to the cent; nb_02 builds the four Direct Lake models (friendly names, relationships, measures with descriptions, RLS roles and members) with semantic-link-labs; nb_03 checks the calibrated figures as each persona and snapshots every golden case. A unit test checks every golden-set DAX reference against the model definitions.
  - The Work IQ content pack: three synthetic documents (approved revenue targets, service-level objectives and the draft decoy) built by `scripts/build_workiq_documents.py` from `workiq/content.yaml` and the facts in `evals/golden/models.yaml`, and `evals deploy workiq` to upload them to SharePoint.
  - Joint cases JNT-001 to JNT-004, the `work_source_match` evaluator, `expect.work_sources` and `expect.work_facts`, and `work_sources` / `expected_facts` in the evaluation row; a seventh sample row.
  - Infrastructure as code: `infra/entra/New-EvalAppRegistrations.ps1` (four app registrations, GitHub OIDC, daemon certificate in Key Vault) and `infra/azure` (Bicep for the Foundry or Azure OpenAI resource, project, `gpt-5-mini`, Key Vault and the optional runner VM; `deploy.sh`, `register-runner.sh`).
  - Phase 0 spike scripts S1, S2, S3, S6, S7 and the new S8 (which surfaces answer joint questions; ADR-011 pending).
  - Settings `[fabric] capacity`, lakehouse names, `enable_monitoring` and `notebook_timeout_s`; `[workiq.sites]`; `[apps] setup_client_id`; persona `rls_role` and `regions`. Contracts `work_iq_api`, `graph_sharepoint_files`, `fabric_rest`, `power_bi_dataset_users` and `semantic_link_labs`. Optional dependency groups `setup` and `spikes`.
- **Two evaluation paths: with Microsoft Foundry or without it** ([ADR-009](docs/decisions/ADR-009-two-evaluation-backends.md); implementation plan version 1.2). The evaluators are written once and run on either backend: Microsoft Foundry Evaluations (the default) or a local backend that runs the same files in the harness process, with no Foundry project.
  - Added the backend-neutral package `copilot_evals.evaluation`: the `EvaluationBackend` protocol, the local backend, the attempt verdict rule and the evaluation dataset files. The definitions checker moved here from `copilot_evals.foundry`.
  - Added `evals score`, which scores collected rows and explains every result, and six sample rows in `evals/evaluators/samples/`. CI scores them on the local backend on every push, with no Azure resources.
  - Both backends record the same content-addressed evaluator versions (`cfiq_<key>_<sha8>`), so their results can be compared directly.
  - Added `[evaluation]` and `[azure_openai]` settings, the `EVALS_BACKEND` workflow variable, the `azure_openai_v1` contract, task P2.8 (the local backend's Azure OpenAI judge client) and tenant item T19 (Cognitive Services OpenAI User).
  - Added [docs/evaluation-paths.md](docs/evaluation-paths.md), which compares the two paths and explains how to switch.
- Repository bootstrap from the implementation plan (docs/PLAN.md, version 1.0, 3 November 2026):
  - plan, research notes, reference architecture and documentation set; ADR template and ADR-000;
  - GitHub Copilot instructions (PLAN Appendix A) and path-specific instructions; issue forms; pull request template;
  - CI workflow (ruff, mypy --strict, pytest, golden-set validation); PR gate, nightly and reconcile workflows wired and disabled; Copilot cloud agent setup steps;
  - Python package `copilot_evals` with the data contracts (`schemas.py`), settings loader, surface-adapter protocol and the `evals validate` command, with unit tests;
  - seed golden set (10 cases), personas and models; routing policy; gate policy; API contracts registry; engine-log KQL;
  - backlog of every plan task (`docs/backlog/tasks.yaml`) and the GitHub bootstrap script.

### Changed

- The model-access role depends on the resource kind: Foundry User on a Foundry resource, Cognitive Services OpenAI User on an Azure OpenAI resource (PLAN §6 T19).
- The tenant checklist is now T1-T21; the backlog gains S8, P1.9 and P1.10, and marks the delivered parts of P0.1, P0.2, P1.1-P1.3, P1.7 and P9.2.
- `evals/foundry/` is now `evals/evaluators/`, with the code-based evaluators in `code/`; `evals validate --foundry-dir` is now `--evaluators-dir`. The L1 orchestrator's model settings moved from `[foundry]` to `[azure_openai]`. The architecture diagram's scoring zone shows both backends.
- **Microsoft Foundry Evaluations is the evaluation framework of record** ([ADR-007](docs/decisions/ADR-007-foundry-evaluations-framework-of-record.md); implementation plan version 1.1). GitHub and Python are now only the thin layer that drives the Copilot surfaces and gathers evidence; Fabric keeps the expected values and the business scorecard.
  - Added `evals/evaluators/`: the evaluator catalog, the eval definition (OpenAI Evals format), the code-based evaluators `routing_match`, `no_decoy` and `citation_match` with unit tests, a `value_match` skeleton, and the AI judge and extraction prompts.
  - Added offline checks of the Foundry definitions to `evals validate`: sandbox rules, declared row fields, and that no LLM-facing prompt can see the expected answer.
  - Added `EvalItem` (one Foundry dataset row per attempt) and `EvaluatorResult` to the data contracts; removed the Python scoring package and `Attempt.extracted`.
  - Added spike S7 (Foundry evaluation contract), task P2.7 (Foundry client), tenant item T18 (Foundry User role) and the `foundry_evaluations` entry in `config/contracts.yaml`.
  - The PR gate and nightly workflows register the evaluators before each run; the architecture diagram's scoring zone now shows Microsoft Foundry.
