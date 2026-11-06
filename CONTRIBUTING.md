# Contributing

Contributions are welcome: bug fixes, scorer improvements, new checks, docs and app pages.

## Development setup

```bash
git clone https://github.com/bgbailey/copilot_iq_eval
cd copilot_iq_eval
python -m pip install -e .
python tools/rehearse_demo.py --mock --run-id offline-change-01 --questions Q01,Q03 --max-questions 2 --max-judge-calls 4
cd app/standalone
npm ci
npm run typecheck
npm run build
```

Use Node 24 LTS. The one mock smoke is offline and cannot sign in or call cloud services.
**The documented scripted live demo is the acceptance test.** Do not add a unit-test framework, broad test suites,
multi-version matrices or production orchestration. Preserve product scorers and runtime integrity/identity guards.

## Ground rules

* **Synthetic data only.** Contoso samples, never customer names, tenant IDs, user names or real answers.
* **One schema.** Table changes go in `src/cfeval/schema.py`. Then regenerate:
  `python tools/gen_app_contract.py`, `python -m cfeval kql --out kql/setup.kql`, and
  `node app/scripts/generate-entities.mjs --metadata app/connectors/evals/metadata.example.json --out app/connectors/evals`.
  CI fails when a generated file is stale.
* **Scorers stay standard-library only.** `src/cfeval/scorers.py` is bundled into Microsoft Foundry code evaluators,
  which have no network access and a limited package set.
* **Keep the app logic pure.** `metrics.ts`, `normalize.ts` and `format.ts` have no runtime imports.
* Update related docs and verify the narrow affected offline/build path. Live evidence needs explicit bounded
  approval; never silently repeat paid questions, judges or Foundry dataset runs.

## Pull requests

Describe the change and how you tested it. If it changes what's recorded or how a verdict is decided, say so in the
description and update `docs/METRICS.md`.
