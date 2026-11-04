<#
.SYNOPSIS
    Creates the Microsoft Entra ID app registrations for copilot-fabriciq-evals (PLAN §11).

.DESCRIPTION
    Idempotent: each app is found by display name and created only when missing; its API
    permissions are brought up to date on every run. Permissions are resolved by name from each
    resource's service principal, so no permission ID is hard-coded.

      copilot-eval-public  Public client. Delegated permissions the personas' tokens need: the
                           Microsoft 365 Copilot Chat API (Graph), Power BI query and Fabric IQ
                           scopes, and Work IQ (when Work IQ is enabled in the tenant).
      copilot-eval-setup   Public client. Delegated permissions for `evals deploy`: Fabric and
                           Power BI write scopes, SharePoint upload, directory lookups, OneLake read.
      copilot-eval-daemon  Confidential client with a certificate. Application permissions for
                           telemetry: Copilot interaction export and the Purview audit query API.
      copilot-eval-ci      GitHub Actions identity: an OIDC federated credential for the
                           repository's environment, no secrets. Its object ID goes to Bicep.

    Admin consent is a separate, deliberate step: pass -GrantAdminConsent to grant it here
    (needs Privileged Role Administrator or Global Administrator), or grant it in the Entra admin
    center. Prints the values to copy into config/settings.toml and GitHub.

.PARAMETER TenantId
    The Microsoft Entra tenant ID.

.PARAMETER GitHubRepository
    owner/name of the GitHub repository whose workflows sign in as copilot-eval-ci.

.PARAMETER GitHubEnvironment
    The GitHub environment the live workflows run in (default eval-demo).

.PARAMETER KeyVaultName
    Optional. Creates the daemon certificate in this Key Vault (Azure CLI, signed in) and attaches
    its public key to copilot-eval-daemon. Without it, attach a certificate yourself.

.PARAMETER GrantAdminConsent
    Grant tenant-wide admin consent for every permission requested here.

.EXAMPLE
    ./infra/entra/New-EvalAppRegistrations.ps1 -TenantId <tenant-id> -GitHubRepository contoso/copilot-fabriciq-evals -KeyVaultName <vault>

.NOTES
    Requires PowerShell 7 and the Microsoft Graph PowerShell SDK:
        Install-Module Microsoft.Graph.Applications, Microsoft.Graph.Identity.SignIns -Scope CurrentUser
    The signed-in account needs Application Administrator (or Cloud Application Administrator).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $TenantId,
    [Parameter(Mandatory)] [ValidatePattern('^[\w.-]+/[\w.-]+$')] [string] $GitHubRepository,
    [string] $GitHubEnvironment = 'eval-demo',
    [string] $KeyVaultName = '',
    [switch] $GrantAdminConsent
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Well-known resource application IDs.
$Graph = '00000003-0000-0000-c000-000000000000'    # Microsoft Graph
$PowerBI = '00000009-0000-0000-c000-000000000000'  # Power BI Service (also serves the Fabric REST API)
$Storage = 'e406a681-f3d4-42a8-90b6-c2b029497af1'  # Azure Storage (OneLake)
$WorkIQ = 'fdcc1f02-fc51-4226-8753-f668596af7f7'   # Work IQ (present once Work IQ is enabled, PLAN §6 T21)

# What each app asks for: resource app ID -> delegated scopes / application roles.
$Apps = [ordered]@{
    'copilot-eval-public' = @{
        PublicClient = $true
        Delegated    = [ordered]@{
            $Graph   = @('Sites.Read.All', 'Mail.Read', 'People.Read.All', 'OnlineMeetingTranscript.Read.All',
                'Chat.Read', 'ChannelMessage.Read.All', 'ExternalItem.Read.All', 'offline_access')
            $PowerBI = @('Dataset.Read.All', 'Item.Read.All', 'Item.Execute.All')
            $WorkIQ  = @('WorkIQAgent.Ask')
        }
        Application  = @{}
    }
    'copilot-eval-setup'  = @{
        PublicClient = $true
        Delegated    = [ordered]@{
            $PowerBI = @('Workspace.ReadWrite.All', 'Item.ReadWrite.All', 'Item.Execute.All', 'Capacity.Read.All',
                'Dataset.ReadWrite.All')
            $Graph   = @('User.ReadBasic.All', 'Application.Read.All', 'Sites.ReadWrite.All', 'offline_access')
            $Storage = @('user_impersonation')
        }
        Application  = @{}
    }
    'copilot-eval-daemon' = @{
        PublicClient = $false
        Delegated    = @{}
        Application  = [ordered]@{
            $Graph = @('AiEnterpriseInteraction.Read.All', 'AuditLogsQuery.Read.All')
        }
    }
    'copilot-eval-ci'     = @{
        PublicClient = $false
        Delegated    = @{}
        Application  = @{}
    }
}

