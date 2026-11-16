# Troubleshooting

Common issues across authentication, Copilot Chat responses, Workspace Monitoring correlation, scoring tolerances, and reporting.

## 1. Authentication & Microsoft Graph Copilot Chat API

| Symptom | Likely Cause | Resolution |
|---|---|---|
| `401 Unauthorized` or `403 Forbidden` on `beta/copilot/conversations` | Missing Microsoft 365 Copilot license on test user or unconsented Graph delegated scopes | Confirm `eval.tester@contoso.com` holds an active M365 Copilot license and your Entra public-client app has delegated Graph permissions consented for the test tenant. |
| Interactive browser signs into the wrong corporate account | Default browser profile is cached to another tenant | Use explicit tenant authority (`CFEVAL_TENANT_ID`) and login hint (`CFEVAL_TEST_USER_UPN`), verify the signed-in UPN + tenant ID before proceeding, or use an isolated browser profile. |
| `429 Too Many Requests` during large suites | Copilot Chat per-user rate limiting | Increase `CFEVAL_PAUSE_SECONDS` between turns (for example `5`–`10`s) or split long paraphrase runs across batches. |

## 2. Fabric Workspace Monitoring (`kql`) Correlation

| Symptom | Likely Cause | Resolution |
|---|---|---|
| `routing_evidence_tier` falls back to `citations-only` with 0 matched DAX queries | Monitoring ingestion lag (`SemanticModelLogs` typically takes 30–180s, longer on cold Eventhouse) or monitoring is off on the model's workspace | Enable **Log workspace activity** on every workspace hosting expected/decoy models (setting `CFEVAL_MONITORING_SOURCES` when models span multiple workspaces) and increase `CFEVAL_TRACE_WAIT_SECONDS` (for example `240`). |
| Multiple candidate DAX queries match a single ask | Concurrent activity by the same `eval.tester@contoso.com` account during the run window | Reserve a dedicated evaluation user account and avoid manual Power BI report browsing under that identity while a run is active. |
| Kusto query fails with `Forbidden` or database not found | Runner identity lacks read access on the Workspace Monitoring Eventhouse, or `CFEVAL_EVENTHOUSE_DATABASE` uses the portal display name instead of the engine `databaseName` GUID | Grant Database Viewer on the Workspace Monitoring KQL database to the identity running `cfeval` and set `CFEVAL_EVENTHOUSE_DATABASE` to `properties.databaseName`. |

## 3. Scoring & Golden Set Mismatches

| Symptom | Likely Cause | Resolution |
|---|---|---|
| `value` gate fails on a rounded answer (`$12.8M` vs `12840000`) | Tolerance narrower than display rounding or missing `unit: currency` | Set `unit: currency` (enables display-aware half-ULP tolerance) or configure `rel_tol: 0.005` / `display_tol: 0.01` / `abs_tol` in your golden YAML. |
| Source semantic model refreshed and numbers legitimately changed | Golden `expected` value reflects an older snapshot | Run `python -m cfeval golden-refresh --golden data/golden/contoso.yaml` to execute each case's `reference_dax` directly against the certified semantic model before re-scoring. |
| `model` gate shows `not_applicable` / `INCONCLUSIVE` | Target ran without engine telemetry (`transcript-import`, `work-iq`, or `--no-trace`) | Expected behavior for `citations-only` / `unverified` evidence tiers; configure `CFEVAL_MONITORING_QUERY_URI` when semantic-engine proof is required, or use `--gate-profile without_engine_evidence`. |

## 4. Eventhouse Publication, OneLake Shortcuts & SQL Endpoint Sync

- **OneLake shortcut propagation & SQL metadata cache:** Newly ingested Eventhouse rows export to OneLake `_delta_log` within ~1–3 minutes, and Lakehouse SQL analytics endpoints cache schema/snapshots until refreshed. Run `python -m cfeval sync-sql` (or `cfeval publish <run-dir> --sync-sql`) to refresh `SQL_ENDPOINT_ID` metadata immediately, and pass `SQL_ENDPOINT_ID` (not `LAKEHOUSE_ID`) to `npx rayfin connector add --item-id`. Local HTML reports (`python -m cfeval report runs/<id>`) render immediately from local JSONL with zero propagation wait.
