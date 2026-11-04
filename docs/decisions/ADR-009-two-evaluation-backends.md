# ADR-009: Two evaluation backends: Microsoft Foundry Evaluations or local

- **Status:** Accepted
- **Date:** 2026-11-03
- **Plan sections:** §2.3, §3.2–§3.4, §6 (T5, T18, T19), §7, §8 (P2.6–P2.8, P3.2, P8.1, P8.2, P9.1, P10.1), §9.1, §9.6, §9.8–§9.12, §10, §11, §13, §15 (PLAN version 1.2)
- **Amends:** [ADR-007](ADR-007-foundry-evaluations-framework-of-record.md). Foundry Evaluations stays the default backend and the reference implementation; it is no longer the only place verdicts can be decided.

## Context

ADR-007 made Microsoft Foundry Evaluations the evaluation framework of record. This repository is also a **demo reference** for field teams, so it has to serve two kinds of organisation:

- Organisations that run evaluation in Microsoft Foundry: they want a report page per run, a central results store, Foundry's role-based access and, later, red-teaming and monitoring.
- Organisations that can't or won't use it yet: no Foundry project, a region without batch evaluation, a policy against preview services (Foundry custom evaluators have no SLA), or a wish to start with only GitHub and Fabric.

Three facts make one design serve both:

1. **The evaluators are already portable.** Each code-based evaluator is a self-contained `grade(sample, item)` file that uses only the standard library, with no network access. The AI judge is a prompt file with `{{variables}}`. The eval definition is plain YAML in the OpenAI Evals format.
2. **The rest of the harness never depended on Foundry.** Driving Copilot, gathering evidence, ground truth, the gate, the Lakehouse and the Power BI scorecard work the same whatever produces the verdicts.
3. **Two copies of the checks would drift.** Version 1.0 of the plan scored in custom Python. Bringing those scorers back beside the Foundry evaluators would mean two implementations of every check, two sets of bugs and two answers to "why did this fail?".

## Options considered

| Option | For | Against |
|---|---|---|
| **A. Foundry only (ADR-007 as written)** | One path to build, test and explain | Excludes every team that can't use Foundry custom evaluators today; no fallback if the preview service is unavailable |
| **B. Foundry, plus the version 1.0 Python scorers as the alternative** | Each path is idiomatic | Two implementations of every check, which drift; the demo would show two different answers to the same question |
| **C. Foundry, plus an open-source framework (promptfoo, DeepEval, Inspect AI) as the alternative** | Mature runners and reports | Still can't drive Copilot; a second evaluator format, judge and results store; brings back the open-source core that ADR-007 rejected |
| **D. One set of evaluators, two backends that run them** | The checks are written once; both paths give the same verdict for the same row; switching is a setting | The harness owns a small runner for the local path; the local path has no portal report page |

## Decision

Option D. **The evaluators in `evals/evaluators/` are written once and run on either of two backends, chosen per run.**

| | `foundry` (default) | `local` |
|---|---|---|
| Who runs the evaluators | Microsoft Foundry Evaluations, in the customer's Azure subscription | The harness process: the GitHub Actions runner or a developer machine |
| Code-based evaluators | Uploaded to the evaluator catalog; run in Foundry's sandbox | The same files, executed as standalone code exactly as the sandbox runs them |
| AI judge and extraction step | Foundry prompt-based evaluator and target-completions step | The same prompts and messages, sent to an Azure OpenAI deployment through the v1 API with Microsoft Entra ID |
| Where verdicts are kept | The Foundry project, with a report page per run; copied to the Lakehouse | The run artifacts in GitHub Actions and the Lakehouse |
| Client | `copilot_evals.foundry` (P2.7, after spike S7) | `copilot_evals.evaluation.local` (in-process runner delivered; judge client P2.8) |

