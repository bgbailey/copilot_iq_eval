# Scripted demo and acceptance

This is a personal demonstration shared as a community accelerator, not production tooling.
**The documented scripted live demo is the acceptance test.** Use Option 1; do not run an extra unscripted
batch followed by a duplicate “acceptance” batch or repeat the full run during the meeting.

## Before any paid calls

1. Complete [SETUP.md](SETUP.md): exact licensed test-user/operator identities, consent, retained report/model
   access, Viewer + Read/Build, RLS in the supported UI, Prep data for AI and labelled browser sign-in.
   Owner DAX and an exported field's absence are not proof of test-user access or a disabled UI feature.
2. Keep the original fictional Q01–Q08 sample/history. Prepare a separate calibrated positive-path CSV from
   `data/golden/demo_questions.template.csv`; changed prompts need new IDs. In particular:
   - Service Operations count/MTTR questions name that source; keep old unqualified failures as diagnostics.
   - Sales revenue names Sales Analytics, gross revenue, latest **completed fiscal** quarter and a fixed as-of
     cutoff. The reference DAX/value and reference sentence must agree.
   - Keep an unqualified certified-routing case and an accessible sandbox-decoy check. Do not manufacture a failure.
3. Run read-only setup, then explicitly selected `--apply` changes if required. Publish the app using the public
   scaffold + overlay instructions, not a private executor. Confirm all five SQL tables are visible first.
4. Record the approved total question/judge allowance and capacity window. The operator tracks cumulative usage;
   failed/ambiguous attempts count. No new Foundry dataset evaluation is needed for this route.

## Optional named-source controls, only within the approval

When diagnosing a domain gap, use a **separate two-row CSV** for named-source count/MTTR controls and its own
private `.env` pointing to it. Do not launch an eight-row file with a two-question allowance.
Limit that control's `MONITORING_SOURCES` to workspaces represented by its expected/decoy models.
A quiet unrelated workspace cannot receive a roster-based progress marker and would leave capture unsettled;
setup/rehearsal reject that configuration before paid submissions.

```powershell
python tools/rehearse_demo.py --env controls.env --run-id controls-unique-01 --max-questions 2 --max-judge-calls 4
```

Named-source success proves that source was reachable for those prompts, not that unqualified discovery was fixed.
If controls fail, stop to isolate access, RLS, preparation or discovery using actual evidence. Do not silently drop
Service Operations and describe a narrower Sales/Finance demo as all-domain success.

## Run the final batch ONCE

```powershell
python tools/rehearse_demo.py --env demo.env --run-id demo-unique-01 --max-questions 8 --max-judge-calls 16 --wait-seconds 1200 --poll-seconds 30
```

For an approval of two controls plus eight final questions, these are **ten question attempts/why turns and
twenty direct judge attempts total**, not a universal allowance or authorization to retry. The wrapper:

- checks actual cached test-user tenant/principal/scopes and the explicit operator context;
- uses one attempt per question, one why follow-up, `REPEATS=1`, no Chat/judge retries, at most `2N` judge calls;
- rejects any existing run ID and preserves original JSONL, conversation/ask IDs and a rehearsal receipt;
- requires actual why turns, full Option 1 checks and nonempty settled per-ask DAX;
- verifies exact current-JSONL counts for **seven Eventhouse** and **five SQL shortcut** tables using bounded,
  read-only polling, then prints the hosted demo link and manual browser gates.

Exit **0** means scripted gates pass, **2** quality FAIL, **3** runtime ERROR/incomplete evidence or publication,
**64** CLI usage error. An absent score/query is not a passing zero. SQL driver/dependency failures stop before
paid calls with installation instructions; there is no success fallback.

If publication alone times out:

```powershell
python tools/rehearse_demo.py --env demo.env --run-id demo-unique-01 --verify-only --wait-seconds 1200
```

This reads the **same run** only: no question, judge, monitoring fetch, rescore or republish. It can be repeated
for observation without another full batch. Tables arrive independently: OneLake's five-minute minimum setting
is not a hard upper bound. Interrupted submissions/sink errors require reconciliation, not blind repetition.

## Show the recorded evidence (about 15 minutes)

| Stop | What to show honestly |
|---|---|
| Contract | The calibrated positive-path CSV plus separately retained ambiguous/unqualified diagnostic history |
| Ask | Actual answer, answer links/citations and original conversation ID; grounding-only metadata is not an answer citation |
| DAX | `AskTimeline('<ask id>')` and recorded model/query rows; user/time correlation is observational, not exhaustive/causal proof |
| Explanation | Actual generated why reply, compared with citations/DAX; it is not chain of thought |
| Overview | Select **Live only** and **Option 1**; the headline is the filtered live-history aggregate, not this run's score |
| Questions | Fresh values, expected/cited/queried sources, actual outcomes—including any FAIL/pending/error |
| Performance | Independent answer/why round trips, captured DAX work and stages; DAX may overlap and is not an additive latency split |
| Runs | Find the actual new run name/ID and its own score/ask counts; do not imply successful Option 2 service evaluation |

Enter the **published app through Fabric portal**, verify the actual SSO account/tenant in a persistently labelled
browser context, and check fresh **Overview, Questions, Performance, Runs**. A standalone/build is not hosted
evidence. Record this manual gate before calling the demo ready. If all-domain evidence is missing, it is NO-GO
unless the owner explicitly approves a narrower presentation.
There is no global per-run selector: the controls filter backend, time window and live/simulated history.
Use the **Runs** row for the final rehearsal's own pass rate; do not call a historical aggregate its score.

## Optional Option 2

The Foundry notebook/CLI remain available for separate approval. Preview dataset evaluation can fail before
returning grades/error detail. Preserve original eval/run IDs and service status and stop; never replace missing
cloud grades with local grades, assume zero billing, or launch another dataset run automatically.

## Evidence gaps / still thin

No prompt can force deterministic source selection through the Microsoft 365 Copilot Chat API. One successful
run is an observation, not a guarantee of later routing. Original “latest quarterly revenue” can legitimately
mean another source/measure/period; that ambiguity alone is not a hallucination. These public docs assert no
private calibration, measured readiness result or Service Operations root cause. Cloud notebook/Key Vault
execution and preview hosted availability need their own observed evidence; preserve workspaces and identities.
