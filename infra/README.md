# Infrastructure

Scripted setup for the identities and Azure resources the harness needs (backlog task **P0.2**). The tenant checklist (PLAN §6, issue `[T1-T21]`) tracks what must exist; [docs/deployment.md](../docs/deployment.md) walks through the whole deployment in order. Nothing tenant-specific is committed: scripts take parameters and print the values for `config/settings.toml`.

| Path | What it does |
|---|---|
| [`entra/New-EvalAppRegistrations.ps1`](entra/New-EvalAppRegistrations.ps1) | Creates or updates four app registrations: `copilot-eval-public` (persona tokens), `copilot-eval-setup` (`evals deploy`), `copilot-eval-daemon` (telemetry; certificate in Key Vault) and `copilot-eval-ci` (GitHub OIDC federated credential, no secret). Permissions are resolved by name. Admin consent only with `-GrantAdminConsent`. |
| [`azure/main.bicep`](azure/main.bicep) | A Microsoft Foundry resource with a project and a `gpt-5-mini` deployment, or an Azure OpenAI resource (`accountKind`); a Key Vault with RBAC; optionally the runner VM. Least-privilege role assignments. |
| [`azure/modules/`](azure/modules) | `ai.bicep` (model resource, project, deployment, model access), `keyvault.bicep`, `runner.bicep` (VM, network with NAT gateway and no public IP, its role assignments). |
| [`azure/main.bicepparam`](azure/main.bicepparam) | Example parameters; reads identities from environment variables set by `deploy.sh`. |
| [`azure/deploy.sh`](azure/deploy.sh) | Creates the resource group, deploys (or `--what-if`), and prints the settings to copy. |
| [`azure/register-runner.sh`](azure/register-runner.sh) | Registers the runner VM with GitHub through `az vm run-command`, after verifying the runner package's published SHA-256. |
| [`azure/cloud-init/runner.yaml`](azure/cloud-init/runner.yaml) | Runner prerequisites: uv, Node 24 and the Azure CLI from the Microsoft package repository. |

## Roles assigned

| Identity | On the Foundry resource | On the Key Vault |
|---|---|---|
| `copilot-eval-ci` (GitHub Actions) | Foundry User, or Cognitive Services OpenAI User on an Azure OpenAI resource | Key Vault Secrets User |
| You (the operator) | the same model role | Key Vault Secrets Officer and Certificates Officer |
| The runner VM's managed identity | the same model role | Key Vault Secrets User |
| The Foundry project's managed identity | Foundry User | none |

## Still manual

- **Admin consent** for the app registrations (or `-GrantAdminConsent`).
- **Licences** for the personas, and the Fabric capacity.
- **Tenant settings** in the Fabric admin portal and the Microsoft 365 admin center (PLAN §6 T6–T10, T21).

## Notes

- API versions and role IDs were taken from Microsoft Learn on 3 November 2026. If a deployment reports an unsupported API version, list the supported ones with `az provider show --namespace Microsoft.CognitiveServices --query "resourceTypes[?resourceType=='accounts'].apiVersions"`.
- `az bicep build infra/azure/main.bicep` compiles the template without deploying; run it after any change.
