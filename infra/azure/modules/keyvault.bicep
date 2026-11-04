// Key Vault with RBAC authorization: persona MSAL token caches, the daemon certificate and the
// Teams webhook URL (PLAN §11). Called by main.bicep.

param location string
param keyVaultName string

@description('Principals that read secrets during runs: [{ principalId, principalType }].')
param secretReaders array

@description('Principals that write secrets and certificates (the operator): [{ principalId, principalType }].')
param officers array
param tags object

var secretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var secretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
var certificatesOfficerRoleId = 'a4417e6f-fecd-4de8-b567-7b0420556985'

resource vault 'Microsoft.KeyVault/vaults@2026-05-15' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    accessPolicies: []
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled' // GitHub-hosted runners read it; restrict with private endpoints if needed
  }
}

resource readers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for reader in secretReaders: {
    name: guid(vault.id, reader.principalId, secretsUserRoleId)
    scope: vault
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleId)
      principalId: reader.principalId
      principalType: reader.principalType
    }
  }
]

resource secretOfficers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for officer in officers: {
    name: guid(vault.id, officer.principalId, secretsOfficerRoleId)
    scope: vault
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsOfficerRoleId)
      principalId: officer.principalId
      principalType: officer.principalType
    }
  }
]

resource certificateOfficers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for officer in officers: {
    name: guid(vault.id, officer.principalId, certificatesOfficerRoleId)
    scope: vault
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', certificatesOfficerRoleId)
      principalId: officer.principalId
      principalType: officer.principalType
    }
  }
]

output keyVaultName string = vault.name
output keyVaultUri string = vault.properties.vaultUri
