# Setup

This guide sets up a live run in a demo tenant and a demo Azure subscription.
Run the offline quickstart first (`notebooks/00_quickstart_offline.ipynb`) so you know what each step produces.

## Scripted route (default: existing models and resources)

The local scripted demo is the acceptance test, not a production deployment framework. Reuse an existing
capacity, workspaces, semantic models/reports, telemetry KQL database and app lakehouse. **Never delete
workspaces or empty them as cleanup.** Preserve model/report IDs and control cost with separately approved,
bounded capacity operation. The scripts do not manage capacity, permissions or tenant settings.

```powershell
Copy-Item .env.example .env
python -m pip install -e ".[copilot,kusto,judge,sql]"
python tools/setup_demo.py --env .env --offline
python tools/setup_demo.py --env .env
# Explicitly select only the changes you want; without --apply these are previews:
python tools/setup_demo.py --env .env --telemetry --shortcuts --refresh-golden --apply
```

Fill `.env` first; the file wins over environment variables. Paths are relative to the invocation directory
unless absolute. `--offline` validates configuration/CSV syntax only, never authenticates or resolves live targets.
The default setup reads back explicit workspace/item IDs, reuses their connection properties, and checks expected
models as the configured **operator**. It does not prove that the **test user** can query them. No tools are installed
by setup. Missing Python extras or Microsoft ODBC Driver 18 must be installed explicitly; SQL verification cannot
be skipped. `--apply` only permits the selected telemetry/shortcut/calibration changes, never an identity/admin action.

| Binding | Use |
|---|---|
| `EVENTHOUSE_WORKSPACE_ID`, `EVENTHOUSE_DATABASE_ID` | Existing **KQL database item GUID**, not the Eventhouse container |
| `EVENTHOUSE_DATABASE` | Actual Kusto engine `databaseName` from connection details; often a GUID, not the display name |
| `LAKEHOUSE_WORKSPACE_ID`, `LAKEHOUSE_ID` | Existing **lakehouse item GUID** for shortcuts and the Rayfin connector |
| `SQL_ENDPOINT_ID` | Lakehouse's `properties.sqlEndpointProperties.id`, distinct from the lakehouse ID; optional cross-check |
| `SQL_ENDPOINT_SERVER`, `SQL_ENDPOINT_DATABASE` | TDS host and database name; blank values resolve from the lakehouse, configured host must match |
| `LAKEHOUSE_SHORTCUT_PATH`, `SQL_SCHEMA` | `Tables` or `Tables/dbo`; SQL schema normally `dbo` |
| `DEMO_APP_URL` | Actual hosted app link, obtained after scaffold/overlay/publish |

Setup uses the existing non-overwriting shortcut and Eventhouse CLI helpers. It never replaces a conflicting
shortcut or recreates an item. Golden refresh previews reference DAX results; `--apply` saves only a separate CSV
after every reference succeeds. Review its reference sentences, units, fiscal periods and cutoff before a run.
The fictional/bundled Q01–Q08 CSV is preserved and is rejected as a live rehearsal set.
Some Fabric KQL database responses omit `properties.databaseName`. Setup therefore checks the configured engine
database with a read-only `current_database()` query rather than guessing it from the display name or item ID.

Optional portable packaging: add `--bundle-dir build/demo-bundle-01` (a **new** local directory). This builds a wheel
from the declared package, copies generic notebooks, and includes no `.env`, private bindings or tokens.
Attach the wheel in a Fabric Environment and import/configure the notebooks through the supported UI. No upload,
notebook execution or job scheduling is performed. Friday uses the local entrypoint; cloud notebook execution is
a separate, unverified path until actually observed.

## What you need