$scopes = @('Application.ReadWrite.All')
if ($GrantAdminConsent) { $scopes += @('AppRoleAssignment.ReadWrite.All', 'DelegatedPermissionGrant.ReadWrite.All') }
Connect-MgGraph -TenantId $TenantId -Scopes $scopes -NoWelcome

$resourceCache = @{}
function Get-ResourcePrincipal([string] $AppId) {
    if (-not $resourceCache.ContainsKey($AppId)) {
        $resourceCache[$AppId] = Get-MgServicePrincipal -Filter "appId eq '$AppId'" -Top 1
    }
    return $resourceCache[$AppId]
}

function Resolve-ResourceAccess([hashtable] $Spec) {
    # Builds requiredResourceAccess from permission names; skips (with a warning) what the tenant lacks.
    $access = @()
    foreach ($kind in 'Delegated', 'Application') {
        foreach ($resourceAppId in $Spec[$kind].Keys) {
            $resource = Get-ResourcePrincipal $resourceAppId
            if (-not $resource) {
                Write-Warning "Resource $resourceAppId is not in this tenant; skipped $($Spec[$kind][$resourceAppId] -join ', ')."
                continue
            }
            $entries = foreach ($name in $Spec[$kind][$resourceAppId]) {
                if ($kind -eq 'Delegated') {
                    $match = $resource.Oauth2PermissionScopes | Where-Object Value -EQ $name
                    if ($match) { @{ Id = $match.Id; Type = 'Scope' } } else { Write-Warning "$($resource.DisplayName) has no delegated scope $name." }
                } else {
                    $match = $resource.AppRoles | Where-Object Value -EQ $name
                    if ($match) { @{ Id = $match.Id; Type = 'Role' } } else { Write-Warning "$($resource.DisplayName) has no app role $name." }
                }
            }
            $existing = $access | Where-Object { $_.ResourceAppId -eq $resourceAppId }
            if ($existing) { $existing.ResourceAccess += @($entries) }
            elseif ($entries) { $access += @{ ResourceAppId = $resourceAppId; ResourceAccess = @($entries) } }
        }
    }
    return $access
}

function Set-EvalApp([string] $Name, [hashtable] $Spec) {
    $access = Resolve-ResourceAccess $Spec
    $app = Get-MgApplication -Filter "displayName eq '$Name'" -Top 1
    $common = @{ RequiredResourceAccess = $access; SignInAudience = 'AzureADMyOrg' }
    if ($Spec.PublicClient) {
        $common.IsFallbackPublicClient = $true
        $common.PublicClient = @{ RedirectUris = @('http://localhost') }
    }
    if (-not $app) {
        $app = New-MgApplication -DisplayName $Name @common
        Write-Host "Created $Name ($($app.AppId))"
    } else {
        Update-MgApplication -ApplicationId $app.Id @common
        Write-Host "Updated $Name ($($app.AppId))"
    }
    $principal = Get-MgServicePrincipal -Filter "appId eq '$($app.AppId)'" -Top 1
    if (-not $principal) { $principal = New-MgServicePrincipal -AppId $app.AppId }
    return [pscustomobject]@{ App = $app; Principal = $principal; Access = $access }
}

