// =============================================================================================
// copilot-fabriciq-evals: Azure resources for the evaluation harness
//
//   * a Microsoft Foundry resource (kind AIServices) with a project and a gpt-5-mini deployment,
//     serving the Foundry evaluation path, the local path's AI judge and the L1 orchestrator;
//     or, with accountKind = 'OpenAI', an Azure OpenAI resource for the local path only;
//   * a Key Vault (RBAC) for persona token caches and the daemon certificate (PLAN §11);
//   * optionally, the self-hosted GitHub Actions runner VM with a managed identity (P9.2).
//
// Role assignments follow least privilege (PLAN §6 T18, T19): Foundry User on a Foundry resource
// (Cognitive Services OpenAI User on an Azure OpenAI resource) and Key Vault Secrets User for the
// identities that run evaluations; Secrets and Certificates Officer for the operator.
//
// Deploy with infra/azure/deploy.sh (docs/deployment.md, step 1). Nothing tenant-specific is
// committed: identities and the SSH key are parameters (main.bicepparam is an example).
// =============================================================================================

targetScope = 'resourceGroup'

@description('Azure region. Use one where gpt-5-mini (GlobalStandard) and Foundry evaluations are available, for example eastus2 or swedencentral.')
param location string = resourceGroup().location

@description('Short prefix for resource names (3-10 lower-case letters or digits).')
@minLength(3)
@maxLength(10)
param namePrefix string = 'cfiq'

@description('AIServices: a Microsoft Foundry resource with a project (both evaluation paths, ADR-009). OpenAI: an Azure OpenAI resource only (local path; no Foundry project).')
@allowed([
  'AIServices'
  'OpenAI'
])
param accountKind string = 'AIServices'

@description('Create the Foundry project the Foundry evaluation path uses. Ignored when accountKind is OpenAI.')
param createProject bool = true

@description('The model deployment used as AI judge, extraction step and L1 orchestrator ([foundry] judge_deployment, [azure_openai] judge_model).')
param judgeModel object = {
  name: 'gpt-5-mini'
  version: '2025-08-07'
  sku: 'GlobalStandard'
  capacity: 50 // thousands of tokens per minute
}

@description('Object ID of the copilot-eval-ci service principal (GitHub Actions OIDC) from infra/entra. Empty to skip.')
param ciPrincipalId string = ''

@description('Object ID of the person who operates the harness: Key Vault secrets and certificates, and model access for local runs. Empty to skip.')
param operatorPrincipalId string = ''

@description('Deploy the self-hosted GitHub Actions runner VM (P9.2). Needed for the agent_cli surface and long live runs.')
param deployRunner bool = false

@description('Runner VM size.')
param runnerVmSize string = 'Standard_D2s_v5'

@description('Runner VM administrator user name.')
param runnerAdminUsername string = 'azureuser'

@description('SSH public key for the runner VM. Required when deployRunner is true; password sign-in is disabled.')
param runnerSshPublicKey string = ''

@description('Tags applied to every resource.')
param tags object = {
  project: 'copilot-fabriciq-evals'
  environment: 'demo'
}

var suffix = uniqueString(resourceGroup().id)
var accountName = '${namePrefix}-ai-${suffix}'
var keyVaultName = take('${namePrefix}-kv-${suffix}', 24)

var evaluators = concat(
  empty(ciPrincipalId) ? [] : [{ principalId: ciPrincipalId, principalType: 'ServicePrincipal' }],
  empty(operatorPrincipalId) ? [] : [{ principalId: operatorPrincipalId, principalType: 'User' }]
)

module ai 'modules/ai.bicep' = {
  name: 'ai'
  params: {
    location: location
    accountName: accountName
    accountKind: accountKind
    createProject: createProject && accountKind == 'AIServices'
    projectName: '${namePrefix}-evals'
    judgeModel: judgeModel
    modelUsers: evaluators
    tags: tags
  }
}

module keyVault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    location: location
    keyVaultName: keyVaultName
    secretReaders: empty(ciPrincipalId) ? [] : [{ principalId: ciPrincipalId, principalType: 'ServicePrincipal' }]
    officers: empty(operatorPrincipalId) ? [] : [{ principalId: operatorPrincipalId, principalType: 'User' }]
    tags: tags
  }
}

module runner 'modules/runner.bicep' = if (deployRunner) {
  name: 'runner'
  params: {
    location: location
    namePrefix: namePrefix
    vmSize: runnerVmSize
    adminUsername: runnerAdminUsername
    sshPublicKey: runnerSshPublicKey
    accountName: ai.outputs.accountName
    accountKind: accountKind
    keyVaultName: keyVault.outputs.keyVaultName
    tags: tags
  }
}

@description('[azure_openai] endpoint in config/settings.toml (the OpenAI v1 API).')
output openAiEndpoint string = ai.outputs.openAiEndpoint

@description('[foundry] endpoint in config/settings.toml; empty without a project.')
output foundryProjectEndpoint string = ai.outputs.projectEndpoint

@description('[foundry] judge_deployment and [azure_openai] judge_model / orchestrator_model.')
output judgeDeployment string = ai.outputs.deploymentName

@description('[azure] key_vault_url in config/settings.toml.')
output keyVaultUrl string = keyVault.outputs.keyVaultUri

@description('Runner VM name, for infra/azure/register-runner.sh; empty when not deployed.')
output runnerVmName string = deployRunner ? runner!.outputs.vmName : ''
