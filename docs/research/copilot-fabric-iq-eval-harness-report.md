# Automated Evaluation of M365 Copilot → Fabric IQ Routing and Answers (state as of 3 Nov 2026)

## Executive Summary
You can't automatically prove which semantic model answered a prompt through the base Microsoft 365 Copilot Chat API. The API is beta, delegated-only, and documented only for enterprise-search and web grounding, with no agent targeting. Evidence has to come from three places: (1) an **agent surface you can drive programmatically**, (2) **server-side Fabric telemetry** (workspace monitoring `SemanticModelLogs`: ItemId + DAX `EventText` + `ExecutingUser`), and (3) an **independent ground-truth DAX execution**. Recommended primary path: a declarative agent with the new GA Fabric capability (manifest 1.9), evaluated by the Agent Evaluations CLI and correlated with SemanticModelLogs. Secondary path: a Copilot Studio agent that calls a Fabric data agent, evaluated via the Power Platform evaluation API with the Tool use grader. **Confidence: MODERATE.** The surfaces are well documented, but several correlation fields are undocumented and need a spike in the demo tenant.

## 1. Microsoft 365 Copilot Chat API
- **Status:** "Overview of the Microsoft 365 Copilot Chat API (preview)". Endpoints are `/beta` only: "APIs under the /beta version are subject to change. Use of these APIs in production applications is not supported." Overview last updated 2026-07-02. [Overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/overview), [Create](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotroot-post-conversations)
- **Endpoints:** `POST https://graph.microsoft.com/beta/copilot/conversations` takes an empty body `{}` and returns 201 with `id, createdDateTime, displayName, status, turnCount`. `POST .../conversations/{id}/chat` is synchronous. `.../chatOverStream` returns SSE (`text/event-stream`), which isn't supported in Graph Explorer. [chat](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotconversation-chat), [chatOverStream](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotconversation-chatoverstream)
- **Auth:** delegated (work/school) only; application permissions are "Not supported". Required permissions: Sites.Read.All, Mail.Read, People.Read.All, OnlineMeetingTranscript.Read.All, Chat.Read, ChannelMessage.Read.All, ExternalItem.Read.All ("You need all of these"). Global cloud only. [Create](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotroot-post-conversations)
- **Licensing:** "available at no extra cost to users with a Microsoft 365 Copilot add-on license"; unlicensed users aren't supported. [Overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/overview)
- **Request body:** `message` (required), `locationHint` (`timeZone`, required), `additionalContext[]` (`text`, for extra grounding), and `contextualResources`. `contextualResources` takes `files[].uri` (OneDrive/SharePoint) and `webContext.isWebEnabled:false`; the web toggle is "a single-turn action". **No agent, plugin or data-source selector is documented.** [chat](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotconversation-chat)
- **Response:** `copilotConversation.messages[]` contains `copilotConversationResponseMessage`: `text`, `adaptiveCards`, `attributions[]` (`attributionType` annotation/citation, `attributionSource` model/grounding, `providerDisplayName`, `seeMoreWebUrl`) and `sensitivityLabel`. The stream sample shows `"agentId": null` at conversation level; this field isn't documented. No tool or plugin invocation metadata.
- **Limitations (quoted):** "doesn't support action or content generation skills"; "only responds with textual responses"; "doesn't support tools such as code interpreter"; "doesn't support long running tasks… prone to gateway timeouts"; "subject to all limitations of the Microsoft 365 Copilot semantic index." [Overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/overview)
- **Agents and Fabric:** the docs describe only "enterprise search grounding and web search grounding". The declarative-agent docs say manifest-declared connected agents "are a separate mechanism from the Copilot Chat API". [Connected agents](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/declarative-agent-connected-agent) **Conclusion:** the Chat API can't target declarative, Copilot Studio or Fabric data agents. Whether base Copilot's GA Power BI answering (section 3d) triggers through the API is **undocumented**, so test it empirically.
- **Throttling:** no published Chat API limit was found. A third-party blog cites 200 requests/user/hour for the Retrieval and Search APIs, not Chat ([spknowledge](https://spknowledge.com/2026/08/17/microsoft-365-copilot-api-rate-limits-error-handling-national-cloud/), LOW trust). **Unverified.**

## 2. Telemetry showing what Copilot used
- **Interaction Export API:** `aiInteractionHistory: getAllEnterpriseInteractions` (v1.0 and beta). **Application-only** `AiEnterpriseInteraction.Read.All`; delegated isn't supported. It supports `$top` (recommended 100), `$filter` on appClass, and a createdDateTime range (both bounds required); delta isn't supported. It needs a Copilot license with the "Graph-grounded chat" service plan, and "doesn't retrieve interactions in agents created by Copilot Studio." Fields: `appClass` (e.g. `IPM.SkypeTeams.Message.Copilot.BizChat`), `conversationType`, `interactionType` (userPrompt/aiResponse), `requestId` (pairs prompt with response), `sessionId`, `body`, `attachments`, `contexts`, `links` (`linkType` File/Event/…), `mentions`, `from`. Latency: **not documented**. [API](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/interaction-export/aiinteractionhistory-getallenterpriseinteractions), [resource](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/interaction-export/resources/aiinteraction)
- **Purview CopilotInteraction (Audit Standard):** includes `AccessedResources[]` (ID, SiteUrl, Type, Name, SensitivityLabelId, Action, PolicyDetails, Status, XPIADetected), `AgentId` (e.g. `CopilotStudio.Declarative.<guid>`), `AgentName`, `AgentVersion`, `AISystemPlugin[]` (`BingWebSearch` marks web use), `AppHost` (BizChat, Teams, Power BI…), `AppIdentity` (e.g. `Copilot.Fabric.CopilotforPowerBI`), `CapacityId`, `Contexts`, `Messages` and `ModelTransparencyDetails`. AppIdentity filtering must be done offline after export. Updated 2026-08-26. [Purview](https://learn.microsoft.com/en-us/purview/audit-copilot) **Not documented:** whether a Power BI semantic model or Fabric data agent appears in `AccessedResources` or `AISystemPlugin`.
- **Programmatic audit query:** Graph `security/auditLog/queries` (auditLogQuery: `recordTypeFilters`, `operationFilters`, `userPrincipalNameFilters`, `status`, `records`). Permission `ThreatIntelligence.Read.All` (delegated or app) on v1.0; beta uses per-service `AuditLogsQuery-*` permissions. [auditLogQuery](https://learn.microsoft.com/en-us/graph/api/resources/security-auditlogquery?view=graph-rest-1.0), [Get](https://learn.microsoft.com/en-us/graph/api/security-auditlogquery-get?view=graph-rest-1.0) The Office 365 Management Activity API schema page for CopilotInteraction is stale (2024). [schema](https://learn.microsoft.com/en-us/office/office-365-management-api/copilot-schema) Latency: **not verified**; expect it to be asynchronous.
- **Agent 365:** GA for commercial customers on 1 May 2026. [Security blog](https://www.microsoft.com/en-us/security/blog/2026/05/01/microsoft-agent-365-now-generally-available-expands-capabilities-and-integrations/) Observability now runs through the **Microsoft OpenTelemetry Distro**, which exports to Agent 365, Azure Monitor or OTLP; the earlier A365 Observability SDK is deprecated. It instruments agents **you build**, not first-party Copilot internals. [Distro](https://learn.microsoft.com/en-us/microsoft-agent-365/developer/microsoft-opentelemetry)
- **Copilot Analytics:** no per-prompt routing data was found; the new `getMicrosoft365CopilotUsageUserDetailByDate` is aggregate usage (Oct 2026). [What's new](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/whats-new)

## 3. Fabric IQ and every M365 Copilot consumption path
**What it is:** announced at Ignite in November 2025 with five capabilities: ontology, semantic model, native graph, data agents and operations agents. [InfoWorld](https://www.infoworld.com/article/4093181/microsoft-fabric-iq-adds-semantic-intelligence-layer-to-fabric.html), [Fabric blog](https://community.fabric.microsoft.com/blog/fbc_fabricupdatesblogs/fabric-iq-the-semantic-foundation-for-enterprise-ai/5172473) The current Learn page (2026-09-28) positions it within "Microsoft IQ" (Work, Foundry, Web, Fabric IQ). The IQ workload is still "(preview)" and ontology is preview. Workload items: Ontology, semantic model, Planning, Graph, Data agent and Operations agent. [Overview](https://learn.microsoft.com/en-us/fabric/iq/overview)

**(a) Native Fabric IQ in M365 Copilot Chat (GA, 2026-09-23):** "Data answering from Power BI content in Microsoft 365 Copilot Chat is a generally available (GA) feature". Copilot "can search for relevant Power BI reports and use the underlying semantic models", using the user's permissions including RLS/OLS. **Routing control:**
- Name the report (fuzzy matching), paste a report link or attach it.
- You can "paste a semantic model URL… to ask questions directly against the model."
- General questions "might need guidance to use Power BI data".
- An attachment "doesn't limit the answer to only that report".
- Data agents and ontologies "can't answer… without an explicitly published Microsoft 365 agent".

Embedded (A/EM) capacities aren't supported; Pro, PPU, Premium and Fabric are. Requires a "Microsoft 365 Copilot Premium license". [Learn](https://learn.microsoft.com/en-us/fabric/iq/connectors/microsoft-365-copilot-overview)

**(b) Declarative agent / Agent Builder "Fabric" capability:** **GA**. It answers using "Power BI reports and semantic models that the user can access"; no MCP endpoint or app registration is needed; it uses the user's Entra identity, RLS and OLS. [Agent Builder](https://learn.microsoft.com/en-us/fabric/iq/connectors/agent-builder-overview) Pro-code: manifest **v1.9 (Oct 2026)** "Added the new Fabric capability". [Schema 1.9](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/declarative-agent-manifest-1.9) Routing is controlled by agent instructions, which can require "State the data source, filters, and time period used." **No documented property pins a specific semantic model** (not verified in the 1.9 Fabric object; check the schema).

**(c) Fabric data agent published to M365 Copilot (Agent Store):** invoked by chatting directly or with `@`-mention. Uses user identity, and "all row-level and column-level security settings are fully respected". The publish description "becomes the description_for_model". The orchestrator rephrases output, and "some level of change is inevitable." Status is ambiguous: the en-US page (2026-10-26) no longer says preview, but localized copies do. Publishing to M365 "doesn't use the public API yet" (portal or Fabric notebook only). [Learn](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-microsoft-365-copilot), [SDK](https://learn.microsoft.com/en-us/fabric/data-science/fabric-data-agent-sdk)

**(d) Copilot Studio:**
- The current path is the **"Fabric IQ Data MCP"** tool, on the **GitHub Copilot harness** only.
- Auth mode is **User** or **Maker**. "The orchestrator… decides when to call it… based on the description".
- The agent can be published to Teams + M365 Copilot. [Tool](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-microsoft-copilot-studio-tool)
- The legacy "connected agent" path is preview. [Connected](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-microsoft-copilot-studio)
- The Fabric IQ blog also says ontology can be added as "Fabric IQ MCP (Preview)" as a tool. [Blog](https://community.fabric.microsoft.com/blog/fbc_fabricupdatesblogs/fabric-iq-the-semantic-layer-powering-trusted-ai-agents-at-enterprise-scale/5190739)

**(e) Foundry:**
- The `fabric_dataagent_preview` tool is "scheduled for deprecation on November 6, 2026. Use the Fabric IQ tool instead."
- It uses OBO identity passthrough; "Service principal authentication isn't supported for the Fabric data agent."
- `tool_choice:"required"` can force the call. [Foundry](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/fabric)
- Publishing Foundry agents to M365 Copilot wasn't re-verified in this pass.

**(f) MCP paths:**
- **Fabric IQ MCP (GA):**
  - Endpoint `https://fabriciq.svc.cloud.microsoft/v1/mcp/fabriciq`, pinned with header `X-Variants: Fabric.Routing.FabricIQ.V1`.
  - Tools: DiscoverArtifacts, ResolveFabricItem, GetReportMetadata, GetSemanticModelSchema, ValueSearch and ExecuteQuery (default 250 rows; "Each ExecuteQuery call targets one semantic model").
  - Auth: delegated `Item.Read.All` + `Item.Execute.All`; "Service-principal and application-only authentication aren't supported".
  - Doesn't support ontologies or data agents. [Fabric IQ MCP](https://learn.microsoft.com/en-us/fabric/iq/connectors/fabric-iq-mcp)
- The older **Power BI Consumption MCP** is preview and superseded ("prefer to use the Fabric IQ MCP server"). [PBI MCP](https://learn.microsoft.com/en-us/power-bi/developer/mcp/remote-mcp-server-get-started)
- **Data agent MCP:** `https://api.fabric.microsoft.com/v1/mcp/workspaces/{ws}/dataagents/{id}/agent`. It exposes a single tool whose description is the publish description. Token "can represent either a user identity or a service principal" (scope `https://api.fabric.microsoft.com/.default`). Supports MCP tasks for long runs. [Data agent MCP](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-mcp-server)
- Declarative agents support MCP-based actions and widgets (Mar 2026). [What's new](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/whats-new)

**Prep data for AI:** AI data schema (field subset), verified answers (trigger phrases → visual, up to 3 filters) and AI instructions are stored on the semantic model. The Prep data for AI page is still titled preview. [Prep](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-prepare-data-ai), [Verified answers](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-prepare-data-ai-verified-answers)

## 4. Programmatic Fabric data agent invocation and introspection
- **Breaking change:** the FabricOpenAI/Assistants (threads/runs) client relied on the OpenAI Assistants API, "which OpenAI sunset on August 26, 2026… migrate to the MCP endpoint". The SDK is now management-plane only (create, configure, `publish_staging`); querying goes through MCP or the Responses API. [Python client](https://learn.microsoft.com/en-us/fabric/data-science/consume-data-agent-python), [SDK](https://learn.microsoft.com/en-us/fabric/data-science/fabric-data-agent-sdk)
- **Run-step introspection** (`run_steps`, tool names, generated query) is documented only for the sunset Assistants client. The MCP tool response is documented as text. **Unverified** whether MCP returns the DAX query.
- **`evaluate_data_agent(df, name, stage)`** writes `<table>` (summary) and `<table>_steps` ("detailed reasoning and step-by-step execution") and supports question/expected_answer ground truth (preview). [Evaluate](https://learn.microsoft.com/en-us/fabric/data-science/evaluate-data-agent) This is the best documented way to see per-question steps.
- **Identity:** SPN support is **preview** (tenant setting "Service principals can use Fabric APIs", workspace Member/Contributor, read on sources). [SPN](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-service-principal) A semantic model needs only **Read** permission through a data agent. [Create](https://learn.microsoft.com/en-us/fabric/data-science/how-to-create-data-agent)
- **Capacity:** F2+ or P1+, plus cross-geo processing and storage settings. [Create](https://learn.microsoft.com/en-us/fabric/data-science/how-to-create-data-agent)
- **REST item/definition APIs:** the SDK "runs on the Fabric public REST API". Specific endpoint paths weren't re-verified.

## 5. Programmatic testing of Copilot Studio agents
- **Harness split (critical).** The Fabric data agent *tool* requires the GitHub Copilot harness. The Power Platform evaluation REST API, the full grader set, and the Agents SDK CopilotClient are documented for the **standard harness**. The CopilotClient docs say "Agents using the GitHub Copilot harness aren't yet officially supported." [Agents SDK](https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/integrate-with-mcs)
- **Graders (standard harness):** General quality, Content safety, Compare meaning, **Tool use** ("Whether the test case used all or any the expected resources", pass/fail, expected capabilities), Keyword match, Text similarity, Exact match and Custom. [Methods](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-overview)
- **New-harness Evaluate tab (production-ready preview):**
  - CSV upload, max 5 MB.
  - User profile = signed-in user.
  - Only "No authentication or Authenticate with Microsoft" agents.
  - One version lists only General quality. [Evaluate (new)](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/analytics-agent-evaluation-intro), [Test set](https://learn.microsoft.com/en-au/microsoft-copilot-studio/agents-experience/analytics-agent-evaluation-create)
- **REST API:**
  - `POST https://api.powerplatform.com/copilotstudio/environments/{env}/bots/{bot}/api/makerevaluation/testsets/{id}/run?api-version=2024-10-01`, body `evaluationRunName`, `mcsConnectionId` (user profile), `runOnPublishedBot`, `toolsConnections[]`.
  - Results come from `GET .../testruns/{runId}`.
  - Needs a **user** token. [REST](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-rest-api), [Ref](https://learn.microsoft.com/en-us/rest/api/power-platform/copilotstudio/bots/run-maker-evaluation-test-set)
  - A pac CLI command for evaluations wasn't found.
- **Copilot Agent Kit:**
  - **Plan Validation** checks that "the dynamic plan… includes the expected tools" (tools, actions, connected agents) with a pass threshold %, evaluated post-run from conversation transcripts.
  - Also offers Topic Match (needs Dataverse enrichment), Generative Answers, Response Match and Multi-turn.
  - Connector "Connect to continue" cards can be automated through a multi-turn Invoke Actions test. [Kit](https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/kit-configure-tests)
- **CopilotClient** (`microsoft-agents-copilotstudio-client` 1.8.0, 2026-10-01): user token with `CopilotStudio.Copilots.Invoke`. The repo says delegated *and application* permissions are coming for the Microsoft Copilot harness "by the end of October 2026". [README](https://github.com/microsoft/Agents/blob/main/samples/python/copilotstudio-client/README.md), [lib](https://github.com/microsoft/Agents-for-python/blob/main/libraries/microsoft-agents-copilotstudio-client/readme.md)
- **Telemetry:** environment-level App Insights (preview, both harnesses) emits OTel `InvokeAgent`/`ExecuteTool`/`OutputMessages` spans in `dependencies`, keyed by `gen_ai.conversation.id`. "Telemetry delivery can take up to 24 hours on new configurations." [Env telemetry](https://learn.microsoft.com/en-us/microsoft-copilot-studio/advanced-environment-level-agent-telemetry)
- **Direct Line + end-user auth to Fabric:** not re-verified. Use CopilotClient or the evaluation API with `mcsConnectionId` instead.

## 6. Evidence of which semantic model was queried
- **Workspace monitoring `SemanticModelLogs`** (monitoring Eventhouse) columns:
  - `ItemId`, `ItemName`, `ItemKind`, `WorkspaceId`, `OperationName`
  - `EventText` ("for example, DAX Query"), `ExecutingUser`, `User`
  - `ApplicationName` ("values passed by the application"), `ApplicationContext` ("for example, report ID")
  - `CorrelationId`, `OperationId`, `XmlaSessionId`, `DurationMs`, `Timestamp`

  [Logs](https://learn.microsoft.com/en-us/fabric/enterprise/powerbi/semantic-model-operations)
- **Distinguishing Copilot or data-agent DAX:** **not documented.** No published ApplicationName or ApplicationContext value identifies Copilot, a Fabric data agent or Fabric IQ MCP. A practical discriminator is a dedicated test UPN (`ExecutingUser`) + a tight time window + `ItemId` + a DAX fingerprint; verify ApplicationName empirically.
- **Ingestion latency:** not documented in the sources found.
- Power BI Log Analytics, activity events for data agents, and XMLA traces weren't re-verified in this pass.

## 7. Ground-truth execution
- **executeQueries:** `POST https://api.powerbi.com/v1.0/myorg/datasets/{id}/executeQueries`. Tenant setting "Dataset Execute Queries REST API"; read + build permission. Limits:
  - One query and one table per call.
  - 100k rows or 1M values, 15 MB.
  - 120 requests/min/user.
  - DAX only; no INFO, DMV or MDX.

  SPN needs "Allow service principals to use Power BI APIs" and isn't supported for RLS or SSO models. `impersonatedUserName` is available for RLS. [executeQueries](https://learn.microsoft.com/en-us/rest/api/power-bi/datasets/execute-queries)
- **Fabric IQ MCP `ExecuteQuery`:** a GA delegated alternative.
- **sempy `evaluate_dax` and XMLA:** not re-verified this pass.

## 8. Demo-tenant prerequisites
- **Licences:** M365 Copilot (Chat API, Fabric IQ in Chat and Agent Builder all require it); Power BI Pro/PPU for content access. The Agent Evaluations CLI "consumes Copilot credits" and needs usage-based billing on. [Quickstart](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-quickstart) Copilot Studio evaluations also use credits.
- **Capacity:** F2+ or P1+ for data agents. Native Fabric IQ in Chat works on Pro, PPU or Fabric (not A/EM SKUs). The tenant region must support all Fabric workloads.
- **Settings:**
  - M365 admin center: "Fabric data available in M365 Copilot" (on by default).
  - Fabric: "Share Fabric data with your Microsoft 365 services" (for discovery); "Data sent to Azure OpenAI can be processed outside…" and the storage equivalent (for non-US/EU tenants); "Users can access Microsoft Copilot in Power BI and Microsoft Fabric" (preview, off by default).
  - Power BI: Dataset Execute Queries REST API; service principals can use Fabric/Power BI APIs; Copilot extensibility in M365. [Chat](https://learn.microsoft.com/en-us/fabric/iq/connectors/microsoft-365-copilot-overview), [Copilot in PBI](https://learn.microsoft.com/en-us/fabric/iq/connectors/copilot-power-bi-fabric)
- **Azure:** a Foundry project with a model deployment (CLI default `gpt-5-mini`) for LLM graders. [CLI](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-overview)

## Implications for an automated eval harness

| Path | End-to-end via API? | Routing evidence | Value check |
|---|---|---|---|
| Base Chat API | Yes (delegated, beta) | `attributions[]` only; no agent field | Text match |
| Native Fabric IQ in Copilot Chat (UI) | **No API documented** | SemanticModelLogs only | UI or Playwright (fragile) |
| Declarative agent + Fabric capability | **Yes** via Agent Evaluations CLI (`runevals`, `--m365-agent-id`) | SemanticModelLogs; CLI retrieval evaluators expose `retrieval_executions[]`, but documented capabilities are OneDriveAndSharePoint/Email/GraphConnectors (Fabric **unverified**) | ExactMatch / PartialMatch / Similarity |
| Fabric data agent in M365 Agent Store | Only if wrapped as a worker agent of a declarative agent (unverified) | Purview AgentId/AgentName (async); SemanticModelLogs | CLI |
| Copilot Studio + data agent (standard harness, connected agent) | **Yes**: Power Platform eval API + Tool use grader; CopilotClient; Kit Plan Validation | Tool use pass/fail; transcripts; App Insights ExecuteTool span | Exact / Compare meaning |
| Copilot Studio + Fabric IQ Data MCP tool (GitHub harness) | Partial: UI evals; REST/CopilotClient not officially supported | Env-level ExecuteTool spans | General quality (others unclear) |
| Data agent MCP or evaluate_data_agent | **Yes** (user or SPN) | `_steps` table + SemanticModelLogs | Expected answer |
| Fabric IQ MCP (own client) | **Yes** (delegated) | Explicit ExecuteQuery with model ID | Exact |

**Recommendation:**
- **Primary:** a declarative agent (Agents Toolkit, manifest 1.9 Fabric capability, instructions requiring source citation) run nightly by `runevals` under a dedicated licensed test user. Assert the value with ExactMatch/PartialMatch. Assert routing by joining on test UPN + timestamp window + expected `ItemId` in SemanticModelLogs, and check that `EventText` references the expected measure. Ground truth comes from executeQueries (impersonating the test UPN where RLS applies).
- **Secondary:** a standard-harness Copilot Studio agent with the data agent connected, driven by the Power Platform evaluation API with Tool use + Exact match graders, plus the same Fabric-log join.
- **Diagnostic layer:** use `evaluate_data_agent` and Fabric IQ MCP to isolate the data or semantic layer from orchestration failures.
- Keep the Chat API as a baseline/negative control only.

## Conclusion
Routing proof is fundamentally a **server-side** problem. Copilot-side APIs expose answers and, at best, agent identity; they don't expose which semantic model a DAX query hit. Fabric's engine logs are the only documented artefact that names the model (`ItemId`) and the query (`EventText`) together. A sound harness pairs a programmable agent surface with that log plus an independent DAX ground truth. Because the Chat API stays beta, delegated-only and agent-less, the agent surfaces with first-party eval tooling are the realistic automation points.

## Limitations & residual risks
- **Pre-mortem:** (1) the SemanticModelLogs fields can't reliably separate Copilot DAX from other traffic; (2) the harness split blocks the REST eval path for the Fabric tool; (3) a preview API changes (Chat API, Copilot Studio eval). Mitigation: spike all three in week 1.
- The Foundry Fabric data agent tool is deprecated on 6 Nov 2026, so don't build on it.

## Open uncertainties
1. Does the Chat API trigger Fabric IQ Power BI answering? (undocumented)
2. Does the manifest 1.9 Fabric object allow pinning specific models or reports?
3. Is `retrieval_executions` populated for Fabric in the Agent Evaluations CLI?
4. ApplicationName/ApplicationContext values for Copilot, data agent and MCP DAX; workspace monitoring ingestion latency.
5. Do Purview `AccessedResources` or `AISystemPlugin` record Power BI items? Audit latency.
6. Does the data agent MCP response include the generated DAX?
7. Do CopilotClient and the evaluation REST API support the GitHub Copilot harness (README claims late Oct 2026)?
8. M365 data-agent publishing status (GA vs preview); Agent Evaluations CLI GA (README) vs "(preview)" (Learn).
9. Chat API throttling limits; Foundry → M365 Copilot publishing; sempy and XMLA details (not re-verified).

## Sources
1. [Chat API overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/overview) - Microsoft Learn, Jul 2026
2. [Create copilotConversation](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotroot-post-conversations) - Microsoft Learn
3. [copilotConversation: chat](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotconversation-chat) - Microsoft Learn
4. [chatOverStream](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotconversation-chatoverstream) - Microsoft Learn
5. [Connected agents](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/declarative-agent-connected-agent) - Microsoft Learn
6. [What's new](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/whats-new) - Microsoft Learn, Oct 2026
7. [Declarative agent schema 1.9](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/declarative-agent-manifest-1.9) - Microsoft Learn
8. [Fabric IQ in Agent Builder](https://learn.microsoft.com/en-us/fabric/iq/connectors/agent-builder-overview) - Microsoft Learn, Oct 2026
9. [Fabric IQ in M365 Copilot Chat](https://learn.microsoft.com/en-us/fabric/iq/connectors/microsoft-365-copilot-overview) - Microsoft Learn, Sep 2026
10. [Copilot in Power BI and Fabric](https://learn.microsoft.com/en-us/fabric/iq/connectors/copilot-power-bi-fabric) - Microsoft Learn
11. [What is Fabric IQ](https://learn.microsoft.com/en-us/fabric/iq/overview) - Microsoft Learn, Sep 2026
12. [Fabric IQ semantic foundation blog](https://community.fabric.microsoft.com/blog/fbc_fabricupdatesblogs/fabric-iq-the-semantic-foundation-for-enterprise-ai/5172473) - Fabric blog, Nov 2025
13. [Fabric IQ semantic layer blog](https://community.fabric.microsoft.com/blog/fbc_fabricupdatesblogs/fabric-iq-the-semantic-layer-powering-trusted-ai-agents-at-enterprise-scale/5190739) - Fabric blog, 2026
14. [InfoWorld Fabric IQ](https://www.infoworld.com/article/4093181/microsoft-fabric-iq-adds-semantic-intelligence-layer-to-fabric.html) - InfoWorld, Nov 2025
15. [Data agent in Microsoft Copilot](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-microsoft-365-copilot) - Microsoft Learn, Oct 2026
16. [Data agent as Copilot Studio tool](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-microsoft-copilot-studio-tool) - Microsoft Learn, Aug 2026
17. [Data agent connected agent](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-microsoft-copilot-studio) - Microsoft Learn
18. [Fabric IQ MCP](https://learn.microsoft.com/en-us/fabric/iq/connectors/fabric-iq-mcp) - Microsoft Learn, Oct 2026
19. [Power BI Consumption MCP](https://learn.microsoft.com/en-us/power-bi/developer/mcp/remote-mcp-server-get-started) - Microsoft Learn
20. [Data agent MCP server](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-mcp-server) - Microsoft Learn, Sep 2026
21. [Data agent SDK](https://learn.microsoft.com/en-us/fabric/data-science/fabric-data-agent-sdk) - Microsoft Learn
22. [Python client](https://learn.microsoft.com/en-us/fabric/data-science/consume-data-agent-python) - Microsoft Learn, Aug 2026
23. [Data agent SPN](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-service-principal) - Microsoft Learn
24. [Create data agent](https://learn.microsoft.com/en-us/fabric/data-science/how-to-create-data-agent) - Microsoft Learn
25. [Evaluate data agent](https://learn.microsoft.com/en-us/fabric/data-science/evaluate-data-agent) - Microsoft Learn
26. [Foundry Fabric tool](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/fabric) - Microsoft Learn, Sep 2026
27. [getAllEnterpriseInteractions](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/interaction-export/aiinteractionhistory-getallenterpriseinteractions) - Microsoft Learn
28. [aiInteraction](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/interaction-export/resources/aiinteraction) - Microsoft Learn
29. [Purview Copilot audit](https://learn.microsoft.com/en-us/purview/audit-copilot) - Microsoft Learn, Aug 2026
30. [auditLogQuery](https://learn.microsoft.com/en-us/graph/api/resources/security-auditlogquery?view=graph-rest-1.0) - Microsoft Graph, Oct 2026
31. [CopilotInteraction schema](https://learn.microsoft.com/en-us/office/office-365-management-api/copilot-schema) - Microsoft Learn, 2024
32. [Agent 365 GA](https://www.microsoft.com/en-us/security/blog/2026/05/01/microsoft-agent-365-now-generally-available-expands-capabilities-and-integrations/) - Microsoft Security Blog, May 2026
33. [Microsoft OpenTelemetry Distro](https://learn.microsoft.com/en-us/microsoft-agent-365/developer/microsoft-opentelemetry) - Microsoft Learn
34. [Semantic model operation logs](https://learn.microsoft.com/en-us/fabric/enterprise/powerbi/semantic-model-operations) - Microsoft Learn
35. [executeQueries](https://learn.microsoft.com/en-us/rest/api/power-bi/datasets/execute-queries) - Microsoft Learn
36. [Prep data for AI](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-prepare-data-ai) - Microsoft Learn
37. [Verified answers](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-prepare-data-ai-verified-answers) - Microsoft Learn
38. [Copilot Studio eval methods](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-overview) - Microsoft Learn
39. [Copilot Studio eval REST](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-rest-api) - Microsoft Learn
40. [Run Maker Evaluation Test Set](https://learn.microsoft.com/en-us/rest/api/power-platform/copilotstudio/bots/run-maker-evaluation-test-set) - Microsoft Learn
41. [Evaluate (new harness)](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/analytics-agent-evaluation-intro) - Microsoft Learn, Oct 2026
42. [Agent Kit tests](https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/kit-configure-tests) - Microsoft Learn, Jul 2026
43. [Agents SDK + Copilot Studio](https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/integrate-with-mcs) - Microsoft Learn, Oct 2026
44. [CopilotStudio client README](https://github.com/microsoft/Agents/blob/main/samples/python/copilotstudio-client/README.md) - GitHub
45. [Env-level App Insights telemetry](https://learn.microsoft.com/en-us/microsoft-copilot-studio/advanced-environment-level-agent-telemetry) - Microsoft Learn
46. [Agent Evaluations CLI](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-overview) - Microsoft Learn, Sep 2026
47. [CLI evaluators](https://github.com/MicrosoftDocs/m365copilot-docs/blob/main/docs/evaluations-cli-evaluators.md) - GitHub, Jun 2026
48. [CLI quickstart](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/evaluations-cli-quickstart) - Microsoft Learn
49. [spknowledge Copilot API limits](https://spknowledge.com/2026/08/17/microsoft-365-copilot-api-rate-limits-error-handling-national-cloud/) - Blog (LOW trust), Aug 2026
