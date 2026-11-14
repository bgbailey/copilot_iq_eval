# Cost and Operational Limits

Running `cfeval` offline (`--mock` or `--target transcript-import`) incurs **zero** cloud cost, zero token spend, and completes a 42-question suite in under two seconds. Before running live evaluations in a demo tenant and demo Azure subscription, plan for the Fabric capacity, Eventhouse storage, optional judge model tokens, and wall-clock durations below.

## Fabric Capacity Consumption

Live Fabric IQ evaluations consume Capacity Units (CU) on the Microsoft Fabric capacity (`F2` or higher) backing your semantic models and Eventhouses:

| Workload | Capacity Driver | Operational Guidance |
|---|---|---|
| **Semantic model DAX execution** | Each Copilot Chat turn triggers one or more `QueryEnd` DAX evaluations on the target semantic model (`CpuTimeMs` logged in `SemanticModelLogs`). Running `cfeval golden-refresh` also executes each case's `reference_dax` once via Power BI `executeQueries`. | Reuse existing demo-tenant workspaces and pause dedicated dev/demo capacities between evaluation windows using bounded capacity leases—never delete workspaces as a cost-control shortcut. |
| **Workspace Monitoring (`SemanticModelLogs`)** | [Fabric Workspace Monitoring](https://learn.microsoft.com/en-us/fabric/fundamentals/workspace-monitoring-overview) continuously ingests semantic model operation logs into a workspace Eventhouse with a **30-day default retention window**, consuming minor background Eventhouse ingestion and OneLake storage CU. | Share a monitoring Eventhouse across evaluated workspaces where supported, keep default 30-day hot retention for raw engine logs, and persist curated run history in the lightweight telemetry Eventhouse. |
| **Telemetry Eventhouse (`Eval*` tables)** | `cfeval publish` / `cfeval run` ingests seven compact tables (`EvalRun`, `EvalQuestion`, `EvalAsk`, `FabricIqQuery`, `EvalScore`, `EvalResult`, `EvalEvent`) at the end of a run. | Negligible CU impact; queries run only when rendering live scorecards or `cfeval compare`. |

## Eventhouse Storage Footprint

Local `runs/<run_id>/` artifacts and telemetry Eventhouse rows store text prompts, Copilot answers, citation JSON, and correlated DAX strings:

* **`EvalQuestion` + `EvalAsk` + `EvalScore` + `EvalResult`**: ~`3`–`8 KB` uncompressed per evaluated turn.
* **`FabricIqQuery`**: ~`1`–`4 KB` per correlated `QueryEnd` DAX query (`1`–`3` queries per typical Copilot turn).
* **Sizing rule of thumb**: A 50-question suite at `K = 3` trials (`150` turns) writes **< 2 MB** uncompressed (~`200`–`400 KB` compressed in Eventhouse / OneLake). Even 500 historical runs occupy well under `1 GB`.

## Optional Judge Model Token Estimates

Deterministic Layers 1–4 (`--scorer fabric-native`, the default) execute locally in Python and consume **0 LLM tokens**.

When optional Layer 5 LLM-as-judge (`--judge` or `--scorer foundry`) is enabled against a model deployment in your demo Azure subscription:

* **Per judged turn**: ~`700`–`1,200` input tokens (system rubric + question + expected intent + Copilot response + citations) and ~`120`–`250` output tokens (structured JSON reason + score).
* **Example suite budgets**:

| Suite Size | Trials (`K`) | Total Judged Turns | Est. Input Tokens | Est. Output Tokens |
|---|---:|---:|---:|---:|
| Smoke (`8` cases) | `1` | `8` | `6K` – `10K` | `1K` – `2K` |
| Prototype (`42` cases) | `1` | `42` | `30K` – `50K` | `5K` – `11K` |
| Prototype (`42` cases) | `3` | `126` | `90K` – `150K` | `15K` – `32K` |
| Production (`100` cases) | `3` | `300` | `210K` – `360K` | `36K` – `75K` |

Use `cfeval rescore runs/<run_id>` whenever iterating on deterministic tolerances so you neither re-invoke Copilot Chat nor re-spend judge tokens.

## Expected Wall-Clock Duration

Live Copilot Chat evaluations execute sequentially for a given test user to avoid Microsoft Graph throttling and keep `SemanticModelLogs` time-window correlation unambiguous:

$$\text{Duration} \approx N \times K \times (\bar{L}_{\text{turn}} + t_{\text{pause}}) + t_{\text{trace\_wait}}$$

Where:

* $N$ = number of questions in the golden suite
* $K$ = trials per question (`--repeats`, default `1`; `3` recommended before release gates)
* $\bar{L}_{\text{turn}}$ = mean Copilot Chat turn latency (typically `8`–`25 s` for semantic model queries)
* $t_{\text{pause}}$ = `CFEVAL_PAUSE_SECONDS` (default `20 s` cooldown between turns in `.env.example`, configurable down to `2`–`5 s` on unthrottled smoke runs)
* $t_{\text{trace\_wait}}$ = `CFEVAL_TRACE_WAIT_SECONDS` / `CFEVAL_TRACE_SETTLE_SECONDS` (post-run buffer for Workspace Monitoring KQL ingestion)

| Suite Tier | $N \times K$ | Typical Live Wall-Clock Duration |
|---|---:|---|
| Quick smoke (`8 × 1`) | `8` turns | `3` – `5` minutes |
| Standard benchmark (`42 × 1`) | `42` turns | `12` – `20` minutes |
| Multi-trial release check (`42 × 3`) | `126` turns | `35` – `55` minutes |
| Production benchmark (`100 × 3`) | `300` turns | `85` – `130` minutes |

## Platform and Rate Limits

* **Copilot Chat `/beta` preview throttling**: Microsoft Graph enforces per-user and per-tenant concurrency and rate limits (`HTTP 429` with `Retry-After`). `cfeval` honors `Retry-After` with bounded exponential backoff; do not run parallel live harnesses under the same `eval.tester@contoso.com` account.
* **Concurrent model activity**: Other users or scheduled refreshes running as the same identity during `cfeval run` reduce `CorrelationConfidence` from `high` to `medium` or `low`.
* **Microsoft Foundry custom code evaluator limits**: When exporting pure-stdlib scorers (`src/cfeval/scorers.py`) to Foundry cloud evaluations, Foundry enforces `< 256 KB` code bundle size, `2` minutes maximum per invocation, `2 GB` memory, and zero outbound network access ([Custom evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/custom-evaluators)).

## Related Guides

* [Prerequisites](./prerequisites.md)
* [First Live Run](./first-live-run.md)
* [Platform Status](../reference/platform-status.md)
* [Threat Model](../responsible-use/threat-model.md)
