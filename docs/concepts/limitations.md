# Known Limitations

`cfeval` is designed around explicit, inspectable evidence boundaries. Review the platform and measurement limitations below before interpreting live scorecards or wiring `cfeval` into automated gates.

1. **Preview Microsoft 365 Copilot Chat API (`/beta`)**:
   * The `copilot-chat` target calls `POST https://graph.microsoft.com/beta/copilot/conversations` and `/chat` ([Chat API overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/overview)). Microsoft `/beta` Graph APIs are subject to breaking payload or throttling changes and are not supported for production SLA workloads.
   * Delegated user authentication is required; application-only service principal tokens are rejected by upstream Microsoft Graph (`R2`) and by the [Fabric IQ MCP server](https://learn.microsoft.com/en-us/fabric/iq/connectors/fabric-iq-mcp) (`R5`).
2. **Broad delegated Graph read permissions require a synthetic test user**:
   * Because the Copilot Chat API requires delegated `Mail.Read`, `Chat.Read`, `ChannelMessage.Read.All`, `Sites.Read.All`, `People.Read.All`, `OnlineMeetingTranscript.Read.All`, and `ExternalItem.Read.All`, running under a real employee account exposes personal mail, chats, and files to grounding and persists answers into run logs. Always use a dedicated synthetic test account (`eval.tester@contoso.com`) in an isolated demo tenant.
3. **Time-window KQL correlation under concurrent load**:
   * Microsoft 365 Copilot Chat HTTP responses do not echo the internal Analysis Services `OperationId` executed inside Fabric. When `CorrelationId` is not propagated end to end, `cfeval` matches `SemanticModelLogs` `QueryEnd` rows by `ExecutingUser` and `[RequestSentUtc, ResponseReceivedUtc]` window.
   * If another process, user session, or scheduled visual query runs under the **same `ExecutingUser`** at the same moment, correlation becomes ambiguous (`CorrelationConfidence = low`). Run live evaluations sequentially with a dedicated test user.
4. **Workspace Monitoring ingestion lag and retention**:
   * Fabric Workspace Monitoring (`SemanticModelLogs`) is asynchronous: `QueryEnd` rows typically appear within `15`–`90` seconds, with occasional multi-minute spikes during capacity cold starts. If ingestion exceeds `CFEVAL_MONITORING_WAIT_SECONDS` + retry polling, engine checks resolve to `INCONCLUSIVE` until re-hydrated (`cfeval rescore` / `cfeval trace probe`).
   * Workspace Monitoring retains `SemanticModelLogs` for **30 days** by default and consumes Fabric capacity CU ([Workspace monitoring overview](https://learn.microsoft.com/en-us/fabric/fundamentals/workspace-monitoring-overview)). Long-term run history must be published to the telemetry Eventhouse (`Eval*` tables) or archived as local JSONL bundles.
5. **Verified answers behavior in Fabric IQ**:
   * Author-curated Power BI **verified answers** (pre-mapped visual/filter triggers inside Power BI Copilot) can be **bypassed** when questions are routed through Fabric IQ in Microsoft 365 Copilot Chat ([Ask Copilot for data from semantic models](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-ask-data-question)). Conversely, if a surface serves a cached visual/verified answer without issuing a fresh ad-hoc DAX query, `SemanticModelLogs` may record different or zero ad-hoc `QueryEnd` rows. Test prompts through the exact surface your users use.
6. **Citations-only surfaces cannot prove engine execution**:
   * Without Workspace Monitoring enabled (or on unstructured Work IQ documents/sites/messages), `RoutingEvidence` caps at `citations-only`. `cfeval` can verify answer values and cited URLs/titles, NOT whether an un-cited semantic model was queried behind the scenes.
7. **LLM-as-judge variance and model drift**:
   * Optional Layer 5 judge scores (`judge.answer_correctness`, `judge.why_consistency`) depend on external LLM weights and prompt sensitivity, even at `temperature=0`. `cfeval` mitigates this by keeping Layers 1–4 100% deterministic, pinning `JudgeModel` and `JudgePromptHash` on every row, requiring human-pair calibration (`cfeval judge calibrate --min-kappa 0.70`), and preventing judge scores from overriding deterministic `FAIL` or `INCONCLUSIVE` gates.
8. **Offline mock runs test harness logic, not your tenant**:
   * `cfeval run --mock` exercises scoring, tolerances, statistical tests, HTML reporting, and scorecard contracts against synthetic Contoso fixtures (`@contoso.com`). Passing `--mock` proves the harness works; it does not validate your tenant's semantic model measures, synonyms, RLS roles, or Copilot tenant settings.

## Related Pages

* [Platform Status](../reference/platform-status.md)
* [Evidence Tiers and Verdicts](./evidence-and-verdicts.md)
* [Threat Model](../responsible-use/threat-model.md)
* [Cost and Operational Limits](../get-started/cost-and-limits.md)
