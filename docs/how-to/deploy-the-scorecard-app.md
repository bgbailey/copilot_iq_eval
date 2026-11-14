# Deploy the Scorecard App

Every `cfeval` run already produces a self-contained HTML scorecard via `cfeval report <run-dir> --out report.html` with zero Node.js or Fabric App dependencies. When you want a persistent, multi-run interactive experience backed by your telemetry Eventhouse—or a local browser preview over synthetic Contoso runs—use the optional React scorecard overlay in [`../../app/README.md`](../../app/README.md).

> **Preview notice**: Native **Fabric Apps** hosting is a Microsoft Fabric preview capability (see [Platform Status](../reference/platform-status.md)). Keep the standalone Vite preview and `cfeval report` HTML output as your zero-dependency baseline.

## Option 1: Standalone Local Preview (100% Offline)

Run the scorecard UI locally against bundled synthetic Contoso runs (`app/overlay/public/sample-data/evals.json`) without any cloud connection:

```bash
npm --prefix app/standalone ci
npm --prefix app/standalone test
npm --prefix app/standalone run dev
```

Open the printed localhost URL to inspect:

* **Executive Overview**: `PassRate`, Wilson 95% confidence intervals, `pass@1` / `pass^k`, and `RoutingEvidence` breakdown (`engine+citations`, `tool_call`, `citations-only`, `unverified`).
* **Baseline vs. Candidate Diff**: Paired improvements, regressions, and exact McNemar $p$-values.
* **Turn & DAX Inspector**: Side-by-side prompt, answer, extracted vs. expected value (`MatchKind`), cited artifacts, and captured `SemanticModelLogs` DAX (`LatencyMs`, `DaxTotalMs`, `DaxCpuMs` shown non-additively).

## Refresh Synthetic Sample Data (`cfeval demo-data --as-of`)

To regenerate deterministic multi-run sample data anchored to a reproducible timestamp (`--as-of`) and verify no duplicate `RowId` records exist:

```bash
cfeval demo-data --as-of 2026-11-13T12:00:00Z --app-json app/overlay/public/sample-data/evals.json
node app/scripts/dedupe-sample.mjs --check
```

Pinning `--as-of` guarantees byte-reproducible timestamps and `RunId` digests across developer machines and CI checks.

## Option 2: Connect to a Telemetry Eventhouse in a Fabric App

To host the overlay against live `EvalRun`, `EvalQuestion`, `EvalAsk`, `FabricIqQuery`, `EvalScore`, `EvalResult`, and `EvalEvent` tables in a demo tenant:

1. Bootstrap the telemetry Eventhouse tables and Lakehouse shortcuts (`cfeval setup`).
2. Verify contract synchronization between Python (`src/cfeval/schema.py`) and TypeScript (`app/overlay/src/eval/generated/contract.ts`):
   ```bash
   python tools/gen_app_contract.py
   ```
3. Follow the step-by-step connector entity generation and overlay assembly instructions in [`app/README.md`](../../app/README.md):
   ```bash
   node app/scripts/generate-entities.mjs \
     --metadata app/connectors/evals/metadata.example.json \
     --out app/connectors/evals
   ```
4. Grant scorecard viewers read-only access to the telemetry Eventhouse / Lakehouse only after reviewing [Threat Model](../responsible-use/threat-model.md)—remember that `EvalAsk`, `EvalResult`, and `FabricIqQuery` contain evaluation answers and DAX query text.

## Related Pages

* [Scorecard App Package (`app/README.md`)](../../app/README.md)
* [Telemetry Schema Reference](../reference/telemetry-schema.md)
* [Platform Status](../reference/platform-status.md)