| Item | Why | Notes |
|---|---|---|
| Test user with a Microsoft 365 Copilot license | The Copilot Chat API signs in as a user (delegated only) | Use a dedicated account so its queries are easy to find in workspace monitoring |
| Microsoft Entra app registration | Device-code sign-in for the test user | Public client, delegated Microsoft Graph permissions, admin consent |
| Fabric capacity workspace with the semantic models and reports | What Copilot should answer from | Include a decoy (a stale copy or a draft document) to test routing |
| Workspace monitoring on all expected/decoy workspaces | DAX capture (`SemanticModelLogs`) | A created monitoring item is not proof that collection is enabled |
| Eventhouse with a KQL database (`copilot_eval`) | Telemetry tables | Any workspace on a Fabric capacity |
| Lakehouse | Shortcuts that the Fabric app reads | Same or another workspace |
| Microsoft Foundry resource and project with a chat model deployment | Option 1 judge, Option 2 evaluations | For example `gpt-5-mini` |
| Microsoft ODBC Driver 18 + `cfeval[sql]` | Exact five-table SQL publication readback | Entra token only, encrypted TCP 1433; no SQL password or interactive ODBC login |
| Azure Key Vault (optional) | Token cache/secrets for separately configured notebooks | The notebook user needs approved secret access and a working network path |

## 1. Test user

1. Select an existing dedicated test user and manually verify its Microsoft 365 Copilot license.
2. Manually verify report/model access: Viewer where applicable plus **Read + Build**, and access to intended
   decoys so the routing questions mean something. Review **RLS membership in the supported Power BI UI**;
   never treat an owner/administrator query as test-user or RLS proof.
3. Sign in to Microsoft 365 Copilot Chat in a browser as the test user and confirm that Copilot answers a golden
   question from your Power BI content. Browser and API behavior can differ; one does not prove the other.

Review **Prep data for AI**, AI instructions, AI data schema/synonyms and Approved for Copilot in the supported
Power BI UI. These UI-only artifacts and RLS memberships are not serialized or rewritten by this accelerator.
Do not use Verified Answers as a substitute for the primary observed-DAX demonstration.

## 2. App registration

1. In Microsoft Entra ID, register an application (single tenant).
2. Under **Authentication**, set **Allow public client flows** to **Yes** (device-code sign-in).
3. Under **API permissions**, add these **delegated** Microsoft Graph permissions, which the Copilot Chat API
   requires, and grant admin consent:
   `Sites.Read.All`, `Mail.Read`, `People.Read.All`, `OnlineMeetingTranscript.Read.All`, `Chat.Read`,
   `ChannelMessage.Read.All`, `ExternalItem.Read.All`.
4. Note the **tenant ID** and **client ID** for `TENANT_ID` and `CLIENT_ID`.

These are content-reading permissions, not just model access. For a personal demo, an administrator can use a
per-user delegated grant (`consentType=Principal`) and restrict the enterprise app to the intended user.
Application permissions and tenant-wide consent are not required. Subscription ownership or Fabric
Administrator alone is not Entra app-consent authority; do not activate roles or change consent without approval.

## 3. Golden set

1. Create a **separate** CSV from `data/golden/demo_questions.template.csv` (columns in `data/golden/README.md`).
   Preserve the original Q01–Q08 prompts/history. Changed prompts need new stable IDs. Start with a small approved set of
   questions: some that name the source, some that don't, and at least one that invites a decoy.
2. Add `reference_dax` that returns each expected value as a single cell.
3. Set `SEMANTIC_MODEL_WORKSPACE_ID` and use `tools/setup_demo.py --refresh-golden` to preview expected values
   from the models (needs Build permission and the tenant setting that allows the Execute Queries REST API).
   Add `--apply` to save a separate CSV. Review changed values and the free-text `expected_answer` together;
   a reference query error is not a new golden value.
4. In Fabric notebooks, upload the CSV to the lakehouse **Files** area and set
   `GOLDEN_SET=/lakehouse/default/Files/golden_questions.csv`.

## 4. Workspace monitoring (DAX capture)

1. In every workspace that holds expected models or decoys, open **Workspace settings** > **Monitoring**.
   Reuse/configure the monitoring item and explicitly **turn on data collection**. A Fabric administrator must
   permit monitoring and collection in tenant settings. Monitoring does not backfill earlier activity.
2. From that Eventhouse, copy the **Query URI** into `MONITORING_QUERY_URI` and the KQL database name into
   `MONITORING_DATABASE`.
3. During an **approved bounded** named-source control/rehearsal, inspect the monitoring database:

   ```kusto
   SemanticModelLogs
   | where Timestamp > ago(1h) and OperationName == "QueryEnd"
   | project Timestamp, ExecutingUser, ApplicationName, ItemName, DurationMs, EventText
   | order by Timestamp desc
   ```

   Confirm the query appears with the test user as `ExecutingUser`, and note how long it took to show up. If a
   different identity appears, set `TRACE_USER` to it and keep the workspace quiet during runs.

