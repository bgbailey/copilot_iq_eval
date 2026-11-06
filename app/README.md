# Scorecard app (Fabric Apps)

A Fabric app that shows how Copilot Chat performs on the golden set: accuracy, routing, the DAX Fabric IQ ran, and
latency. It reads the evaluation tables from a lakehouse SQL analytics endpoint (the Eventhouse tables, shortcut
through OneLake availability) and signs viewers in with Fabric SSO.

| Page | What it shows |
|---|---|
| Overview | Pass rate, correct value, right report cited, right model queried, decoy rate, latency, DAX per ask; pass-rate trend and verdicts by run; why asks fail; expected vs queried semantic models |
| Questions | Each golden question's latest verdict, pass rate, routing stability and value spread. Select one to see Copilot's answer, citations, its own explanation, the judge's notes, an ask timeline and the DAX text |
| Performance | Answer latency trend and distribution, independent answer/why round trips vs captured DAX work per question, harness stage timings, the slowest DAX queries |
| Runs | Every run with its option, data source (live or simulated), accuracy, latency and Foundry report link; Option 1 vs Option 2 agreement |

## Try it locally with sample data (no Fabric needed)

```bash
cd app/standalone
npm ci
npm run dev          # opens the scorecard with app/overlay/public/sample-data/evals.json
```

In `app/standalone`, run `npm run typecheck` and `npm run build`. The standalone forces sample mode and never
signs in. It is not a browser, Fabric sign-in or deployed-connector acceptance test.

Use **Node 24 LTS** for this repository and the Rayfin **1.36.2** scaffold/SDK/CLI.
Rayfin CLI/scaffold 1.36.2 declares the engine range
`>=20.0.0 <21.0.0 || >=22.0.0 <23.0.0 || >=24.0.0 <25.0.0`.
“22.18+” does not mean every newer major is supported: Node 26 is outside that range. The repository's
standalone engine is deliberately restricted to 24.x, which also supports the entity generator's native
TypeScript imports. No multi-version test matrix is needed.

The standalone overrides only the compatible, type-only `@types/estree` patch to **1.0.8**: the newer
transitive 1.0.9 tarball was unavailable during validation, while 1.0.8 was verified obtainable.
The portable lockfile omits registry-resolved URLs (project-local npm setting), so installs use your configured
registry with package integrity checks. No registry address or credential is stored in this source.

## Deploy to Fabric

Prerequisites: **Node 24 LTS**, Rayfin **1.36.2**, the Eventhouse set up with OneLake availability, and the lakehouse
shortcuts (see [docs/SETUP.md](../docs/SETUP.md)). Fabric Apps is a **preview with tenant/region availability gates**;
having npm packages or a standalone build does not establish that hosted Apps is enabled for your tenant.
Use the supported scaffold and publish flow below; this repository is an overlay, not an already deployed app
or a private deployment executor.

1. **Create the app** in a workspace on a Fabric capacity:

   ```bash
   npm create @microsoft/rayfin@1.36.2 -- copilot-eval-scorecard --workspace <workspace id>
   cd copilot-eval-scorecard
   ```

2. **Add the lakehouse connector** named `evals` (read-only):

   ```bash
   npx rayfin connector add --type fabric-sqlanalytics --workspace-id <workspace id> \
     --item-id <lakehouse id> --name evals --operations read
   ```

   Here `--item-id` is the **lakehouse item ID**, not `properties.sqlEndpointProperties.id`.
   The latter identifies the SQL endpoint for SQL-endpoint APIs; the KQL database GUID is a third, different ID.
   Run the pinned `npm install` command it prints. Keep the Rayfin dependencies/CLI on the compatible 1.36.2 line.
   The command discovers the tables into
   `rayfin/connectors/evals/metadata.json`. Discovery must include all five tables and the app's required
   columns. Keep the connector name **`evals`**, which is the client contract.

3. **Apply the overlay** from your clone of this repository:

   ```bash
   node <path to accelerator>/app/scripts/apply-overlay.mjs --project .
   ```

   First it validates the actual discovered metadata, column mappings and React frontend path. Missing,
   incompatible or ambiguous metadata fails **before any project file is copied or replaced**.
   Then it copies `src/eval` and the sample data into the frontend, keeps the template's `App.tsx` as
   `App.template.tsx` and renders the scorecard instead, points `src/eval/connectorSchema.ts` at
   `rayfin/connectors/evals/schema.ts`, and generates the connector entity files from `metadata.json`
   (keyless, read-only, `@role('authenticated', ['read'])`).
   Reapplying intentionally refreshes the supplied overlay; use a separate scaffold folder, not this source tree.

4. **Run it locally** with `npx rayfin dev` if desired. This is a component check, not hosted SSO evidence.

5. **Publish** with `npx rayfin up`, preserving the existing app identity on subsequent publishes. Open the
   published app **through its Fabric portal item**, complete actual hosted SSO in the intended account/tenant,
   and manually check fresh **Overview, Questions, Performance and Runs** with **Live** selected and the new run.
   Keep a persistent same-window task/service/run/tenant/expected-user context before any sign-in; a guessed
   ambient browser account is not identity verification. Set `DEMO_APP_URL` from this actual published link.
   Do not present a local build, sample history, or another operator's existing app as public hosted evidence.

