#!/usr/bin/env bash
# =============================================================================================
# Deploy the Azure resources for copilot-fabriciq-evals (docs/deployment.md, step 2).
#
#   infra/azure/deploy.sh --resource-group rg-copilot-evals --location eastus2 [options]
#
# Options:
#   --kind AIServices|OpenAI   Foundry resource with a project (default), or Azure OpenAI only
#   --ci-principal-id ID       object ID of the copilot-eval-ci service principal (infra/entra output)
#   --runner                   also deploy the self-hosted runner VM
#   --ssh-key PATH             SSH public key for the runner (default: ~/.ssh/id_ed25519.pub)
#   --name-prefix PREFIX       resource name prefix (default: cfiq)
#   --what-if                  show what would change, deploy nothing
#
# Needs the Azure CLI (2.61 or later, `az bicep install`), `az login`, and Owner, or Contributor
# plus Role Based Access Control Administrator, on the resource group: the template assigns roles.
# Prints the values to copy into config/settings.toml.
# =============================================================================================
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
resource_group=""
location="eastus2"
kind="AIServices"
ci_principal_id=""
runner="false"
ssh_key="${HOME}/.ssh/id_ed25519.pub"
name_prefix="cfiq"
what_if="false"

usage() { sed -n '3,18p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --resource-group|-g) resource_group="$2"; shift 2 ;;
    --location|-l)       location="$2"; shift 2 ;;
    --kind)              kind="$2"; shift 2 ;;
    --ci-principal-id)   ci_principal_id="$2"; shift 2 ;;
    --runner)            runner="true"; shift ;;
    --ssh-key)           ssh_key="$2"; shift 2 ;;
    --name-prefix)       name_prefix="$2"; shift 2 ;;
    --what-if)           what_if="true"; shift ;;
    -h|--help)           usage 0 ;;
    *) echo "unknown option: $1" >&2; usage 2 ;;
  esac
done
[[ -n "$resource_group" ]] || { echo "--resource-group is required" >&2; usage 2; }

export CFIQ_LOCATION="$location" CFIQ_ACCOUNT_KIND="$kind" CFIQ_NAME_PREFIX="$name_prefix"
export CFIQ_CI_PRINCIPAL_ID="$ci_principal_id" CFIQ_DEPLOY_RUNNER="$runner"
CFIQ_OPERATOR_PRINCIPAL_ID="$(az ad signed-in-user show --query id -o tsv)"
export CFIQ_OPERATOR_PRINCIPAL_ID
if [[ "$runner" == "true" ]]; then
  [[ -f "$ssh_key" ]] || { echo "SSH public key not found: $ssh_key (use --ssh-key)" >&2; exit 2; }
  CFIQ_RUNNER_SSH_PUBLIC_KEY="$(cat "$ssh_key")"
  export CFIQ_RUNNER_SSH_PUBLIC_KEY
fi

echo "Resource group ${resource_group} in ${location} (${kind}, runner: ${runner})"
az group create --name "$resource_group" --location "$location" \
  --tags project=copilot-fabriciq-evals environment=demo --output none

deployment="copilot-evals-$(date -u +%Y%m%d%H%M%S)"
if [[ "$what_if" == "true" ]]; then
  az deployment group what-if --resource-group "$resource_group" --name "$deployment" \
    --parameters "${here}/main.bicepparam"
  exit 0
fi
az deployment group create --resource-group "$resource_group" --name "$deployment" \
  --parameters "${here}/main.bicepparam" --output none

outputs="$(az deployment group show --resource-group "$resource_group" --name "$deployment" \
  --query properties.outputs --output json)"
value() { jq -r --arg key "$1" '.[$key].value' <<<"$outputs"; }

cat <<EOF

Deployed. Copy into config/settings.toml:

[azure]
subscription_id = "$(az account show --query id -o tsv)"
key_vault_url = "$(value keyVaultUrl)"

[foundry]
endpoint = "$(value foundryProjectEndpoint)"
judge_deployment = "$(value judgeDeployment)"

[azure_openai]
endpoint = "$(value openAiEndpoint)"
orchestrator_model = "$(value judgeDeployment)"
judge_model = "$(value judgeDeployment)"
EOF
if [[ "$runner" == "true" ]]; then
  echo
  echo "Runner VM: $(value runnerVmName). Register it with GitHub:"
  echo "  infra/azure/register-runner.sh --resource-group ${resource_group} --vm $(value runnerVmName) --repo <owner>/<repo>"
fi
