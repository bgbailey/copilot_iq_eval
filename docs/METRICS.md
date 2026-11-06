# Metrics

The Python harness (`pipeline.run_metrics`), the KQL functions (`src/cfeval/kql/functions.kql`) and the app
(`app/overlay/src/eval/metrics.ts`) use the same definitions. The scripted live demo is the acceptance test;
CI only runs a minimal offline smoke and app typecheck/build.

## Checks and verdicts

| Check | Score | Meaning |
|---|---|---|
| `value` | 1 / 0 / 0.5 | 1 when the first unit-compatible number in the answer is within tolerance of the expected value; 0.5 when no expected value is set |
| `artifact` | 1 / 0 / 0.5 | 1 when a cited Power BI item matches the expected report or model and no decoy is cited; 0.5 when no expected artifact is set |
| `model` | 1 / 0 / 0.5 / none | 1 when a settled capture contains the expected model and no configured decoy; an observed decoy is always 0, even during partial capture; 0.5 for missing/unsettled/error evidence; none when capture is off |
| `judge_answer` | 0 to 1 | Option 1: the judge's yes/no on correctness. Option 2: the prompt evaluator's 1 to 5 score, as (score − 1) / 4 |
| `why` | 0 to 1 | Consistency of Copilot's explanation with its citations and the DAX, 1 to 5 scaled to 0 to 1 |
| `coherence`, `similarity` | 0 to 1 | Option 2 built-in evaluators, 1 to 5 scaled to 0 to 1 |

**Verdict** per ask and option: `ERROR` when the Copilot call or that scoring backend failed; otherwise `FAIL` when any gate check
(`value`, `artifact`, `model`) is 0; `INCONCLUSIVE` when a required gate is 0.5, missing, invalid or disabled;
`PASS` only when every required gate passes. With `JUDGE_GATES_VERDICT=true`, Option 1 also requires
`judge_answer`, even if no judge is configured.

### Artifact evidence

The artifact gate counts links in the answer and model-source citations. Grounding-only discovery metadata and
annotations remain in `EvalAsk.Artifacts`, but are not counted as answer citations. A direct answer link still
counts when the same item also appeared in grounding metadata. Legacy saved artifacts without attribution
fields retain their earlier citation meaning.

The citation names/counts and both scoring options use this same policy. An actually cited decoy fails the
artifact gate; an observed decoy model fails the independent model gate. Passing the citation gate does **not**
prove that other grounding had no influence. See the
[Chat attribution contract](https://learn.microsoft.com/microsoft-365/copilot/extensibility/api/ai-services/chat/resources/copilotconversationattribution).

### Scoring failures

A failed/canceled Foundry run, a backend exception, or missing/invalid expected criterion results is an
`ERROR`, not a quality failure or a successful evaluation with inconclusive grades. Independent local results
are retained. Such a run is `partial` when some results remain valid, otherwise `failed`; the CLI exits nonzero.
The original Foundry IDs/status and available diagnostics are preserved. Missing cloud grades are never
replaced with local grades.

### Value matching

* Numbers are read from the answer after removing links, citation markers, years, fiscal labels (`FY2025`, `Q2`),
  dates, ordinals and labels such as `Sev1`.
* The unit picks the candidate: `percent` takes numbers with `%`; `currency` prefers numbers with a currency sign,
  then scaled numbers (`12.8M`); `count` and `number` prefer plain numbers.
* Tolerance is the larger of `abs_tol` and `rel_tol × expected`. **Display-aware** tolerance also accepts a value
  within half of its displayed precision (`$12.8M` covers 12.75M to 12.85M), unless that half-step is more than 5%
  of the expected value, in which case the answer is too coarse to verify and fails.

## Run and scorecard metrics

| Metric | Definition |
|---|---|
| Pass rate | PASS scored results ÷ all scored results, per backend (errors count as not passing); combined views label scoring rows separately from physical asks |
| Correct value / Right report cited / Right model queried | Asks scoring 1 ÷ asks scoring 0 or 1 on that check (inconclusive and skipped are excluded; errors are excluded) |
| Decoy rate | Asks that cited or queried a decoy ÷ asks without errors |
| Latency p50 / p95 | One answer-latency observation per `(RunId, AskId)`, excluding ERROR; Python/app use linear interpolation, KQL uses its percentile aggregate |
| DAX per ask | Average number of DAX queries captured per traced ask |
| Time in DAX p50 | Median of total DAX duration per ask, over asks where DAX ran |
| Asks with DAX captured | Traced asks with at least one query ÷ traced asks |
| Agreement | Asks scored by both options with the same verdict ÷ asks scored by both |
| Model sets (Questions page) | Distinct sets of queried models seen for a question across runs; more than one means routing is unstable |

## Latency fields

| Field | Meaning |
|---|---|
| `LatencyMs` | Time for the Copilot Chat API to return the answer turn |
| `WhyLatencyMs` | Time for the follow-up "why" turn |
| `DaxTotalMs`, `DaxMaxMs`, `DaxQueryCount` | Sum, maximum and count of captured DAX query durations for the ask |
| `FirstDaxOffsetMs` | When the first DAX query ended, measured from the ask start |
| `OffsetMs` (FabricIqQuery) | When each query ended, measured from the ask start; it started `DurationMs` earlier |
| `EvalEvent.DurationMs` | Harness stage time: `copilot.ask`, `copilot.answer`, `copilot.why`, `trace.watermark`, `trace.wait`, `trace.fetch`, `score.local`, `score.judge`, `score.foundry`, `publish.results`, `run.total` |

Captured DAX work is **not additive** with answer latency. Queries can overlap, and capture includes the follow-up
window while `LatencyMs` covers only the answer turn. Subtracting the sum from answer latency does not measure
retrieval, orchestration or generation time.

## Trace status

| Status | Meaning |
|---|---|
| `observed` | Nonempty capture settled after progress within the deadline; correlation is heuristic, not exhaustive |
| `complete` | Legacy saved/sample status; not a new completeness guarantee |
| `pending` | No DAX was observed, progress is missing, or capture did not settle; incomplete evidence, not acceptance |
| `error` | The monitoring query failed |
| `disabled` | DAX capture isn't configured for the run |

## Scripted acceptance and publication

`tools/rehearse_demo.py` is stricter than a low-level harness completion: one Option 1 batch, one actual why turn
per question, all five expected checks, and nonempty settled DAX per ask. A runtime ERROR or inconclusive trace
cannot become successful acceptance. Quality FAIL exits 2; runtime/incomplete evidence or publication exits 3.

Expected publication counts come from the current **raw run JSONL**, not an assumed fixed number or deduplicated
latest-row view: seven Eventhouse tables and five SQL tables (`EvalRun`, `EvalQuestion`, `EvalResult`,
`FabricIqQuery`, `EvalEvent`). Multiple late row versions must be counted as recorded. Exact readback must match
both systems. Zero queries/scores is not an acceptable “matching zero” result.

OneLake's five-minute minimum latency setting is not a hard upper bound. Each table propagates independently.
After a publication observation timeout use `--verify-only` on the same run; it only reads JSONL/Eventhouse/SQL.
Do not rescore, refetch traces or republish as a hidden resume. A pending original trace requires diagnosis and
separate approval, not a second full batch until the dashboard turns green.

## Evidence gaps / still thin

Citation compliance, self-reported source explanations and observed user/time-correlated DAX are different
evidence. None guarantees exclusive grounding or exhaustive capture. A failed service run without error detail
does not establish its root cause or zero billing.
