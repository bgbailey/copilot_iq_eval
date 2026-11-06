# Copilot Chat × Fabric IQ evaluation accelerator

Check whether **Microsoft 365 Copilot Chat** answers business questions from the **expected semantic model** with
the **expected number**. The harness asks a golden set of questions through the
Microsoft 365 Copilot Chat API, records what Copilot cited and how it explains its sources, captures the **DAX that
Fabric IQ ran** for each answer, scores everything, and writes it all to a **Fabric Eventhouse**. A **Fabric app**
shows accuracy, routing, DAX and latency.

![Simplified architecture](docs/architecture/simplified-architecture.png)

> Community accelerator, provided as-is under the MIT license. It is not a Microsoft product and isn't supported
> by Microsoft. It uses preview services (the Copilot Chat API, Fabric Apps, Foundry custom evaluators); check
> their current terms before you use it with production data.

## What it answers

| Question | How it's measured |
|---|---|
| Did Copilot give the expected value? | First unit-compatible number in the answer vs the golden value, with display-aware tolerance (`$12.8M` passes for 12,840,000). |
| Did it cite the right report or semantic model? | Copilot's citations (Chat API attributions and links). Citing a decoy fails the ask. |
| Did Fabric IQ query the right model? | DAX captured from workspace monitoring (`SemanticModelLogs`), matched to the ask by test user and time window. |
| Why did it answer that way? | A follow-up turn asks Copilot to state its sources, filters and period; a judge model checks that against the evidence. |
| How fast, and where does the time go? | Answer and follow-up latency, DAX count and duration per ask, harness stage timings. |
| Is it getting better or worse? | Every run lands in the Eventhouse: trends, flaky questions, Option 1 vs Option 2 agreement. |

## Two ways to run the evaluation

Both options use the same harness to drive Copilot Chat (no evaluation framework can call Copilot itself), the
same golden set and the same telemetry tables. They differ in what scores the answers.

| | Option 1 · Fabric-native | Option 2 · Microsoft Foundry Evaluations |
|---|---|---|
| Scoring | Deterministic Python checks plus a judge model deployed in Foundry | Foundry evaluation runs: the same checks as **code evaluators**, plus **prompt** and **built-in** evaluators |
| Where it runs | A Fabric notebook (or locally) | Harness in a notebook; scoring in your Foundry project |
| Results | Eventhouse, KQL and the Fabric app | Foundry report and run comparison, **and** the same Eventhouse tables |
| Pick it when | You want everything in Fabric with the fewest moving parts | Your AI evaluation practice is standardized on Foundry |

**Demo default: Option 1 only.** Option 2 is optional and can fail in the preview service before returning grades.
Keep its original service IDs/error and stop; never substitute local grades or start another dataset run blindly.
The low-level CLI still offers `--option both` for a separately approved comparison.

## Quickstart (offline, 2 minutes)

No sign-in and no Azure resources: a simulated tenant mimics Copilot Chat, Fabric IQ's DAX, workspace monitoring
delays, the judge model and Foundry. Python 3.10+ with `requests` is all it needs.

```bash
git clone https://github.com/bgbailey/copilot_iq_eval
cd copilot_iq_eval
python -m pip install -e .
python -m cfeval run --mock --option both
```

Or open [`notebooks/00_quickstart_offline.ipynb`](notebooks/00_quickstart_offline.ipynb). To see the scorecard app
with sample data, use **Node 24 LTS**, then `npm ci` and `npm run dev` in [`app/standalone`](app/standalone).
Simulated history is labelled and its aggregate trend is not a live score or measured tuning result.

## Live setup (demo tenant)

**Bring your existing semantic models, reports, workspaces and capacity.** These scripts never create/delete
workspaces, replace models/reports, manage capacity, or automate Entra consent, RLS or Prep data for AI.

1. Complete the manual licensing, consent, test-user access/RLS, AI-preparation and labelled sign-in gates in
   [docs/SETUP.md](docs/SETUP.md). Enable monitoring **data collection** in every expected/decoy workspace.
2. Copy `.env.example` to a private `.env`; configure exact identities and existing target IDs. Create a separate,
   calibrated CSV from [`data/golden/demo_questions.template.csv`](data/golden/demo_questions.template.csv).
   Preserve the fictional Q01–Q08 baseline/history; changed prompts get new IDs.
3. Use the two entrypoints below. Setup is read-only unless both an operation flag and `--apply` are supplied.
   The rehearsal uses explicit per-run attempt caps, one question + one why turn per conversation,
   disables Chat/judge retries, and never invokes Foundry dataset evaluations.
