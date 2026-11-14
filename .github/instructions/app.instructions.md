---
applyTo: "app/**"
---

# Scorecard app conventions (`app/`)

- Target Node 24 LTS (Node 22+ compatible) and strict TypeScript.
- Keep pure logic in `app/overlay/src/eval/` (`metrics.ts`, `normalize.ts`, `format.ts`, `loadState.ts`) using type-only imports and zero DOM or host-SDK side effects so `node --test` runs directly on them.
- Metric definitions in `metrics.ts` must match `src/cfeval/pipeline.py` (`run_metrics`), `src/cfeval/stats.py`, and `src/cfeval/kql/functions.kql`. Update both sides together and keep cross-language parity fixtures green.
- Never edit `app/overlay/src/eval/generated/contract.ts`, `app/connectors/evals/metadata.example.json`, or generated entity files (`app/connectors/evals/*.ts`) by hand; regenerate them from `src/cfeval/schema.py` (`python tools/gen_app_contract.py` and `node app/scripts/generate-entities.mjs`).
- Sample data comes from `python -m cfeval demo-data --as-of <timestamp> --app-json app/overlay/public/sample-data/evals.json` with a fixed seed; do not hand-edit `evals.json`.
- The app makes zero analytics or third-party network calls.
- Verify with `npm --prefix app/standalone run typecheck`, `npm --prefix app/standalone test`, `npm --prefix app/standalone run build`, and `node app/scripts/dedupe-sample.mjs --check`.
