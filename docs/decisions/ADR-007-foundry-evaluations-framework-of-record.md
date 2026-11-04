# ADR-007: Microsoft Foundry Evaluations is the evaluation framework of record

- **Status:** Accepted; amended by [ADR-009](ADR-009-two-evaluation-backends.md): Foundry Evaluations is the default of two evaluation backends, and a local backend runs the same evaluators without Foundry
- **Date:** 2026-11-03
- **Plan sections:** §2.1 (finding 11), §2.3, §3.2–§3.4, §9.6, §9.8–§9.11 (PLAN version 1.1)
- **Supersedes:** the version 1.0 decision in PLAN §2.3 ("build a custom Python harness; deterministic scorers are the source of truth")
- **Spike:** S7 confirms the contract in our project and region (ADR-008)

## Context

Version 1.0 of the plan scored every attempt with custom Python scorers and used Microsoft Foundry only to host the LLM judge. Before the repository is deployed, the owner reconsidered where scoring, results and comparison should live.

Three facts frame the choice:

1. **No framework can drive Microsoft 365 Copilot.** Foundry cloud evaluation sends prompts only to Foundry-deployed models and agents (`azure_ai_target_completions`), and the open-source frameworks call only what they host. The code that talks to Copilot stays custom whatever is chosen.
2. **Foundry can score a file of answers collected elsewhere.** A cloud evaluation run scores a JSONL dataset with built-in evaluators and our own custom evaluators, and returns per-row results, pass rates and a portal report page.
3. **Our checks fit Foundry's custom evaluators.** The value, routing, decoy and citation checks are deterministic code; the clarify, refuse and no-access checks need an LLM judge. Foundry offers both, code-based and prompt-based, in one run.

## Options considered

| Option | For | Against |
|---|---|---|
| **A. Custom Python scorers (version 1.0)** | Full control; no preview dependency | A second results store and judge beside the one Microsoft's own tooling uses; reports, comparison and access control all have to be built |
| **B. Microsoft Foundry Evaluations as the framework of record** | One AI judge and one results store, the same Foundry project the Agent Evaluations CLI already judges with; a report page per run; results retrievable for CI and Power BI; runs in the customer's Azure subscription with Entra ID and role-based access, and adds red-teaming and monitoring later; test definitions in the OpenAI Evals format | Custom evaluators are preview with no SLA; built-in tool-call evaluators don't support Fabric data agent calls; the AI judge costs tokens |
| **C. An open-source framework (promptfoo, DeepEval, Inspect AI, MLflow) at the core** | Mature runners, repeats and CI integration | Can't drive Copilot either; a second judge and results store outside the customer's Microsoft estate; more stack to support |
| **D. Run the L1 orchestrator as a Foundry agent, so Foundry also drives L1** | Foundry could generate L1 answers itself | Fabric IQ MCP accepts only delegated user sign-in, and a cloud evaluation run has no persona sign-in to pass through, so row-level security per persona can't be tested |

## Decision

Option B. **Microsoft Foundry Evaluations is the evaluation framework of record.**

- **Foundry decides.** Every check is a Foundry custom evaluator whose source lives in `evals/evaluators/`:

  | Check | Evaluator | Kind |
  |---|---|---|
  | The right number | `value_match` | Code-based |
  | The right semantic model | `routing_match` | Code-based |
  | No decoy model, document or non-Fabric source | `no_decoy` | Code-based |
  | Citations name the certified source | `citation_match` | Code-based |
  | Should answer, ask a clarifying question, refuse or report no access | `behavior_match` | Prompt-based (AI judge) |

- **Python gathers, never judges.** Code-based evaluators run without network access and with a 2-minute limit per call, so the runner collects everything first: the live expected value from Fabric and the engine-log hits. It writes one dataset row per attempt (`EvalItem`), submits one Foundry run, and reads the results back for the CI gate and Power BI.
- **Fabric keeps the truth and the business view:** the semantic models that produce expected values, the engine logs that show which model answered, and the Lakehouse and Power BI scorecard. Foundry results are copied there; Foundry remains the record.
- **The AI judge never sees the expected answer.** It classifies behaviour and, in the run's extraction step, reports which figure an answer gives. `judge_blind_fields` in `eval-definition.yaml` lists the fields no LLM-facing template may reference, and `evals validate` enforces it.
- **Endpoint-based evaluators** (our own HTTP endpoint, 30-second limit) are held in reserve for a check that ever needs a live lookup. None does today.

## Consequences

### What changes

- PLAN 1.1 updates §1, §2.1, §2.3, §3, §6 (T5, T18), §7, §8, §9.1, §9.6, §9.8–§9.11, §10–§16 and Appendices A and C.
- `evals/evaluators/` holds the evaluator catalog (`evaluators.yaml`), the evaluators, the judge and extraction prompts, and the eval definition (`eval-definition.yaml`).
- `src/copilot_evals/scoring/` is removed. `src/copilot_evals/foundry/` holds the thin client: offline definition checks today; registration, dataset upload, runs and results in P2.7.
- `schemas.py` gains `EvalItem` (the dataset row) and `EvaluatorResult` (a Foundry verdict read back); `Attempt` no longer carries an extracted value.
- The backlog gains spike **S7** (the Foundry evaluation contract) and task **P2.7** (the Foundry client); P2.5 now builds evaluators instead of scorers.
- The pull-request gate and nightly workflows register the evaluators (`evals foundry sync`) before each run.
- The runner identity and the builder need the Foundry User role at the Foundry account scope (tenant item T18).

### How the caveats are handled

| Caveat | Mitigation |
|---|---|
| Custom evaluators are preview, with no SLA | Evaluator source and definitions live in this repository in the OpenAI Evals format. `grade()` files are plain Python, unit-tested in CI by executing them as the sandbox does, so they could be re-hosted. Spike S7 confirms the contract before anything depends on it, and the nightly run is the smoke test. |
| Built-in tool-call evaluators don't support Fabric data agent calls | The routing and decoy checks were always going to be our own; they are code-based evaluators over engine-log evidence. |
| The AI judge costs tokens | The judge runs only where code can't decide (behaviour, ambiguous extraction), on a mini model; pull requests run L0–L1 only; each completed run reports an estimated target cost. |
| An evaluator can return only a float | A check that can't decide raises; Foundry records an error, and the gate reports INCONCLUSIVE rather than FAIL. S7 confirms how errors appear in output items. |
| Reproducibility while evaluators change | Catalog names are content-addressed (`cfiq_<key>_<sha8>`), so a run always uses the evaluator source in its commit and a pull request can't change what `main` runs. If S7 shows `testing_criteria` can pin versions, ADR-008 can switch to versions. |

### What stays the same

- The golden set, personas, routing policy, evaluation layers (L0–L3), failure triage, gate policy and demo story.
- The thin layer still drives every surface, including the L1 reference orchestrator (option D was rejected).

## Contracts updated

`config/contracts.yaml` gains `foundry_evaluations` (status `documented`, sources S33–S40). Spike S7 resolves its `TODO(spike-S7)` markers and records the result as ADR-008.
