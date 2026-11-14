# Glossary and Microsoft Evaluation Vocabulary

`cfeval` preserves backwards-compatible telemetry column names (`EvalQuestions`, `QuestionId`, `fabric-native`, `foundry`) for OneLake and Eventhouse continuity while aligning documentation and reports to Microsoft's published agent evaluation vocabulary ([Agent evaluation overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluation-overview) and [Microsoft Foundry evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/agent-evaluators)).

## Repository-to-Microsoft Vocabulary Mapping

| Repository / Schema Term | Microsoft Evaluation Term | Definition in `cfeval` |
|---|---|---|
| `golden set` (`data/golden/*.yaml`) | **Test set** (evaluation dataset) | Versioned collection of business prompts, expected values, tolerances, expected sources, and decoys validated by `schemas/golden.schema.json`. |
| `question` entry (`GoldenQuestion`, `QuestionId`) | **Test case** | Single evaluation item in a test set, identified by a stable ID (`Q01`–`Q42`, `W01`–`W22`). |
| `question` text (`Question`) | **Prompt** | Exact user utterance sent to the target surface (`copilot-chat`, `mcp-agent`, `fabric-data-agent`, etc.). |
| `check` (`value`, `artifact`, `model`, `abstention`, `why`) | **Assertion** / **Grader** | Rule or evaluator function (`cfeval.score_value`, `cfeval.score_artifact`, `cfeval.score_model`, `judge.answer_correctness`) returning `PASS` (`1`), `FAIL` (`0`), or `INCONCLUSIVE` (`-1`). |
| `OverallPassRate`, `pass@1`, `pass^k`, `MatchKind`, `RoutingEvidence` | **Quality signal** | Quantitative metric or provenance badge summarizing accuracy, multi-trial consistency, or routing evidence across a test set. |
| `reference_dax`, semantic models, SharePoint/OneDrive/Teams/Mail items | **Grounding data** (and ground-truth reference query) | Authoritative enterprise data sources queried by Copilot at runtime, plus optional `EVALUATE ROW(...)` DAX computing live expected scalars. |
| `--option fabric-native` (`fabric-native`) | **Local scoring** (with Fabric Eventhouse telemetry) | Default 100% deterministic local Python grading (`src/cfeval/scorers.py`) with optional idempotent KQL persistence to a Fabric Eventhouse. |
| `--option foundry` (`foundry`) | **Foundry Evaluations scoring** | Optional cloud/SDK evaluation workflow exporting pure-stdlib custom code evaluators and Layer 5 judge rubrics to Microsoft Foundry. |

## Core Domain Terms

* **`CorrelationConfidence` (`high` | `medium` | `low` | `none`)**: Strength of the join between a conversational turn and `SemanticModelLogs` `QueryEnd` DAX rows (`CorrelationId` match or bounded `[RequestSentUtc, ResponseReceivedUtc]` window for `ExecutingUser`).
* **Decoy (`decoys`)**: Uncertified sandbox semantic model, stale archive, or draft file intentionally present in the demo tenant to verify Copilot routes to authoritative sources (`DecoyAvoided = true`).
* **`display_rounded`**: `MatchKind` outcome where Copilot reports a human-scaled figure (such as `$12.8M` for `$12,840,000`) within `min(0.5 * ulp, |expected| * display_tol)`.
* **`INCONCLUSIVE`**: Honest status indicating a required assertion lacked observable evidence (for example `model` gate active when Workspace Monitoring logs were unavailable). Never counted as `PASS`.
* **`pass@1`**: Unbiased probability that a single attempt passes ($\frac{c}{n}$ averaged across test cases).
* **`pass^k`**: Multi-trial reliability metric $(c / n)^k$ measuring the probability that **all $k$ independent attempts** pass.
* **`RowId`**: Deterministic SHA-256 key (`sha256(run_id | table | natural_key)[:32]`) enabling idempotent retries and deduplicated Eventhouse views (`arg_max(IngestedAtUtc, *) by RowId`).
* **`RoutingEvidence` (`engine+citations` | `engine-only` | `tool_call` | `citations-only` | `unverified`)**: Highest provenance tier observed for a turn (see [Evidence Tiers and Verdicts](../concepts/evidence-and-verdicts.md)).

## Related Pages

* [How It Works](../concepts/how-it-works.md)
* [Evidence Tiers and Verdicts](../concepts/evidence-and-verdicts.md)
* [Telemetry Schema Reference](./telemetry-schema.md)
* [Use with the Evaluations CLI](../how-to/use-with-the-evaluations-cli.md)
