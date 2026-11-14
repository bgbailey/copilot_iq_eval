# First Live Run

This guide walks through the smallest end-to-end live evaluation (`8` smoke questions, `1` trial per question) against a demo tenant (`contoso.com`) and renders an HTML scorecard report.

Before starting, confirm all licence, dedicated test user (`eval.tester@contoso.com`), and Workspace Monitoring requirements in [Prerequisites](./prerequisites.md).

## 1. Install Live Extras and Configure `.env`

Install `cfeval` with live Microsoft Entra, Kusto, and HTTP dependencies, then copy `.env.example` to `.env` (which is gitignored):

```bash
pip install -e ".[live]"
cp .env.example .env
```

Edit `.env` with your demo-tenant and demo Azure subscription settings:

```dotenv
# Expected Entra identity guardrails (verified before every live call)
CFEVAL_TENANT_ID=00000000-0000-0000-0000-000000000000
CFEVAL_TENANT_LABEL=Contoso Demo / contoso.com
CFEVAL_OPERATOR_UPN=eval.operator@contoso.com
CFEVAL_TEST_USER_UPN=eval.tester@contoso.com
CFEVAL_CLIENT_ID=00000000-0000-0000-0000-000000000001

# Telemetry Eventhouse (stores EvalRun, EvalQuestion, EvalAsk, FabricIqQuery, EvalScore, EvalResult, EvalEvent)
CFEVAL_EVENTHOUSE_WORKSPACE_ID=00000000-0000-0000-0000-000000000002
CFEVAL_EVENTHOUSE_QUERY_URI=https://trd-telemetry.z0.kusto.fabric.microsoft.com
CFEVAL_EVENTHOUSE_INGEST_URI=https://ingest-trd-telemetry.z0.kusto.fabric.microsoft.com
CFEVAL_EVENTHOUSE_DATABASE=CopilotEvalTelemetry

# Workspace Monitoring Eventhouse (reads SemanticModelLogs QueryEnd events)
CFEVAL_MONITORING_QUERY_URI=https://trd-monitoring.z0.kusto.fabric.microsoft.com
CFEVAL_MONITORING_DATABASE=WorkspaceMonitoring
CFEVAL_SEMANTIC_MODEL_WORKSPACE_ID=00000000-0000-0000-0000-000000000003
```

## 2. Run Strict Preflight Checks

Validate configuration variables, installed packages, golden-suite schema, and endpoint configuration without modifying tenant state:

```bash
cfeval doctor --strict
```

Fix any `FAIL` or `WARN` items reported by `doctor` before signing in. See [Configuration Reference](../reference/configuration.md) for every environment variable.

## 3. Sign In and Verify Token Claims

Authenticate interactively as your dedicated test account and confirm the acquired token matches `CFEVAL_TENANT_ID` and `CFEVAL_TEST_USER_UPN`:

```bash
cfeval login
```

`cfeval login` inspects the JWT `tid` and `upn` / `preferred_username` claims across Microsoft Graph and Fabric/Kusto scopes. If a cached browser session belongs to another user or tenant, `cfeval` aborts with exit code `4` instead of issuing calls under the wrong identity.

## 4. Bootstrap the Telemetry Eventhouse

Apply idempotent `.create-merge table` and `.create-or-alter function` DDL (`EvalRun`, `EvalQuestion`, `EvalAsk`, `FabricIqQuery`, `EvalScore`, `EvalResult`, `EvalEvent`, and deduplicated KQL functions) to your telemetry Eventhouse:

```bash
cfeval setup
```

To inspect the generated KQL DDL offline before applying it, run `cfeval kql --out kql/setup.kql`.

## 5. Run the Smallest Strict Live Evaluation

Execute the 8-question Contoso smoke suite (or your own calibrated YAML suite) with strict gating enabled:

```bash
cfeval run --strict --golden data/golden/contoso-smoke.yaml --run-id first-live-smoke
```

During execution, `cfeval`:

1. Verifies the signed-in identity against your `.env` guardrails.
2. Opens a fresh Microsoft 365 Copilot Chat conversation per question (`POST /beta/copilot/conversations` -> `/chat`) so prior turns cannot contaminate context.
3. Waits for Workspace Monitoring ingestion (`CFEVAL_TRACE_WAIT_SECONDS`) and correlates `SemanticModelLogs` `QueryEnd` DAX events back to each turn window.
4. Evaluates deterministic value, citation/artifact, semantic-model routing, and decoy-avoidance gates.
5. Writes reproducible local artifacts under `runs/<run_id>/` and publishes idempotently to Eventhouse using deterministic `RowId` keys.

Exit codes follow [CLI Exit Codes](../reference/exit-codes.md) (`0` all active gates passed, `2` release gate threshold failed, `3` inconclusive/error evidence under `--strict`).

## 6. Generate an HTML Scorecard Report

Render a self-contained, offline-viewable HTML report from the completed run directory:

```bash
cfeval report runs/first-live-smoke --out report.html
```

Open `report.html` in any browser to inspect overall Wilson 95% confidence intervals, evidence-tier badges (`engine+citations` vs `citations-only`), extracted vs expected values, and captured DAX per question.

## Next Steps

* [Author a Golden Set](../how-to/author-a-golden-set.md) — create a YAML suite tailored to your own semantic models and `reference_dax` queries.
* [Capture Engine DAX](../how-to/capture-dax.md) — tune Workspace Monitoring windows and filter background index queries.
* [Compare Runs and Gate CI](../how-to/compare-runs-and-gate-ci.md) — run paired baseline-vs-candidate comparisons with exact McNemar $p$-values.
* [Troubleshoot](../how-to/troubleshoot.md) — diagnose `INCONCLUSIVE` verdicts, monitoring lag, or Copilot model settings.
