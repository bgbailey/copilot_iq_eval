# Troubleshooting

Common issues across authentication, Copilot Chat responses, Workspace Monitoring correlation, scoring tolerances, and reporting.

## 1. Authentication & Microsoft Graph Copilot Chat API

| Symptom | Likely Cause | Resolution |
|---|---|---|
| `401 Unauthorized` or `403 Forbidden` on `beta/copilot/conversations` | Missing Microsoft 365 Copilot license on test user or unconsented Graph delegated scopes | Confirm `eval.tester@contoso.com` holds an active M365 Copilot license and your Entra public-client app has delegated Graph permissions consented for the test tenant. |
| Interactive browser signs into the wrong corporate account | Default browser profile is cached to another tenant | Use explicit tenant authority (`CFEVAL_TENANT_ID`) and login hint (`CFEVAL_TEST_USER_UPN`), verify the signed-in UPN + tenant ID before proceeding, or use an isolated browser profile. |
| `429 Too Many Requests` during large suites | Copilot Chat per-user rate limiting | Increase `--cooldown-seconds` between turns (for example `5`–`10`s) or split long paraphrase runs across batches. |

## 2. Fabric Workspace Monitoring (`kql`) Correlation

| Symptom | Likely Cause | Resolution |
|---|---|---|
| `routing_evidence_tier` falls back to `citations-only` with 0 matched DAX queries | Monitoring ingestion lag (`SemanticModelLogs` typically takes 30–180s, longer on cold Eventhouse) or monitoring is off on the model's workspace | Enable **Log workspace activity** on every workspace hosting expected/decoy models and increase `CFEVAL_CORRELATION_LAG_SECONDS` (for example `240`). |
| Multiple candidate DAX queries match a single ask | Concurrent activity by the same `eval.tester@contoso.com` account during the run window | Reserve a dedicated evaluation user account and avoid manual Power BI report browsing under that identity while a run is active. |
| Kusto query fails with `Forbidden` | Runner identity lacks read access on the Workspace Monitoring Eventhouse | Grant Database Viewer on the Workspace Monitoring KQL database to the identity running `cfeval`. |

## 3. Scoring & Golden Set Mismatches

| Symptom | Likely Cause | Resolution |
|---|---|---|
| `value` gate fails on a rounded answer (`$12.8M` vs `12840000`) | Tolerance narrower than display rounding or missing `unit: currency` | Set `unit: currency` (enables display-aware half-ULP tolerance) or configure `tolerance: 0.005` / `abs_tol` in your golden YAML. |
| Source semantic model refreshed and numbers legitimately changed | Golden `expected` value reflects an older snapshot | Run each case's `grounding_query_dax` directly against the certified semantic model to refresh ground truth before re-scoring. |
| `model` gate shows `not_applicable` | Target ran without engine telemetry (`transcript-import`, `work-iq`, or `--collector none`) | Expected behavior for `citations-only` / `none` evidence tiers; connect `--collector kql` when semantic-engine proof is required. |

## 4. Eventhouse Publication & OneLake Shortcuts

- **OneLake shortcut propagation delay:** Newly ingested Eventhouse rows can take several minutes to materialize in Lakehouse SQL analytics endpoints via OneLake shortcuts. Local HTML reports (`python -m cfeval report --run-dir runs/<id>`) render immediately from local JSONL with zero propagation wait.
