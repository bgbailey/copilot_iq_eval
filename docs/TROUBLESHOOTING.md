# Troubleshooting

Start with `python -m cfeval doctor`: it shows which settings and packages are in place. Every run also writes a
folder under `runs/` with the JSONL rows and a `summary.md`, so you can see what happened even if the Eventhouse
was unreachable.

## Copilot Chat API

| Symptom | Likely cause | Fix |
|---|---|---|
| `401` or `403` on every ask | Missing consent, a missing delegated permission, or the account lacks the required Copilot entitlement | Check the seven delegated scopes and per-user consent, then run explicit `cfeval login` with the correct labelled context; do not clear a shared cache or switch another session |
| Actual token identity does not match configuration | The device code used another user or tenant | The token is rejected before cache save; rerun explicit login as the configured user/tenant, leaving other sessions alone |
| `429` or ambiguous timeout | Throttling/service/network failure | The demo route has retries disabled and counts attempts before submission. Preserve the run and stop; a corrective change and new bounded approval are needed, not another full batch |
| Answers never cite Power BI | The test user can't reach the content, or the tenant's Copilot experience doesn't use it for that question | Confirm the same question in Copilot Chat in the browser as the test user; check Build permission; name the report in the question |
| The follow-up "why" says it can't explain | Generated explanation is missing/unhelpful | Keep the actual reply; the acceptance route requires a real follow-up. Do not manufacture reasoning or silently switch to inline/off |
| The reply contains concatenated why JSON objects | The service returned more than one JSON block | The harness parses the first object and preserves the original text; it does not manufacture an explanation |
| A decoy appears in attribution metadata but not the answer citation list | It may be grounding-only discovery metadata | Inspect attribution provenance and the answer links separately from the model trace; discovery is not proof that the decoy was cited or queried |
| Scheduled run fails with `LoginRequired` | No valid cached token for the selected user/scopes | Run the explicit sign-in cell with its context banner; use a reachable Key Vault for persistent schedules. Silent runs never start device flow |

## DAX capture

| Symptom | Likely cause | Fix |
|---|---|---|
| Every ask shows "no DAX observed" | Monitoring is on another workspace, or `ExecutingUser` isn't the test user | Query `SemanticModelLogs` directly (see SETUP step 4); set `TRACE_USER` if a different identity runs the queries |
| Trace status `pending` | No DAX, missing progress in a configured source, or capture has not settled | Incomplete evidence: inspect collection and configured sources. Seeing a marker alone is not completeness. The read-only publication resume does not fetch traces or regrade |
| Setup/rehearsal rejects monitoring-source coverage | A configured workspace has no queryable expected/decoy model in the selected CSV | Scope `MONITORING_SOURCES` to that control/rehearsal roster. Do not remove a required expected/decoy workspace or weaken settling to obtain a pass |
| "DAX watermark query failed" | The Execute Queries REST API tenant setting is off, or no Build permission on the first golden model | Enable the setting or grant Build; without a watermark the harness waits for newer events, which can leave the last asks pending in a quiet workspace |
| DAX from other activity lands on an ask | Another user or job used the test user's identity during the run | Keep the test user dedicated; keep `PAUSE_SECONDS` at 20 or more |
| `observed` shown rather than `complete` | Actual nonempty capture settled | This is deliberate: user/time correlation does not guarantee exhaustive logs |

## Telemetry Eventhouse

| Symptom | Likely cause | Fix |
|---|---|---|
| "telemetry write to EventhouseSink failed" | No ingest permission, wrong URI, or missing tables/mappings | Stop and reconcile current JSONL against all seven tables. An ambiguous ingest may already have landed. The demo never automatically republishes; do not resend the whole folder |
| Rows arrive minutes late | Streaming ingestion is off, so queued ingestion is used | Enable streaming ingestion (optional command in the setup script) or accept the delay |
| Can't change a column type | OneLake availability/schema constraint | Stop and review a supported migration separately; never delete/recreate a workspace or silently replace telemetry |

## Scorecard app

| Symptom | Likely cause | Fix |
|---|---|---|
| "No evaluation results in this window" right after a run | Independent OneLake/SQL propagation | Five minutes is a minimum setting, not a deadline. Use same-run `--verify-only` bounded readback; never another question batch |
| `pyodbc` import or ODBC driver missing | SQL verification dependency absent | Explicitly install `python -m pip install -e ".[sql]"` and Microsoft ODBC Driver 18 for SQL Server. Verification stops, never falls back to success |
| SQL connect error/timeout | Wrong binding, expired explicit identity, or blocked TDS | Check resolved server vs lakehouse, database name, Entra tenant/account and outbound TCP 1433. The public route uses memory-only SQL-audience tokens with ODBC attr 1256, encrypted `SERVER=tcp:<host>,1433`; never put tokens in config/logs |
| Exact row counts are higher than JSONL | Duplicate ingest or a separately modified run | Preserve all original IDs and versions; reconcile manually. Do not deduplicate evidence until counts “pass” |
| Existing run ID rejected | A submission already started or completed | Use `--verify-only` for publication observation; never rename/reset the folder to retry |
| Connector metadata has no eval tables | The shortcuts weren't created before `connector add` | Create the shortcuts, refresh the connector metadata, run `apply-overlay.mjs` again |
| `SELECTION_REQUIRED` or unknown field errors | Entity files don't match the source | Re-run `node app/scripts/generate-entities.mjs --project .` and `npx rayfin up connector apply --name evals` |
| Sign-in popup doesn't open | The browser blocked it | Click **Sign in with Fabric** again and allow popups for the app's origin |
| Long answers cut off | The SQL analytics endpoint stores strings as `varchar(8000)` | Full text is in `EvalAsk` in the Eventhouse |

## Microsoft Foundry

| Symptom | Likely cause | Fix |
|---|---|---|
| Evaluator registration fails | Custom code evaluators aren't available in the project's region, or the identity lacks a role | Use a supported region; give the identity a role such as Azure AI User on the project |
| Evaluation run times out | Large runs or model throttling | Read the persisted `foundry-operation-*.json` for the original IDs and inspect that run. Start smaller; do not blindly create another run or resize capacity |
| Foundry is failed/canceled, or expected criterion results are absent | The scoring backend did not return a complete evaluation | The affected backend is `ERROR` and the run partial/failed. Inspect the persisted original IDs/status and available error; keep valid local results, and reconcile before any approved regrade |
| Option 2 scores are 0.5 everywhere | Output items didn't map to checks | Check the testing criteria names in the Foundry run; they must be `value`, `artifact`, `model`, `judge_answer`, `why`, `coherence`, `similarity` |
| Judge calls fail in a Fabric notebook | No Azure CLI in Fabric | Use an API key from Key Vault (`JUDGE_API_KEY_SECRET`) or a service principal |
| Foundry import fails on `httpx` after installing OpenAI 3.x | Incompatible major-version dependency split | Install the repository's declared extras/requirements (OpenAI 2.x); don't bypass TLS or use a success-shaped fallback |

## Evidence gaps / still thin

An unqualified Service Operations refusal does not establish missing access or missing AI preparation.
Use separately approved named-source count/MTTR controls and test-user report/RLS UI checks to distinguish
reachability from discovery. Original Q08's “latest quarterly revenue” leaves gross/net, source and period
ambiguous: a plausible Finance/net answer is diagnostic, not automatically a hallucination. Keep that history;
give an explicit Sales/gross/completed-fiscal-quarter/as-of question a new ID and a calibrated reference.