For multiple workspaces set `MONITORING_SOURCES` to a JSON list of `query_uri`, `database` and `workspace_id`
entries (see `.env.example`). Every configured source must show progress. The harness keeps collecting after
the marker and resets a quiet interval when more DAX arrives. This is observational correlation, not an ordering
or completeness guarantee; empty/unsettled captures remain pending.

## 5. Telemetry Eventhouse

1. Reuse a regular Eventhouse and a KQL database displayed as `copilot_eval`; do not put custom tables in
   the platform-managed monitoring database.
2. Set `EVENTHOUSE_QUERY_URI` and the actual engine `EVENTHOUSE_DATABASE` from the connection details. The engine
   database name can be a GUID rather than the display name.
3. Create the tables, ingestion mappings, OneLake availability and functions: run
   `python tools/setup_demo.py --env .env --telemetry --apply`.
   The low-level `cfeval setup-eventhouse` and KQL script remain available for explicit manual use.

The identity that runs the harness needs to ingest into the database (workspace Contributor, or the database
Ingestor role). OneLake policies for the five app tables are required. Setup returns failure if they cannot be
enabled; only ingestion tuning is best effort.

## 6. Lakehouse shortcuts for the app

OneLake availability (set by the setup script) writes the app tables to OneLake as Delta. Its five-minute minimum
latency setting is not a delivery deadline; the tables arrive independently. Shortcut them into a
lakehouse so the Fabric app can read them through the SQL analytics endpoint:

```bash
python tools/setup_demo.py --env .env --shortcuts --apply
```

You can also create them in the lakehouse: **New shortcut** > **Microsoft OneLake** > the KQL database > the tables
`EvalRun`, `EvalQuestion`, `EvalResult`, `FabricIqQuery` and `EvalEvent`.
For a schema-enabled destination set `LAKEHOUSE_SHORTCUT_PATH=Tables/dbo`. Existing identical shortcuts are reused; a different
target is an error, never silently overwritten. Confirm actual SQL table visibility before connector discovery.

## 7. Microsoft Foundry

* **Option 1 judge**: deploy a chat model and set `JUDGE_ENDPOINT` (the resource endpoint) and `JUDGE_DEPLOYMENT`.
  Use an API key (`JUDGE_API_KEY` locally, or `JUDGE_API_KEY_SECRET` naming a Key Vault secret in Fabric) or
  Microsoft Entra ID.
* **Option 2 evaluations (optional, not the Friday default)**: set `FOUNDRY_PROJECT_ENDPOINT`
  (`https://<account>.services.ai.azure.com/api/projects/<project>`) and `FOUNDRY_EVAL_DEPLOYMENT`. The identity
  that runs the harness needs a role that can create evaluators and run evaluations in the project, such as
  **Azure AI User**. Locally use the explicitly bound operator described below. In a Fabric notebook use a service principal: set
  `FOUNDRY_SP_CLIENT_ID` and keep its secret in Key Vault under `FOUNDRY_SP_SECRET_NAME`.
  Custom code evaluators are in preview: check that they're available in your project's region.

Install the declared extras: they constrain OpenAI to compatible 2.x and Foundry projects to 2.x. Evaluator
sources/versions are read back and pinned per project. A completed parent run is not sufficient coverage:
missing/invalid required results or a failed service run are backend **ERROR**, never replaced with local scores.
Preview dataset runs may fail before returning grades or detailed service errors. Preserve the original
`foundry-operation-*.json`, eval/run IDs and service status and stop; no local-grade fallback or blind new dataset run.

## 8. Run

**Locally** (PowerShell; the Python commands also work in other shells):

```powershell
Copy-Item .env.example .env
python -m pip install -e ".[copilot,kusto,judge,sql]"
python -m cfeval doctor
python -m cfeval login
python tools/rehearse_demo.py --env .env --run-id demo-unique-01 --max-questions 8 --max-judge-calls 16
```

Before live calls, fill `TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_CONFIG_DIR`, `OPERATOR_UPN` and the
test-user/client fields. Use an isolated, already authenticated operator CLI profile, with the intended tenant
and subscription; the accelerator does not switch accounts or repair operator login. Arrange a persistent
task/service/account/tenant browser context before any operator sign-in.

