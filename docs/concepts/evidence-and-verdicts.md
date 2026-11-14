# Evidence Tiers and Verdicts

Analytical assistants can fail silently in three distinct ways: returning the right-looking prose with the **wrong number**, returning a plausible number pulled from a **stale sandbox or draft decoy**, or citing the right report while an underlying **DAX query errored or hit a fallback cache**. `cfeval` separates **routing evidence** (`RoutingEvidence`), **trace correlation quality** (`CorrelationConfidence`), and **turn verdict** (`Verdict`) so scorecards never conflate missing telemetry with a verified pass.

## `RoutingEvidence` Tiers

Every scored turn records a `RoutingEvidence` badge indicating the strongest provenance channel observed:

| `RoutingEvidence` | How It Is Established | What It Proves | What It Cannot Prove |
|---|---|---|---|
| `engine+citations` | Graph/target response includes artifact citations **and** Workspace Monitoring (`SemanticModelLogs`) matched one or more `QueryEnd` events for the turn. | Copilot both cited an inspectable artifact to the user and executed real engine DAX against the logged `SemanticModelId` with observable `StatusCode` and `QueryText`. | If `CorrelationConfidence` is `low` (concurrent shared identity load), pairing between multiple simultaneous turns is probabilistic rather than exact. |
| `engine-only` | Workspace Monitoring captured `QueryEnd` DAX execution on the semantic model, but the surface response omitted a user-visible citation link. | A real semantic model query ran on the logged `SemanticModelId` during the turn window. | Users reading the chat response received no clickable report/model attribution (`artifact` gate fails if a visible citation is required). |
| `tool_call` | An agent or MCP client (`fabric-iq-mcp` / `mcp-agent` or `fabric-data-agent`) recorded structured tool-call arguments and results naming the target Fabric item. | The orchestrator explicitly invoked the Fabric IQ tool against the recorded item ID and received structured tool output. | Unless paired with Workspace Monitoring, it does not expose VertiPaq `CpuTimeMs` or internal engine sub-queries behind the MCP endpoint. |
| `citations-only` | Surface response returned Graph attributions (Power BI URLs, SharePoint/OneDrive files, Teams/Mail items), without `SemanticModelLogs` engine rows. | Copilot grounded its response in the cited M365 document or referenced the cited Power BI item metadata. | **Cannot prove** what DAX query ran, whether a Power BI semantic model actually executed at query time, or whether an un-cited decoy model was also touched. |
| `unverified` | Neither engine logs, structured tool calls, nor surface citations were captured for the turn. | Only that the target returned text (useful for pure `abstention` or `clarification` prompts). | Proves nothing about data source routing or grounding; any active `artifact` or `model` gate fails or resolves `INCONCLUSIVE`. |

## `CorrelationConfidence` Levels

Because the Microsoft 365 Copilot Chat API (`/beta`) does not return the internal Power BI engine `OperationId` in the HTTP chat payload, `cfeval` correlates `SemanticModelLogs` `QueryEnd` events using `CorrelationId` (when propagated via client/MCP headers) and bounded user/time windows (`[RequestSentUtc - skew, ResponseReceivedUtc + tail]`):

| Level | Criteria | Interpretation |
|---|---|---|
| `high` | Exact `CorrelationId` / `OperationId` match, **or** a single unambiguous `QueryEnd` window for `ExecutingUser` on a monitored model with zero overlapping turns. | Engine DAX attribution is deterministic for practical gating. |
| `medium` | Multiple `QueryEnd` queries executed sequentially for `ExecutingUser` within the turn's `[RequestSentUtc, ResponseReceivedUtc]` window (common when Copilot inspects schema/measures and then runs the answer DAX) with no overlapping external turns. | All captured queries belong to this turn; inspect `dax_queries.jsonl` to see the final evaluation query. |
| `low` | Overlapping concurrent queries for the same `ExecutingUser` or timestamps falling only within the outer clock-skew buffer. | Candidate DAX logs exist, but concurrent activity on the same account makes attribution uncertain. Run live suites sequentially under an isolated test user. |
| `none` | Zero `SemanticModelLogs` events matched the turn window (monitoring disabled, KQL ingestion lag exceeded `CFEVAL_MONITORING_WAIT_SECONDS`, Work IQ document turn, or verified-answer bypass). | Engine evidence is absent; `cfeval` will not guess which model ran. |

## Verdict Semantics (`PASS`, `FAIL`, `INCONCLUSIVE`, `ERROR`)

Each active gate (`value`, `artifact`, `model`) returns `1` (`PASS`), `0` (`FAIL`), or `-1` (`INCONCLUSIVE`), which roll up to the turn `Verdict`:

| Verdict | Meaning | Examples | Gate & CI Behavior |
|---|---|---|---|
| `PASS` | Every active gate configured on the question succeeded (`1`) with sufficient evidence. | Extracted `$12.84M` matches `12840000` within `display_rounded`, certified report cited, `Core Sales` queried with `0` DAX errors, zero decoys touched. | Counts in the numerator and denominator of `OverallPassRate`, `pass@1`, and `pass^k`. |
| `FAIL` | At least one active deterministic gate returned `0` (`FAIL`). | Wrong number (`$11.95M` net vs `$12.84M` gross), decoy `Sales Sandbox` cited or queried, DAX `QueryEnd` failed, or fabricated figure on an `abstention` prompt. | Counts as `0` in pass rates; critical case failures trigger exit code `2` in `cfeval gate`. |
| `INCONCLUSIVE` | No active gate failed (`0`), at least one active gate lacked the evidence needed to verify (`-1`), and the turn did not error. | `model` gate enabled while Workspace Monitoring is off (`CorrelationConfidence = none`), or `expected` is uncalibrated (`null` without `reference_dax`). | **Never coerced into `PASS`.** Reported separately (`InconclusiveCount`); fails strict runs (`cfeval run --strict` / `cfeval gate` exits `3`). |
| `ERROR` | Target invocation, auth claim check, or scoring pipeline encountered an operational failure before producing a gradable turn. | HTTP `504` gateway timeout after retries, expired token, or malformed import record. | **Never coerced into `PASS` or silently dropped.** Recorded in `ErrorCount` and triggers exit code `3` under strict gating. |

## Why `INCONCLUSIVE` and `ERROR` Never Become `PASS`

In enterprise analytics, treating "telemetry missing" or "API timed out" as a silent pass—or quietly dropping those rows from the denominator—creates a perverse incentive: disabling Workspace Monitoring or triggering rate limits can make an evaluation pass rate appear to *improve*. Keeping `INCONCLUSIVE` and `ERROR` as first-class statuses guarantees that:

1. Denominators remain identical across paired baseline and candidate runs (`N` questions stay `N` questions).
2. `citations-only` runs clearly show what was verified (answer text + link) versus what requires Workspace Monitoring (`model` / `dax`).
3. Release pipelines (`cfeval gate`) fail closed (exit code `3`) whenever telemetry pipelines degrade.

## Related Pages

* [How It Works](./how-it-works.md)
* [Metrics and Statistical Tests](./metrics.md)
* [CLI Exit Codes](../reference/exit-codes.md)
