// Self-hosted GitHub Actions runner (PLAN §9.2, backlog P9.2): an Ubuntu 24.04 VM with a
// system-assigned managed identity, no public IP and no inbound rules. Outbound internet goes
// through a NAT gateway, because new virtual networks have no default outbound access.
// GitHub registration is a separate step: infra/azure/register-runner.sh. Called by main.bicep.

param location string
param namePrefix string
param vmSize string
param adminUsername string

@description('SSH public key; password sign-in is disabled.')
param sshPublicKey string
param accountName string

@allowed([
  'AIServices'
  'OpenAI'
])
param accountKind string
param keyVaultName string
param tags object

var foundryUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var openAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var secretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var modelRoleId = accountKind == 'AIServices' ? foundryUserRoleId : openAiUserRoleId
var vmName = '${namePrefix}-runner'

resource publicIp 'Microsoft.Network/publicIPAddresses@2026-03-01' = {
  name: '${namePrefix}-nat-ip'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
  }
}

resource natGateway 'Microsoft.Network/natGateways@2026-03-01' = {
  name: '${namePrefix}-nat'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIpAddresses: [
      {
        id: publicIp.id
      }
    ]
  }
}

resource nsg 'Microsoft.Network/networkSecurityGroups@2026-03-01' = {
  name: '${namePrefix}-runner-nsg'
  location: location
  tags: tags
  properties: {
    securityRules: [] // the defaults deny all inbound traffic from the internet
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2026-03-01' = {
  name: '${namePrefix}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.42.0.0/24'
      ]
    }
    subnets: [
      {
        name: 'runner'
        properties: {
          addressPrefix: '10.42.0.0/27'
          natGateway: {
            id: natGateway.id
          }
          networkSecurityGroup: {
            id: nsg.id
          }
        }
      }
    ]
  }
}

resource nic 'Microsoft.Network/networkInterfaces@2026-03-01' = {
  name: '${vmName}-nic'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: {
            id: vnet.properties.subnets[0].id
          }
        }
      }
    ]
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2026-04-01' = {
  name: vmName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    hardwareProfile: {
      vmSize: vmSize
    }
    securityProfile: {
      securityType: 'TrustedLaunch'
      uefiSettings: {
        secureBootEnabled: true
        vTpmEnabled: true
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        diskSizeGB: 64
        deleteOption: 'Delete'
        managedDisk: {
          storageAccountType: 'StandardSSD_LRS'
        }
      }
    }
    osProfile: {
      computerName: vmName
      adminUsername: adminUsername
      customData: base64(loadTextContent('../cloud-init/runner.yaml'))
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: sshPublicKey
            }
          ]
        }
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: nic.id
          properties: {
            deleteOption: 'Delete'
          }
        }
      ]
    }
  }
}

resource account 'Microsoft.CognitiveServices/accounts@2026-09-01' existing = {
  name: accountName
}

resource vault 'Microsoft.KeyVault/vaults@2026-05-15' existing = {
  name: keyVaultName
}

resource runnerModelAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, vm.id, modelRoleId)
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', modelRoleId)
    principalId: vm.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource runnerSecretsAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, vm.id, secretsUserRoleId)
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleId)
    principalId: vm.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output vmName string = vm.name
output principalId string = vm.identity.principalId