### Who can see what

By default the lakehouse connector reads as the **app identity** (the app item's owner), and anyone you share the
app with sees the evaluation results. To make each viewer's own lakehouse permissions apply instead, set
`auth.type: delegated` on the connector in `rayfin/rayfin.yml` before deploying.

### Settings

| Variable | Default | Meaning |
|---|---|---|
| `VITE_EVAL_DATA` | `auto` | `auto`: live data after sign-in, with a sample-data button; `live`: live only; `sample`: the bundled sample, no sign-in |

The Rayfin template sets `VITE_RAYFIN_API_URL`, `VITE_RAYFIN_PUBLISHABLE_KEY`, `VITE_FABRIC_WORKSPACE_ID`,
`VITE_FABRIC_ITEM_ID` and `VITE_FABRIC_PORTAL_URL`.

## Data freshness

OneLake availability has a **five-minute minimum latency setting, not a hard upper bound**; the SQL analytics
endpoint then picks rows up independently. Do not promise that a complete run appears after five minutes. Use
`LiveAsks()` and the other queries in `kql/queries.kql`.

The five SQL tables can arrive independently. The app keeps known runs and the `EvalQuestion` roster visible
with pending scores, and withholds accuracy when expected per-backend asks, golden questions or run metadata
are absent (or a row cap is reached). An absent score is **not** an invented FAIL/INCONCLUSIVE result.
`tools/rehearse_demo.py --verify-only` checks all five exact per-run counts without asking/regrading/republishing;
the browser checks above remain manual. Simulated history is explicitly labelled, and combined sample/live
aggregates are not the current live rehearsal's score.
The header filters backend, time window and live/simulated history, not an individual run. Use the **Runs**
table's matching run name/ID and its own score/ask counts for the final rehearsal; Overview and Performance
remain historical aggregates within the selected filters.

### Reading the metrics

* **Pass rate and accuracy use backend scores.** An ask scored by both options has two score rows, not two
  Copilot answers. Counts distinguish scores from distinct `(RunId, AskId)` asks; no combined physical verdict is invented.
* **Answer latency counts each non-error ask once**, consistently across the headline, questions and histogram.
  Gate accuracy excludes undecided (`0.5`/null) gate scores; API errors remain separate from inconclusive results.
* **Trace `observed` means heuristic time-window evidence**, after the harness's bounded settling window.
  It does not prove that all queries or their order were captured. `pending`/`missing`/`incomplete`/`error`
  must not become a successful model gate. A positive observed decoy failure stays FAIL even while pending.
  The backend verdict is retained; an `observed` status alone never upgrades an INCONCLUSIVE result.
  Legacy sample status `complete` remains readable. DAX durations sum queries from **both answer and why**;
  they may overlap or exceed answer latency. The chart shows independent measures, never a capped additive split or inferred “other” time.

### Reproducible sample cleanup

After generating a new sample, remove only exact duplicate query/event records:

```bash
node app/scripts/dedupe-sample.mjs
node app/scripts/dedupe-sample.mjs --check
```

The transformer preserves run IDs, ask IDs, score rows, text, timestamps and other observations. It never
queries Fabric or fabricates live records. The loader also removes exact replayed query/event rows.

## How the code is organised

```
overlay/src/App.tsx                  renders the scorecard (replaces the template's App.tsx)
overlay/src/eval/
  EvalApp.tsx                        shell: sign-in, filters, tabs
  pages/                             Overview, Questions, Performance, Runs
  charts.tsx                         dependency-free SVG charts
  metrics.ts, normalize.ts, format.ts  pure logic
  dataSource.ts                      live (connector) and sample loading; the only file that queries data
  loadState.ts                       source-mode and latest-load guards
  rayfinClient.ts, useAuth.ts        Rayfin client and Fabric SSO
  generated/contract.ts              row types and field lists, generated from src/cfeval/schema.py
overlay/public/sample-data/evals.json  simulated runs (python -m cfeval demo-data --app-json ...)
connectors/evals/                    reference copy of the generated connector entities
scripts/apply-overlay.mjs            installs the overlay into a Rayfin project
scripts/generate-entities.mjs        writes connector entities from metadata.json
scripts/dedupe-sample.mjs            explicit duplicate-only sample transformer
standalone/                          local preview with sample data
```

When the telemetry schema changes: run `python tools/gen_app_contract.py`, regenerate the reference entities with
`node app/scripts/generate-entities.mjs --metadata app/connectors/evals/metadata.example.json --out app/connectors/evals`,
and in your app refresh the connector metadata and re-run `apply-overlay.mjs`.
`metadata.example.json` is generated fictional schema metadata for the reference entities; never use it instead
of live connector discovery when publishing.

When the Rayfin KQL connector is available for new projects, `dataSource.ts` can query the Eventhouse directly for
live data without the OneLake delay.

## Evidence gaps / still thin

The public overlay/build is not a promise of preview tenant availability, actual hosted SSO or fresh SQL reads.
Those are manual gates in the documented scripted live demo, which is the acceptance test.
