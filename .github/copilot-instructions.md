# Instructions for GitHub Copilot in this repository

This repository evaluates Microsoft 365 Copilot Chat answers that come from Power BI semantic models through
Fabric IQ. A Python harness (`src/cfeval`) asks golden questions through the Copilot Chat API, captures the DAX
from Fabric workspace monitoring, scores answers (Option 1: Python checks plus a Foundry-hosted judge model;
Option 2: Microsoft Foundry Evaluations), and writes telemetry to a Fabric Eventhouse. A Fabric app (`app/`)
shows the results.

## Conventions
- Python 3.10+, standard library plus `requests` at import time; import optional SDKs (msal, azure-kusto,
  openai, azure-identity, azure-ai-projects) lazily inside functions so offline runs and tests need nothing else.
- `src/cfeval/scorers.py` must stay standard-library only: it is bundled into Foundry code evaluators.
- Table schemas live only in `src/cfeval/schema.py`. Regenerate `kql/setup.kql`, the app contract
  (`python tools/gen_app_contract.py`) and the reference connector entities after any change.
- Keep this a lean community accelerator, not a production testing platform. The documented, scripted live
  demo is the acceptance test. Do not add broad unit-test suites, test matrices or production scaffolding.
  Keep runtime identity, evidence-integrity and error guards; use only essential build/offline smoke checks.
- App logic in `metrics.ts`, `normalize.ts` and `format.ts` stays free of runtime imports (type-only imports).
- Use Contoso sample names. Describe environments generically ("demo tenant", "demo Azure subscription").
- User-facing text is plain and specific; KQL and Python identifiers keep their existing naming.
