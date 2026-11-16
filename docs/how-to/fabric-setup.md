# How to Set Up Fabric Workspace Monitoring and Eventhouse Telemetry

This guide configures two optional Microsoft Fabric capabilities for live `engine+citations` evaluation and historical scorecard storage:

1. **Workspace Monitoring (`SemanticModelLogs`)** — Captures engine-executed DAX queries on expected and decoy semantic models.
2. **Telemetry Eventhouse (`EvalRun`..`EvalEvent`)** — Stores multi-run evaluation history for KQL analytics and the optional Fabric scorecard app.

> **Workspace lifecycle note:** Reuse existing Fabric workspaces, semantic models, and reports. Never delete workspaces as part of evaluation teardown; control compute spend with bounded capacity schedules and capacity pause when idle.

## 1. Enable Workspace Monitoring on Model Workspaces

1. Open the Fabric workspace hosting your certified semantic model(s) (and any workspace hosting decoy/sandbox models you want to monitor).
2. Navigate to **Workspace settings → Monitoring** and enable **Log workspace activity** (including Semantic Model query logs).
3. Record the **Query URI** (`https://trd-....kusto.fabric.microsoft.com`) and **Database name** of the monitoring Eventhouse in `.env`:

   ```ini
   CFEVAL_MONITORING_QUERY_URI=https://trd-example.z0.kusto.fabric.microsoft.com
   CFEVAL_MONITORING_DATABASE=00000000-0000-0000-0000-000000000010
   CFEVAL_SEMANTIC_MODEL_WORKSPACE_ID=00000000-0000-0000-0000-000000000011
   ```

   If your expected models and decoy/sandbox models live in **separate workspaces**, list every monitored workspace in `CFEVAL_MONITORING_SOURCES` so `cfeval` sends progress watermarks and correlates `SemanticModelLogs` across all of them:

   ```ini
   CFEVAL_MONITORING_SOURCES=[{"query_uri":"https://trd-certified.z0.kusto.fabric.microsoft.com","database":"00000000-0000-0000-0000-000000000010","workspace_id":"00000000-0000-0000-0000-000000000011"},{"query_uri":"https://trd-sandbox.z0.kusto.fabric.microsoft.com","database":"00000000-0000-0000-0000-000000000020","workspace_id":"00000000-0000-0000-0000-000000000021"}]
   ```

4. Grant your evaluation runner identity viewer/read permissions on each monitoring Eventhouse so `cfeval` can read `SemanticModelLogs`.

## 2. Prepare Semantic Models for AI Grounding

For reliable Fabric IQ routing in Microsoft 365 Copilot Chat:

- Mark authoritative models **Certified** or **Promoted** under **Endorsement** in Semantic Model settings.
- Populate clear measure descriptions, display units, and synonyms ( **Prep data for AI** / AI instructions ) so ambiguous business prompts (`"latest quarterly revenue"`) disambiguate cleanly from draft or archive models.
- Verify that your dedicated test user (`eval.tester@contoso.com`) has Read + Build permission (and intended RLS role membership) on both the report and underlying semantic model.

To test with synthetic Contoso data rather than enterprise models, follow [`samples/contoso/README.md`](../../samples/contoso/README.md).

## 3. Configure the Evaluation Telemetry Eventhouse & Lakehouse Shortcuts (Optional)

If you want `cfeval` to publish runs beyond local `runs/<run-id>/*.jsonl` files and HTML reports:

1. Enable **OneLake availability** on your telemetry Eventhouse KQL database and configure `.env` with the three distinct Fabric item/endpoint IDs:

   ```ini
   CFEVAL_EVENTHOUSE_WORKSPACE_ID=00000000-0000-0000-0000-000000000030
   CFEVAL_EVENTHOUSE_DATABASE_ID=00000000-0000-0000-0000-000000000031
   CFEVAL_EVENTHOUSE_QUERY_URI=https://trd-telemetry.z0.kusto.fabric.microsoft.com
   CFEVAL_EVENTHOUSE_INGEST_URI=https://ingest-trd-telemetry.z0.kusto.fabric.microsoft.com
   # Note: Fabric KQL databases often use their KQL database GUID as the engine databaseName, not the portal display name:
   CFEVAL_EVENTHOUSE_DATABASE=00000000-0000-0000-0000-000000000031

   CFEVAL_LAKEHOUSE_WORKSPACE_ID=00000000-0000-0000-0000-000000000030
   CFEVAL_LAKEHOUSE_ID=00000000-0000-0000-0000-000000000032
   CFEVAL_SQL_ENDPOINT_ID=00000000-0000-0000-0000-000000000033
   ```

2. Apply the generated Eventhouse tables, mappings, functions, non-overwriting OneLake shortcuts, and SQL analytics endpoint metadata sync in place:

   ```powershell
   python -m cfeval setup --sync-sql
   ```

   Or run `python -m cfeval setup-eventhouse` when using KQL only without a Lakehouse, or execute [`kql/setup.kql`](../../kql/setup.kql) in a KQL queryset. All table and mapping DDL statements use `.create-merge` and `.create-or-alter` so schema upgrades (`v0.1` → `v0.2`) apply safely in place without dropping existing tables or shortcuts.

## 4. Syncing SQL Analytics Endpoint Metadata & Staging Fabric Notebooks

- **SQL metadata refresh (`cfeval sync-sql`)**: Eventhouse writes appear in KQL within seconds and export to OneLake `_delta_log` within ~1–3 minutes, whereas the Lakehouse SQL analytics endpoint (`dbo.Eval*`) caches schema and Delta snapshots until refreshed. Run `python -m cfeval sync-sql` (or `python tools/setup_demo.py --env .env --sync-sql --apply`) after schema upgrades, baseline resets, or ad-hoc publications so T-SQL and the hosted scorecard app reflect the latest commits immediately.
- **Fabric Notebook wheel & in-place definition updates**: Build a portable wheel and clean notebook bundle with `python tools/setup_demo.py --env .env --offline --bundle-dir dist/fabric-bundle`, upload `cfeval-<version>-py3-none-any.whl` to your Lakehouse `Files/` path (or attach it to a Fabric Environment), and update existing notebook items in place (`notebooks/{id}/updateDefinition?format=ipynb`) so workspace item IDs and default Lakehouse bindings are preserved.