4. Scaffold, overlay and publish the app separately using [app/README.md](app/README.md). Hosted SSO and browser
   views are manual acceptance gates, not something a standalone build can prove.

```powershell
python -m pip install -e ".[copilot,kusto,judge,sql]"
# Install Microsoft ODBC Driver 18 for SQL Server separately if absent.
python tools/setup_demo.py --env .env
python tools/setup_demo.py --env .env --telemetry --shortcuts --refresh-golden --apply
# Review calibrated expected_answer text too, then run ONCE within your explicitly approved allowance:
python tools/rehearse_demo.py --env .env --run-id demo-unique-01 --max-questions 8 --max-judge-calls 16
# If publication observation times out, SAME run, read-only (no reasks/regrading/republishing):
python tools/rehearse_demo.py --env .env --run-id demo-unique-01 --verify-only --wait-seconds 1200
```

The operator tracks the cumulative approved allowance across controls and the final run; failed/ambiguous
attempts still count. A new run ID is not a new approval. Exit **0** means scripted gates pass (browser gates remain),
**2** means quality FAIL, **3** means runtime ERROR/incomplete evidence or publication, **64** means CLI usage error.

Step by step: [docs/SETUP.md](docs/SETUP.md). Demo script: [docs/DEMO.md](docs/DEMO.md). How it fits together:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## What gets recorded

Every row carries `RunId`, and ask-level rows carry `AskId`, so a Copilot ask, its DAX, its scores and its timings
join on one key.

| Table | One row per |
|---|---|
| `EvalRun` | run: option, golden set hash, pass rate, accuracy, latency p50/p95, Foundry report link |
| `EvalQuestion` | golden question per run (a snapshot of what was expected) |
| `EvalAsk` | ask: answer, citations, Copilot's own explanation, latency (streamed while the run is in progress) |
| `FabricIqQuery` | DAX query Fabric IQ ran for an ask: semantic model, duration, offset from the ask, DAX text |
| `EvalScore` | check per ask per option: value, artifact, model, judge, Foundry evaluators |
| `EvalResult` | ask per option: verdict, scores, routing, DAX and latency in one wide row (what the app reads) |
| `EvalEvent` | harness stage timing: ask, follow-up, trace wait, scoring, publish |

Metric definitions: [docs/METRICS.md](docs/METRICS.md). Ready-made KQL: [`kql/queries.kql`](kql/queries.kql).

## Repository layout

```
src/cfeval/          Python package: harness, scorers, DAX capture, Foundry integration, CLI
  kql/functions.kql  KQL functions created in the Eventhouse
kql/                 setup.kql (generated) and queries.kql
data/golden/         golden question set (Contoso sample)
notebooks/           00 offline quickstart, 01 Eventhouse setup, 02 Option 1, 03 Option 2
app/                 Fabric app scorecard: overlay, entity generator, standalone preview
docs/                architecture, setup, demo, metrics, troubleshooting
tools/               setup_demo.py, rehearse_demo.py, app-contract generator
```

## Acceptance, not a production test platform

**The documented scripted live demo is the acceptance test.** CI has one small offline mock smoke, generated-file
checks and app typecheck/build; there is no unit-test framework or Python-version matrix.
The rehearsal compares exact counts from the **current run JSONL**, including row versions, against all seven
Eventhouse tables and the five SQL shortcut tables. Zero DAX/scores, missing why turns, incomplete check coverage
and late publication cannot become success. The bounded `--verify-only` route observes publication, not traces.
OneLake's five-minute minimum setting is **not** a hard upper bound; tables arrive independently.

Known limits and fixes: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Evidence gaps / still thin

- The Chat API's use of Fabric IQ must be proved in your tenant; an owner DAX query or a simulated run is not that proof.
- User/time-window DAX correlation is observational. A watermark and a quiet collection window do not guarantee
  exhaustive logs. Missing, disabled or unsettled required evidence never produces a `PASS`.
- A built standalone is not a deployed Fabric app. Check actual SSO, SQL connector reads and
  completeness after OneLake propagation; sample history is always labelled separately.

## Contributing, security, support

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and [SUPPORT.md](SUPPORT.md). Use synthetic or
public sample data in issues and pull requests: never customer data, tenant IDs or secrets.

## Trademarks

Microsoft, Microsoft 365, Copilot, Microsoft Fabric, Power BI and Azure are trademarks of the Microsoft group of
companies. Use of Microsoft trademarks or logos must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Contoso is a fictional company used for sample data.