- **The backend is a setting.** `[evaluation] backend` in `config/settings.toml`, `--backend` on `evals run` and `evals score`, and the `EVALS_BACKEND` repository variable in the workflows. Foundry is the default.
- **Both backends implement one protocol** (`copilot_evals.evaluation.backend.EvaluationBackend`) and return the same `EvaluatorResult` rows, so the runner, the gate, the sinks and the scorecard never branch on the backend. The `eval_run` table records which backend produced a run.
- **Results are comparable across backends.** Each evaluator's version is its content-addressed name (`cfiq_<key>_<sha8>`, `definitions.catalog_name`), recorded identically by both backends.
- **Foundry's rules apply everywhere.** `evals validate` holds every evaluator to the Foundry sandbox rules (size, imports, declared fields) and keeps the expected answer away from every LLM-facing prompt on both paths, so any evaluator moves between backends unchanged.
- **The local backend mirrors Foundry's semantics:** a score at or above the threshold passes; an evaluator that raises, returns a score outside 0–1 or exceeds the sandbox's 2-minute limit yields INCONCLUSIVE; the extraction reaches `value_match` as `item["sample"]["output_text"]`. Where Foundry's behaviour is still unconfirmed (threshold semantics, rendering of non-string template values), spike S7 records it in ADR-008 and the local backend follows.

## Consequences

### What changes

- `evals/foundry/` becomes `evals/evaluators/`, with code-based evaluators in `code/`, prompts in `prompts/` and sample rows in `samples/`. ADR-007's file paths were updated in place when the folder moved, before the repository's first release.
- `src/copilot_evals/evaluation/` holds everything that is backend-neutral: the definitions checker (moved from `copilot_evals.foundry`), the backend protocol, the local backend, the attempt verdict rule and the dataset files. `src/copilot_evals/foundry/` is the Foundry backend only.
- `evals score` scores collected rows on either backend. It runs today on the local backend with no Azure resources; CI runs it on the sample rows.
- Settings gain `[evaluation]` and `[azure_openai]`. The L1 orchestrator's model moves from `[foundry]` to `[azure_openai]`, because it never needed Foundry Evaluations.
- The workflows register Foundry evaluators only on the Foundry backend and pass `--backend` to every run.
- The backlog gains task **P2.8** (the local backend's Azure OpenAI judge client and parity tests) and tenant item **T19** (Cognitive Services OpenAI User on the model resource). Spike S7 and tenant item T18 apply to the Foundry backend only.

### Trade-offs accepted

| Trade-off | Mitigation |
|---|---|
| Two runners for the same evaluators | The local runner is small, has no evaluation logic of its own and reads the same definition; parity tests compare its results with recorded Foundry output items for the same rows (P2.7, P2.8). |
| The local path has no portal report page | The job summary, the run artifacts and the scorecard's Evidence page explain every verdict; `evals score` prints each result with its reason. |
| The local backend does not sandbox evaluators at run time | Evaluators are repository code under review; `evals validate` enforces the sandbox rules statically; the 2-minute limit is checked after each call. |
| Judge calls run from the runner on the local path | Calls run in parallel (`azure_openai.judge_max_workers`); the extraction runs only for `answer` rows, the only rows that use it; pull requests run L0–L1 only. |
| Results on the local path live in GitHub artifacts and Fabric, not a managed store | The Lakehouse is the long-term record on both paths; artifact retention follows the repository's policy. |

### What stays the same

- Everything in ADR-007 about where the checks run in the Foundry path, how the judge is kept blind, and why Python never scores outside the evaluators.
- The golden set, personas, routing policy, evaluation layers, failure triage, gate policy and demo story.

## Contracts updated

`config/contracts.yaml` gains `azure_openai_v1` (status `documented`, source S41): the v1 base URL, Microsoft Entra ID sign-in with the `https://ai.azure.com/.default` scope, and the Cognitive Services OpenAI User role. The `foundry_evaluations` entry is unchanged and applies to the Foundry backend.