`login` is the explicit test-user sign-in. It opens a private labelled context page; use its link to sign in
**as the configured test user in the same window**, retaining the context tab through redirects and consent.
The current Microsoft verification link (`https://login.microsoft.com/device`) and legacy
`microsoft.com/devicelogin` links are accepted; other verification URLs are rejected.
Actual token tenant, principal, audience, scopes and expiry are checked before saving the protected cache.
Ordinary runs are silent and fail if sign-in is needed. `doctor` checks configuration/packages, not live readiness.
The operator must track the total approved allowance across controls and final batch. Per-run ceilings are explicit;
failed/ambiguous attempts count, and a new run ID does not authorize another batch. Repeats are 1, every
question gets one why follow-up, and Chat/direct judge retries are disabled. The wrapper is Option 1 only and
cannot launch a Foundry dataset evaluation. Do not run a second full batch during the meeting.

The wrapper verifies nonempty DAX/check coverage and exact per-run counts for all **seven** Eventhouse tables and
**five** SQL shortcut tables against current JSONL (including row versions). Missing SQL dependencies/drivers,
runtime failures and publication timeout exit 3; valid quality FAIL exits 2. A missing table/score/query is not success.
To continue observing publication without any submissions:

```powershell
python tools/rehearse_demo.py --env .env --run-id demo-unique-01 --verify-only --wait-seconds 1200 --poll-seconds 30
```

`--verify-only` does not ask Copilot, call a judge, fetch monitoring traces, rescore or publish. It leaves original
JSONL/operation IDs untouched. Interrupted submissions or reported sink errors need manual reconciliation, not
automatic republishing. Exit 0 still leaves actual hosted SSO/browser acceptance to the operator.

**In Fabric**: import the notebooks, set the values in the settings cell, and run
`02_option1_fabric_native` or `03_option2_foundry` only with separate live approval. Their live/apply/login flags
remain false; no jobs are created automatically. Set `TOKEN_CACHE=keyvault` and `KEY_VAULT_URL` if persistence is
needed. Cloud notebook authentication/Key Vault execution is not proven by a local run. If the refresh
token expires (after long inactivity or a password change), run the explicit sign-in cell interactively again.
Set the expected notebook operator identity too. The sign-in cell is silent by default (`interactive_login=False`).
For one manual sign-in set the flag to `True`; its context banner and device sign-in tab must stay in the same
browser window. Reset the flag to `False` before publishing/scheduling: a scheduler runs all cells, so a comment
to "skip the sign-in cell" is not a guard. Missing scheduled tokens then fail without prompting.

## 9. Scorecard app

Follow [app/README.md](../app/README.md): scaffold a Fabric app, add the lakehouse connector, apply the overlay
and deploy.

## Settings reference

All settings are environment variables or entries in a `.env` file (the file wins when both set a value);
`.env.example` lists them with comments.
`python -m cfeval doctor` shows which features are configured and which packages are missing.

Fabric API patterns were checked against
[`microsoft/skills-for-fabric` v0.3.21](https://github.com/microsoft/skills-for-fabric/tree/f8fac110ac3b93e9d1f7b0bd8feac5c6a468ce43),
including `common/COMMON-CLI.md`, `common/COMMON-CORE.md`, `common/EVENTHOUSE-CONSUMPTION-CORE.md`,
`common/SQLDW-CONSUMPTION-CORE.md`, and the `eventhouse-cli` authoring/consumption and `sqldw-cli` consumption references.
Fabric control-plane calls carry `x-ms-fabric-skill` for the workload; continuation URLs cannot escape the API origin.
Service behavior and
limits remain governed by current [monitoring](https://learn.microsoft.com/fabric/fundamentals/enable-workspace-monitoring)
and [OneLake mirroring](https://learn.microsoft.com/kusto/management/alter-merge-mirroring-policy-command?view=microsoft-fabric) documentation.

## Evidence gaps / still thin

Model preparation improves the model contract, not deterministic API source selection. A named-source success
does not prove repaired unqualified discovery; the API exposes no source/agent selector. The generated why is not
chain of thought. Exact publication counts are not hosted UI/SSO proof; complete those gates in the Fabric portal.
