# Live Microsoft 365 Copilot Chat Quickstart

Evaluate a live Microsoft 365 Copilot Chat tenant against Power BI / Fabric semantic models (`fabric-iq`) or workplace documents (`work-iq`).

## Prerequisites

1. **Isolated synthetic test user** (for example `eval.tester@contoso.com` in `contoso.com`) licensed for Microsoft 365 Copilot and granted viewer/read access to the target Power BI reports, semantic models, or SharePoint/OneDrive files. See [Prerequisites](prerequisites.md) and [First Live Run](first-live-run.md).
2. **Entra public-client app registration** configured with the delegated Microsoft Graph permissions required by the Microsoft 365 Copilot Chat API (`Sites.Read.All`, `Mail.Read`, `People.Read.All`, `OnlineMeetingTranscript.Read.All`, `Chat.Read`, `ChannelMessage.Read.All`, `ExternalItem.Read.All`).
3. *(Optional, recommended for `engine+citations` tier)* **Fabric Workspace Monitoring** enabled on workspaces hosting expected and decoy semantic models so `SemanticModelLogs` flow into a monitoring Eventhouse. See [Fabric Workspace Setup](../how-to/fabric-setup.md).

## 1. Install Live Extras

```powershell
python -m pip install -e ".[copilot,kusto,judge]"
```

## 2. Configure `.env`

Copy `.env.example` to `.env` (gitignored) and populate your tenant and target settings:

```ini
CFEVAL_TENANT_ID=00000000-0000-0000-0000-000000000000
CFEVAL_COPILOT_CLIENT_ID=11111111-1111-1111-1111-111111111111
CFEVAL_TEST_USER_UPN=eval.tester@contoso.com

# Optional: Fabric Workspace Monitoring KQL endpoint for engine+citations tier
CFEVAL_MONITORING_KUSTO_URI=https://trd-example.z0.kusto.fabric.microsoft.com
CFEVAL_MONITORING_DATABASE=WorkspaceMonitoring
```

Full environment variable reference: [Configuration Reference](../reference/configuration.md).

## 3. Run Chat-Only (`citations-only` Tier)

Start with `--collector none` (or omit `CFEVAL_MONITORING_KUSTO_URI`) to validate authentication, prompts, and report citations before adding KQL correlation:

```powershell
python -m cfeval run `
  --target copilot-chat `
  --golden data/golden/contoso-smoke.yaml `
  --run-id live-chat-smoke-01 `
  --no-publish
```

When prompted for interactive or device-code sign-in, verify that you authenticate as the intended evaluation account (`eval.tester@contoso.com`) in the expected tenant before approving.

## 4. Add Workspace Monitoring Correlation (`engine+citations` Tier)

Once `CFEVAL_MONITORING_KUSTO_URI` and `CFEVAL_MONITORING_DATABASE` are set, `cfeval` polls `SemanticModelLogs` after the conversation batch and joins engine-executed DAX queries back to each ask:

```powershell
python -m cfeval run `
  --target copilot-chat `
  --collector kql `
  --golden data/golden/contoso.yaml `
  --trials 3 `
  --run-id live-fabric-iq-01
```

## Next Steps

- Prepare semantic models and Eventhouse tables in [Fabric Workspace Setup](../how-to/fabric-setup.md).
- Author golden questions tailored to your own business models in [Author Golden Sets](../how-to/author-golden-sets.md).
- Diagnose auth, throttling, or correlation lag in [Troubleshooting](../how-to/troubleshooting.md).