function Grant-AdminConsent($Registration) {
    foreach ($resourceAccess in $Registration.Access) {
        $resource = Get-ResourcePrincipal $resourceAccess.ResourceAppId
        $delegated = @($resourceAccess.ResourceAccess | Where-Object Type -EQ 'Scope' | ForEach-Object {
                $id = $_.Id; ($resource.Oauth2PermissionScopes | Where-Object Id -EQ $id).Value })
        if ($delegated) {
            $grant = Get-MgOauth2PermissionGrant -Filter "clientId eq '$($Registration.Principal.Id)' and resourceId eq '$($resource.Id)' and consentType eq 'AllPrincipals'" -Top 1
            if ($grant) { Update-MgOauth2PermissionGrant -OAuth2PermissionGrantId $grant.Id -Scope ($delegated -join ' ') }
            else {
                New-MgOauth2PermissionGrant -BodyParameter @{ ClientId = $Registration.Principal.Id; ConsentType = 'AllPrincipals'
                    ResourceId = $resource.Id; Scope = ($delegated -join ' ') } | Out-Null
            }
        }
        $assigned = @(Get-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $Registration.Principal.Id -All | ForEach-Object AppRoleId)
        foreach ($role in @($resourceAccess.ResourceAccess | Where-Object Type -EQ 'Role')) {
            if ($assigned -notcontains $role.Id) {
                New-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $Registration.Principal.Id -PrincipalId $Registration.Principal.Id `
                    -ResourceId $resource.Id -AppRoleId $role.Id | Out-Null
            }
        }
    }
    Write-Host "Admin consent granted for $($Registration.App.DisplayName)"
}

$registered = [ordered]@{}
foreach ($name in $Apps.Keys) { $registered[$name] = Set-EvalApp $name $Apps[$name] }

# GitHub Actions: OIDC federated credential for the repository environment (no client secret).
$ci = $registered['copilot-eval-ci'].App
$subject = "repo:${GitHubRepository}:environment:${GitHubEnvironment}"
$credentials = @(Get-MgApplicationFederatedIdentityCredential -ApplicationId $ci.Id)
if (-not ($credentials | Where-Object Subject -EQ $subject)) {
    New-MgApplicationFederatedIdentityCredential -ApplicationId $ci.Id -BodyParameter @{
        Name = "github-$GitHubEnvironment"; Issuer = 'https://token.actions.githubusercontent.com'
        Subject = $subject; Audiences = @('api://AzureADTokenExchange')
    } | Out-Null
    Write-Host "Federated credential added for $subject"
}

# Daemon certificate: created in Key Vault, public key attached to the app. The private key never leaves Key Vault.
if ($KeyVaultName) {
    $certificateName = 'copilot-eval-daemon'
    $existing = az keyvault certificate show --vault-name $KeyVaultName --name $certificateName --query cer -o tsv 2>$null
    if (-not $existing) {
        $policy = az keyvault certificate get-default-policy | ConvertFrom-Json
        $policy.x509CertificateProperties.subject = 'CN=copilot-eval-daemon'
        $policyFile = New-TemporaryFile
        $policy | ConvertTo-Json -Depth 10 | Set-Content $policyFile
        az keyvault certificate create --vault-name $KeyVaultName --name $certificateName --policy "@$policyFile" --output none
        Remove-Item $policyFile
        $existing = az keyvault certificate show --vault-name $KeyVaultName --name $certificateName --query cer -o tsv
    }
    $daemon = $registered['copilot-eval-daemon'].App
    Update-MgApplication -ApplicationId $daemon.Id -KeyCredentials @(@{
            Type = 'AsymmetricX509Cert'; Usage = 'Verify'; DisplayName = "$certificateName (Key Vault $KeyVaultName)"
            Key = [Convert]::FromBase64String($existing)
        })
    Write-Host "Daemon certificate attached from Key Vault $KeyVaultName"
}

if ($GrantAdminConsent) {
    foreach ($registration in $registered.Values) { if ($registration.Access) { Grant-AdminConsent $registration } }
} else {
    Write-Host "`nAdmin consent not granted. Grant it in the Entra admin center (App registrations > API permissions) or re-run with -GrantAdminConsent."
}

Write-Host @"

Copy into config/settings.toml:

[tenant]
tenant_id = "$TenantId"

[apps]
public_client_id = "$($registered['copilot-eval-public'].App.AppId)"
setup_client_id = "$($registered['copilot-eval-setup'].App.AppId)"
daemon_client_id = "$($registered['copilot-eval-daemon'].App.AppId)"

GitHub repository variables (Settings > Secrets and variables > Actions > Variables):
  AZURE_CLIENT_ID = $($ci.AppId)
  AZURE_TENANT_ID = $TenantId
  AZURE_SUBSCRIPTION_ID = <your subscription ID>

infra/azure/deploy.sh --ci-principal-id $($registered['copilot-eval-ci'].Principal.Id)
"@
