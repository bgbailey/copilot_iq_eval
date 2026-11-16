# Troubleshoot Common Issues

Start any diagnosis with strict preflight validation:

```bash
cfeval doctor --strict
```

Below are the root causes and fixes for the most common live setup, authentication, routing, Monitoring KQL, and Python dependency issues.

## 1. Token Claim Mismatch (`Exit Code 4` on `cfeval login` or `cfeval run`)

**Symptom**: `cfeval` aborts before issuing Graph or Kusto requests with an identity mismatch error (`tid` or `upn` does not match `CFEVAL_TENANT_ID` / `CFEVAL_OPERATOR_UPN` / `CFEVAL_TEST_USER_UPN`).

**Cause**: Your active CLI profile or cached MSAL token belongs to a corporate employee account or a different tenant rather than your dedicated synthetic test user (`eval.tester@contoso.com`). `cfeval` intentionally refuses to silently switch accounts or send prompts under an unverified identity.

**Fix**:

1. Sign in explicitly to the target demo tenant as your synthetic evaluation user (and isolate Azure CLI state to a dedicated `CFEVAL_AZURE_CONFIG_DIR=.azure-eval` folder when working across multiple tenants or concurrent terminal sessions):
   ```bash
   cfeval login
   ```
2. Confirm `CFEVAL_TENANT_ID`, `CFEVAL_OPERATOR_UPN`, `CFEVAL_TEST_USER_UPN`, and `CFEVAL_TENANT_LABEL` in `.env` match the intended demo-tenant identities.

## 2. Copilot Ignores a Semantic Model or Returns "I Couldn't Find That Data" (`R10`)

**Symptom**: `copilot-chat` fails `value` and `artifact` checks on unqualified prompts, or fails to discover a published semantic model even though `eval.tester@contoso.com` has workspace access.

**Cause**: Per-model Copilot discovery settings or tenant switches exclude restricted or unconfigured models from cross-model search ([Copilot settings for semantic models](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-semantic-models)).

**Fix**:

1. Confirm Fabric / Power BI Copilot tenant settings are enabled for the security group containing `eval.tester@contoso.com`.
2. Open the semantic model's **Settings -> Copilot** in Fabric and verify Copilot is enabled (and that the model is **Approved for Copilot** / Promoted or Certified if your tenant restricts discovery to approved items).
3. Ensure `eval.tester@contoso.com` holds **Viewer** + **Build** (or Read + Reshare) permissions on the semantic model and passes any configured RLS role rules.
4. Note that Power BI **verified answers** can be bypassed when queries traverse Fabric IQ in Microsoft 365 Copilot Chat ([Ask Copilot for data from semantic models](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-ask-data-question)); define clear DAX measures, descriptions, and synonyms on the model itself.

## 3. `INCONCLUSIVE` Model Gate / `CorrelationConfidence = none` (Workspace Monitoring Lag)

**Symptom**: Answer values and citations match (`ValuePass = 1`, `ArtifactPass = 1`), yet `RoutingEvidence` stays `citations-only`, `CorrelationConfidence` is `none`, and strict runs exit with code `3`.

**Cause**: Either Fabric Workspace Monitoring is not enabled on the model's workspace, `SemanticModelLogs` ingestion lagged past `CFEVAL_TRACE_WAIT_SECONDS` (common during cold capacity startup), or `CFEVAL_MONITORING_QUERY_URI` points to the telemetry Eventhouse instead of the workspace monitoring Eventhouse.

**Fix**:

1. Run `cfeval trace probe` to verify KQL read permissions on `SemanticModelLogs` and measure live ingestion delay.
2. Increase `CFEVAL_TRACE_WAIT_SECONDS` and `CFEVAL_TRACE_SETTLE_SECONDS` in `.env`.
3. Re-hydrate engine traces and rescore your existing run directory without re-sending Copilot prompts:
   ```bash
   cfeval rescore runs/<run_id>
   ```
4. If Workspace Monitoring cannot be enabled in that environment, pass `--gate-profile without_engine_evidence` (or configure `gates: [value, artifact]`) so scorecards grade at the `citations-only` tier transparently.

