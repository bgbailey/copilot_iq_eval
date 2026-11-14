# Capture Engine DAX with Workspace Monitoring

Graph citations tell you which Power BI report or semantic model Copilot **linked** in prose; Fabric Workspace Monitoring (`SemanticModelLogs`) proves which semantic model the Analysis Services engine **actually queried**, what DAX ran, whether any query errored, and how much `CpuTimeMs` it consumed.

## Configure Fabric Workspace Monitoring

1. **Enable Workspace Monitoring**: In the Microsoft Fabric portal, open the workspace hosting your target semantic models as a **Workspace Admin**, select **Workspace settings -> Monitoring**, and turn on **Log workspace activity** ([Workspace monitoring overview](https://learn.microsoft.com/en-us/fabric/fundamentals/workspace-monitoring-overview)).
2. **Multi-workspace topologies**: One monitoring Eventhouse can serve semantic model activity across monitored workspaces, or you can configure `CFEVAL_MONITORING_SOURCES` across multiple workspaces. Record the KQL query URI and database name in `.env`:
   ```dotenv
   CFEVAL_MONITORING_QUERY_URI=https://trd-monitoring.z0.kusto.fabric.microsoft.com
   CFEVAL_MONITORING_DATABASE=WorkspaceMonitoring
   CFEVAL_SEMANTIC_MODEL_WORKSPACE_ID=00000000-0000-0000-0000-000000000003
   ```
3. **Grant KQL read permissions**: Grant your dedicated synthetic test user (`eval.tester@contoso.com`) **Viewer** access to the monitoring Eventhouse KQL database so `cfeval` can query [`SemanticModelLogs`](https://learn.microsoft.com/en-us/fabric/enterprise/powerbi/semantic-model-operations).

## Retention and Capacity Impact

* **30-day default retention**: Workspace Monitoring retains `SemanticModelLogs` for **30 days** by default. Raw DAX trace logs age out after that window unless exported; `cfeval` copies correlated turn queries into `FabricIqQuery` in your long-lived telemetry Eventhouse (`runs/<run_id>/` locally) so evaluation evidence persists beyond 30 days.
* **Capacity consumption**: Streaming `SemanticModelLogs` consumes minor background Fabric capacity CU on the attached capacity. Reuse existing workspaces and pause non-production capacities between test windows via bounded capacity leases rather than deleting workspaces.

## How `cfeval` Filters Copilot Index-Build Noise

When Copilot indexes a semantic model's string columns for entity resolution, Fabric emits background DAX queries that are **not** user answer queries—typically shaped like:

```dax
EVALUATE SELECTCOLUMNS(FILTER(VALUES('dim_product'[product_name]), LEN(...) ...), "valueColumn", ...)
```

`src/cfeval/trace.py` (`is_noise_dax`) automatically filters out two classes of non-answer queries before scoring routing gates:

1. **Copilot text-index build scans**: `SELECTCOLUMNS(FILTER(VALUES(... LEN(... "valueColumn" ...)` lexicon-indexing queries so background index refreshes never pollute `DaxQueryCount` or trigger false decoy matches.
2. **Ingestion watermarks (`cfeval_watermark`)**: Lightweight `EVALUATE ROW("cfeval_watermark", "<marker>")` probes sent by `cfeval` strictly to confirm `SemanticModelLogs` has caught up past the end of a run window.

All remaining `OperationName == "QueryEnd"` events for `ExecutingUser` within the turn window are preserved in `FabricIqQuery`, along with parsed `ApplicationContext` (`DatasetId`, `ReportId`, `VisualId`), `DurationMs`, and `CpuTimeMs`.

## Verify Trace Ingestion with `cfeval trace probe`

Before launching a full live benchmark, run a single-shot trace probe to verify KQL permissions, clock alignment, watermark visibility, and typical ingestion lag in your demo tenant:

```bash
cfeval trace probe
```

`cfeval trace probe` checks recent `SemanticModelLogs` visibility (and optional watermark round-trip latency), reporting the latest ingested timestamp and recommended `CFEVAL_TRACE_WAIT_SECONDS` / `CFEVAL_TRACE_SETTLE_SECONDS`.

If a completed run finished before a slow KQL ingestion spike landed, re-collect traces and rescore locally without re-calling Copilot Chat:

```bash
cfeval rescore runs/<run_id>
```

## Related Pages

* [Prerequisites](../get-started/prerequisites.md)
* [Evidence Tiers and Verdicts](../concepts/evidence-and-verdicts.md)
* [Troubleshoot](./troubleshoot.md)
