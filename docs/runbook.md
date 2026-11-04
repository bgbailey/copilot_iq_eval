# Demo runbook

> **Draft.** This is the outline of the customer-facing demo from PLAN §12 (about 25 minutes). Task **P10.3** completes it with tester prompt cards, troubleshooting and the token re-bootstrap procedure, and a dry run.

## Before the demo

- [ ] Last night's `nightly` run is green, or its failures are understood.
- [ ] `uv run evals auth check --personas exec,east,noaccess` passes on the runner.
- [ ] The scorecard is refreshed and open on the Overview page, and last night's run record is open in another tab: its Foundry report page on the Foundry path, or its GitHub Actions job summary on the local path.
- [ ] You know which evaluation backend the runs use (`EVALS_BACKEND`); see [Choosing an evaluation path](evaluation-paths.md).
- [ ] The regression-injection scripts (P10.2) are tested, and their automatic revert works.

## Demo script

| # | Segment | Time | What to show |
|---|---|---|---|
| 1 | The question | 2 min | Golden case `REV-001`: prompt, expected model, decoy, reference DAX and tolerance, and the routing policy. |
| 2 | Last night's results | 5 min | Scorecard overview; the routing matrix (the diagonal is correct routing); consistency across L1, L2 and L3. Point out that the decoy row is empty. Open the run's record (the Foundry report page, or the job summary on the local path): every verdict is recorded with the evaluator version that produced it. |
| 3 | A live run | 5 min | `evals run --case-filter REV-001,FIN-002,OPS-003 --surfaces ref_mcp,agent_cli --personas exec,east --k 1`, then the evidence for one attempt: answer, extracted value, expected value from live DAX, the `SemanticModelLogs` row naming the model and its DAX, and the citation. Then the same attempt's evaluator results and the judge's reason, in the Foundry report or in the `evals score` output. Optional (3 min): score the run's `out/eval_items.jsonl` again with `evals score --backend local` and show that the verdicts match the Foundry run evaluator by evaluator. |
| 4 | Regression injections | 10 min | Each one is caught by the PR gate and reverted by script (below). |
| 5 | Governance close | 3 min | Attribution to source and owner; nightly audit reconciliation by access point (Teams, web, desktop); alert history. |

### Regression injections (PLAN §12)

| Injection | How | What the audience sees |
|---|---|---|
| **Ambiguity** | Blank the description of Sales Analytics `[Gross Revenue]` and describe Finance `[Net Revenue]` as "Revenue (company total)". | Disambiguation cases such as REV-002 drift to Finance. L0 stays green and L1 fails, so triage points to semantic-model readiness rather than Copilot. |
| **Decoy made to look official** | Rename Sales Sandbox to "Sales Analytics – Latest" and copy the certified measure description. | Decoy hits rise above zero and the gate blocks. |
| **Policy drift** | Delete the "revenue means gross" rule from `agents/policy/routing-policy.md`. | L1 and L2 regress on disambiguation while L0 stays green; the pull-request diff shows the cause. |

## Tester prompt cards

*To be written in P10.3: the prompts testers run in Teams, web and desktop for the access-point consistency check (P6.2).*

## Troubleshooting

*To be written in P10.3.*

## Re-bootstrapping persona tokens

*To be written in P10.3, with `evals auth login --persona <key>` (P2.3).*
