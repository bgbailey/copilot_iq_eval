# AI judge: calibration (PLAN §9.6.6)

The AI judge is a prompt-based evaluator that runs on either evaluation backend: Microsoft Foundry Evaluations runs it as a Foundry prompt-based evaluator ([ADR-007](../../docs/decisions/ADR-007-foundry-evaluations-framework-of-record.md)), and the local backend sends the same prompt to its own judge deployment ([ADR-009](../../docs/decisions/ADR-009-two-evaluation-backends.md)). It is used **only** where code can't decide:

1. classifying behaviour (answer, clarify, refuse or no access): the [`behavior_match`](../evaluators/prompts/behavior_match.md) evaluator; and
2. reporting which figure an ambiguous answer gives: the [`value_extraction`](../evaluators/prompts/value_extraction.md) prompt in each run's extraction step.

Neither ever sees the expected value; `evals validate` enforces that. The prompts live in [`../evaluators/prompts/`](../evaluators/prompts); this folder holds what proves them trustworthy.

Task **P10.1** adds here:

| File | Contents |
|---|---|
| `calibration_set.jsonl` | About 60 human-labelled rows covering rounding, ratio vs percent, units, list order, group-by completeness, and refuse vs fabricate. |
| `calibration.md` | How the calibration run is set up on each backend in use, and the latest results per judge deployment. |

A judge prompt version is promoted (and its evaluator version stored on every `eval_run`) only when, over the majority of 3 runs on the calibration set, raw agreement is at least 0.90, Cohen's kappa at least 0.70 and recall on FAIL at least 0.85. The judge's behaviour depends on the model deployment as well as the prompt, so calibrate on each backend you use: as a Foundry evaluation, or with `evals score --backend local` and the local judge deployment.
