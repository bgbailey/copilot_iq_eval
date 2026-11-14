# Prerequisites

Offline mock runs (`cfeval run --mock`), transcript scoring (`cfeval run --target transcript-import`), and the standalone scorecard preview require only Python `3.10`–`3.13` and zero cloud credentials. To evaluate live Microsoft 365 Copilot Chat and Microsoft Fabric semantic models in a demo tenant, verify the licences, identity boundaries, and workspace permissions below.

## Required Licences and Capacities

| Requirement | Scope | Why It Is Needed |
|---|---|---|
| **Microsoft 365 Copilot add-on / Premium licence** | Assigned to the dedicated test user | Required by both the [Microsoft 365 Copilot Chat API](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/overview) and [Fabric IQ in Microsoft 365 Copilot Chat](https://learn.microsoft.com/en-us/fabric/iq/connectors/microsoft-365-copilot-overview). |
| **Power BI Pro, Premium Per User (PPU), or Fabric capacity (`F2+`)** | Test user + workspaces hosting target semantic models | Grants access to query semantic models, enforce row-level and object-level security (RLS/OLS), and host the telemetry Eventhouse. |
| **Copilot enabled on target semantic models** | Tenant setting + per-model toggle | Restricted or disabled semantic models are excluded from cross-model discovery in Copilot Chat ([Copilot settings for semantic models](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-semantic-models)). |
| **Microsoft Foundry / Azure OpenAI deployment** *(optional)* | Demo Azure subscription (`Azure AI User` RBAC) | Needed only if you enable optional Layer 5 LLM-as-judge scoring (`--judge` or `--scorer foundry`). Deterministic Layers 1–4 require no judge model. |

## Dedicated Synthetic Test User Account

Always run live evaluations under a **dedicated synthetic test user** in an isolated demo tenant (for example `eval.tester@contoso.com` in `contoso.com`), **never a real employee mailbox or shared personal account**.

Why this boundary is mandatory:

1. **Delegated-only API contract**: The Microsoft 365 Copilot Chat API (`POST /beta/copilot/conversations` and `/chat`) supports delegated user authentication only—application-only service principals are not supported ([Chat API permissions](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotconversation-chat)).
2. **Broad Microsoft Graph read scopes**: Calling the Chat API requires delegated read consent across `Mail.Read`, `Chat.Read`, `ChannelMessage.Read.All`, `Sites.Read.All`, `People.Read.All`, `OnlineMeetingTranscript.Read.All`, and `ExternalItem.Read.All`. Under a real employee identity, live emails, Teams chats, meeting transcripts, and SharePoint files become eligible grounding context and could be surfaced in stored evaluation artifacts.
3. **Deterministic security perimeter**: Copilot enforces Power BI RLS/OLS and SharePoint ACLs as the signed-in user. Pinning a dedicated persona (such as `eval.tester@contoso.com`) makes expected values and decoy visibility reproducible across runs.
4. **Fail-fast claim verification**: Configure `CFEVAL_TENANT_ID`, `CFEVAL_OPERATOR_UPN`, `CFEVAL_TEST_USER_UPN`, and `CFEVAL_TENANT_LABEL` in `.env` so `cfeval login` and `cfeval run` decode the acquired token and abort immediately on any tenant or user mismatch rather than silently switching accounts.

See [Threat Model](../responsible-use/threat-model.md) for full credential, cache, and telemetry workspace controls.

## Workspace Monitoring Prerequisites

To achieve `engine+citations` routing evidence (verifying actual DAX execution rather than Graph citations alone), enable [Fabric Workspace Monitoring](https://learn.microsoft.com/en-us/fabric/fundamentals/workspace-monitoring-overview) on each workspace containing evaluated semantic models:

1. **Workspace role**: A **Workspace Admin** must enable Workspace Monitoring in **Workspace settings -> Monitoring -> Log workspace activity**, which provisions a monitoring Eventhouse collecting [`SemanticModelLogs`](https://learn.microsoft.com/en-us/fabric/enterprise/powerbi/semantic-model-operations).
2. **Multi-workspace consolidation**: One monitoring Eventhouse query URI can be queried across semantic models, or you can configure `CFEVAL_MONITORING_SOURCES` (or `CFEVAL_MONITORING_QUERY_URI` and `CFEVAL_MONITORING_DATABASE`) across expected and decoy workspaces.
3. **Evaluator read access**: Grant `eval.tester@contoso.com` **Viewer** (KQL read) access on the monitoring Eventhouse KQL database and **Viewer** + **Build** access on target semantic models (required if running `cfeval golden-refresh` to execute `reference_dax`).
4. **Telemetry Eventhouse write access**: Grant your operator / test identity **Contributor** / KQL database table-ingest permissions on the separate telemetry Eventhouse (`CFEVAL_EVENTHOUSE_QUERY_URI`, `CFEVAL_EVENTHOUSE_INGEST_URI`, `CFEVAL_EVENTHOUSE_DATABASE`) where `cfeval setup` creates the seven telemetry tables (`EvalRun`, `EvalQuestion`, `EvalAsk`, `FabricIqQuery`, `EvalScore`, `EvalResult`, `EvalEvent`).

If Workspace Monitoring cannot be enabled yet, `cfeval` still runs and grades answers at the `citations-only` evidence tier, marking engine-only assertions `INCONCLUSIVE` rather than fabricating passes.

## Local Workstation Setup

* **Python**: `3.10`, `3.11`, `3.12` (recommended), or `3.13`
* **Package installation**:
  ```bash
  pip install -e ".[live]"
  ```
* **Sign-in client**: Azure CLI (`az login --tenant <tenant-id>`) or interactive Entra public-client sign-in (`CFEVAL_CLIENT_ID`) via `cfeval login`.

## Next Steps

* [First Live Run](./first-live-run.md) — run an 8-question live smoke evaluation end to end.
* [Cost and Limits](./cost-and-limits.md) — review Fabric capacity, judge token, and wall-clock estimates before scaling up.
* [Capture Engine DAX](../how-to/capture-dax.md) — configure Workspace Monitoring and verify trace correlation with `cfeval trace probe`.
