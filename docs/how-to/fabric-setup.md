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
   CFEVAL_MONITORING_KUSTO_URI=https://trd-example.z0.kusto.fabric.microsoft.com
   CFEVAL_MONITORING_DATABASE=WorkspaceMonitoring
   ```

4. Grant your evaluation runner identity viewer/read permissions on the monitoring Eventhouse so `cfeval` can read `SemanticModelLogs`.

## 2. Prepare Semantic Models for AI Grounding

For reliable Fabric IQ routing in Microsoft 365 Copilot Chat:

- Mark authoritative models **Certified** or **Promoted** under **Endorsement** in Semantic Model settings.
- Populate clear measure descriptions, display units, and synonyms ( **Prep data for AI** / AI instructions ) so ambiguous business prompts (`"latest quarterly revenue"`) disambiguate cleanly from draft or archive models.
- Verify that your dedicated test user (`eval.tester@contoso.com`) has Read permission (and intended RLS role membership) on both the report and underlying semantic model.

To test with synthetic Contoso data rather than enterprise models, follow [`samples/contoso/README.md`](../../samples/contoso/README.md).

## 3. Provision the Evaluation Telemetry Eventhouse (Optional)

If you want `cfeval` to publish runs beyond local `runs/<run-id>/*.jsonl` files and HTML reports:

1. Select or create an Eventhouse KQL database in your evaluation workspace and set:

   ```ini
   CFEVAL_EVENTHOUSE_KUSTO_URI=https://trd-telemetry.z0.kusto.fabric.microsoft.com
   CFEVAL_EVENTHOUSE_DATABASE=CopilotEvalTelemetry
   ```

2. Apply the generated schema and helper functions:

   ```powershell
   python -m cfeval setup-kql --apply
   ```

   Or inspect [`kql/setup.kql`](../../kql/setup.kql) and execute it manually in a KQL queryset.
