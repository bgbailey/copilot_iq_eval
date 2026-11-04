// Microsoft Foundry resource (or Azure OpenAI resource), optional project, model deployment and
// model-access role assignments. Called by main.bicep.

param location string
param accountName string

@allowed([
  'AIServices'
  'OpenAI'
])
param accountKind string
param createProject bool
param projectName string
param judgeModel object

@description('Principals that call the model and run evaluations: [{ principalId, principalType }].')
param modelUsers array
param tags object

// Built-in roles (Microsoft Learn, "Role-based access control for Microsoft Foundry").
// Foundry User (formerly Azure AI User) covers inference and evaluations on a Foundry resource;
// Cognitive Services OpenAI User is the equivalent on an Azure OpenAI resource.
var foundryUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var openAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var modelRoleId = accountKind == 'AIServices' ? foundryUserRoleId : openAiUserRoleId

resource account 'Microsoft.CognitiveServices/accounts@2026-09-01' = {
  name: accountName
  location: location
  tags: tags
  kind: accountKind
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: accountName // required for Microsoft Entra ID authentication
    disableLocalAuth: true // keys off: Entra ID only
    publicNetworkAccess: 'Enabled' // GitHub-hosted runners call it; restrict with private endpoints if needed
    allowProjectManagement: accountKind == 'AIServices'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-09-01' = if (createProject) {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'copilot-fabriciq-evals'
    description: 'Evaluation runs and results for copilot-fabriciq-evals (ADR-007, ADR-009).'
  }
}

resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2026-09-01' = {
  parent: account
  name: judgeModel.name
  sku: {
    name: judgeModel.sku
    capacity: judgeModel.capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: judgeModel.name
      version: judgeModel.version
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  dependsOn: [
    project // deployments and projects on one account are created one at a time
  ]
}

resource modelAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for user in modelUsers: {
    name: guid(account.id, user.principalId, modelRoleId)
    scope: account
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', modelRoleId)
      principalId: user.principalId
      principalType: user.principalType
    }
  }
]

// The project's managed identity runs cloud evaluations that call the judge deployment.
resource projectModelAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (createProject) {
  name: guid(account.id, projectName, foundryUserRoleId)
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
    principalId: project!.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output accountName string = account.name
output openAiEndpoint string = 'https://${accountName}.openai.azure.com/openai/v1/'
output projectEndpoint string = createProject ? 'https://${accountName}.services.ai.azure.com/api/projects/${projectName}' : ''
output deploymentName string = deployment.name
