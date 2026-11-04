// Example parameters for main.bicep. deploy.sh sets the environment variables read below, so no
// tenant-specific value is committed. Edit the literals to change sizes or names.
using 'main.bicep'

param location = readEnvironmentVariable('CFIQ_LOCATION', 'eastus2')
param namePrefix = readEnvironmentVariable('CFIQ_NAME_PREFIX', 'cfiq')
param accountKind = readEnvironmentVariable('CFIQ_ACCOUNT_KIND', 'AIServices')
param createProject = true

param judgeModel = {
  name: 'gpt-5-mini'
  version: '2025-08-07'
  sku: 'GlobalStandard'
  capacity: 50
}

// Object IDs: the copilot-eval-ci service principal (infra/entra output) and you (az ad signed-in-user show).
param ciPrincipalId = readEnvironmentVariable('CFIQ_CI_PRINCIPAL_ID', '')
param operatorPrincipalId = readEnvironmentVariable('CFIQ_OPERATOR_PRINCIPAL_ID', '')

param deployRunner = readEnvironmentVariable('CFIQ_DEPLOY_RUNNER', 'false') == 'true'
param runnerVmSize = 'Standard_D2s_v5'
param runnerAdminUsername = 'azureuser'
param runnerSshPublicKey = readEnvironmentVariable('CFIQ_RUNNER_SSH_PUBLIC_KEY', '')