## 4. `CorrelationConfidence = low` on Engine Traces

**Symptom**: `SemanticModelLogs` rows are captured, but `CorrelationConfidence` drops to `low`.

**Cause**: Concurrent queries executed under the same `ExecutingUser` (`eval.tester@contoso.com`) during the turn window.

**Fix**: Do not run parallel `cfeval run` processes or interactive Power BI report sessions under `eval.tester@contoso.com` at the same time, and keep `CFEVAL_PAUSE_SECONDS >= 5`.

## 5. `pip` Dependency Conflict: `fabric-data-agent-sdk` vs. `azure-ai-projects` (`openai` Version Split)

**Symptom**: Installing both `.[foundry]` and `.[fabric-data-agent]` into a single virtual environment fails in `pip`'s resolver over `openai`.

**Cause**: Upstream PyPI packages currently pin incompatible major versions of `openai`: `azure-ai-projects` (`>= 2.0`) requires `openai >= 3`, whereas `fabric-data-agent-sdk` (`0.1.x` preview) pins `openai < 3` (see [Platform Status](../reference/platform-status.md)).

**Fix**:

* Keep `cfeval` core + live extras (`pip install -e ".[live]"`) in your primary environment—neither conflicting SDK is required for `copilot-chat`, `fabric-iq-mcp`, `transcript-import`, Workspace Monitoring KQL, or REST-based judge calls.
* When using the optional `fabric-data-agent` target or `azure-ai-projects` Foundry cloud SDK, install each extra in its own isolated virtual environment (`python -m venv .venv-data-agent` vs. `python -m venv .venv-foundry`), then score or compare the resulting `runs/<run_id>/` directories together.

## 6. SQL Analytics Endpoint / Scorecard Lags Behind Eventhouse or `rayfin connector add` Discovers 0 Tables

**Symptom**: Eventhouse KQL queries show newly ingested `EvalRun` / `EvalResult` rows (or newly added `v0.2` columns), while the Lakehouse SQL analytics endpoint (`dbo.Eval*`) or hosted scorecard app still serves older row counts, or `npx rayfin connector add` discovers `0` tables.

**Cause**:

1. Eventhouse exports to OneLake `_delta_log` asynchronously (~1–3 minutes), and the Lakehouse SQL analytics endpoint caches table/column metadata until `sqlEndpoints/{id}/refreshMetadata` runs.
2. `npx rayfin connector add --type fabric-sqlanalytics --item-id` requires `SQL_ENDPOINT_ID` (`properties.sqlEndpointProperties.id`), **not** `LAKEHOUSE_ID` (and on corporate Windows TLS networks Node.js may reject TLS inspection certificates unless `NODE_USE_SYSTEM_CA=1` is set).

**Fix**:

1. Run `cfeval sync-sql` (or `cfeval publish <run_dir> --sync-sql` / `python tools/setup_demo.py --env .env --sync-sql --apply`) to poll OneLake Delta commits and refresh the SQL analytics endpoint metadata.
2. Keep `EVENTHOUSE_DATABASE_ID` (KQL DB item GUID; note `EVENTHOUSE_DATABASE` is often this GUID in Kusto), `LAKEHOUSE_ID` (for shortcuts), and `SQL_ENDPOINT_ID` (for `sync-sql` and `rayfin connector add --item-id`) distinct in `.env`, and set `NODE_USE_SYSTEM_CA=1` when running `npx rayfin`.

## 7. Cold Direct Lake Timeouts Immediately After Resuming Capacity

**Symptom**: Right after resuming a paused demo Fabric capacity, the first 1–2 Copilot Chat questions time out or miss measures while Direct Lake frames load into memory.

**Fix**: Run `cfeval golden-refresh --golden data/golden/contoso-smoke.yaml` before `cfeval run` or `tools/rehearse_demo.py` to verify expected ground-truth values and warm Direct Lake semantic models in memory.

## Related Pages

* [Capture Engine DAX](./capture-dax.md)
* [Platform Status](../reference/platform-status.md)
* [CLI Exit Codes](../reference/exit-codes.md)
