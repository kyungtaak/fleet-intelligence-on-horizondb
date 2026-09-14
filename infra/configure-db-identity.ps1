#requires -Version 7.4

[CmdletBinding()]
param(
    [guid] $SubscriptionId,
    [ValidateSet('Check', 'WhatIf', 'Deploy')]
    [string] $Mode = 'Check',
    [ValidatePattern('^[a-zA-Z0-9_-]{1,80}$')]
    [string] $ResourceGroupName = 'rg-horizonship-dev-wus3',
    [ValidatePattern('^[a-zA-Z0-9][-a-zA-Z0-9]{0,61}[a-zA-Z0-9]$')]
    [string] $ClusterName = 'horizonship-db-6prmjv3zxbvfs',
    [ValidatePattern('^[a-zA-Z0-9_-]+$')]
    [string] $FoundryName = 'horizonship-ai-6prmjv3zxbvfs',
    [ValidatePattern('^/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[^/]+/providers/Microsoft.ManagedIdentity/userAssignedIdentities/[^/]+$')]
    [string] $IdentityResourceId
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$subscription = if ($PSBoundParameters.ContainsKey('SubscriptionId')) { $SubscriptionId.ToString() } else { $null }

function Invoke-Azure {
    param([string[]] $Arguments)
    $subscriptionArguments = if ($subscription) { @('--subscription', $subscription) } else { @() }
    $result = & az @Arguments @subscriptionArguments --only-show-errors --output json
    if ($LASTEXITCODE -ne 0) { throw 'Azure CLI failed. No further changes will run; any completed identity update is retained.' }
    if ($result) { return ($result | Out-String | ConvertFrom-Json -AsHashtable -Depth 100) }
}

function Confirm-Change {
    param([string] $Prompt)
    $answer = Read-Host "$Prompt Press Enter to apply [APPLY], or type CANCEL to stop"
    if ($answer -cne '' -and $answer -cne 'APPLY') { throw 'Identity configuration canceled.' }
}

Get-Command az -ErrorAction Stop | Out-Null
$account = Invoke-Azure @('account', 'show')
if ($account.state -ne 'Enabled' -or ($subscription -and $subscription -ne $account.id)) {
    throw 'The requested subscription is not enabled or could not be selected.'
}
$subscription = ([guid] $account.id).ToString()
$clusterId = "/subscriptions/$subscription/resourceGroups/$ResourceGroupName/providers/Microsoft.HorizonDb/clusters/$ClusterName"
$clusterUrl = "https://management.azure.com${clusterId}?api-version=2026-05-01-preview"
$cluster = Invoke-Azure @('rest', '--method', 'get', '--url', $clusterUrl)
$foundry = Invoke-Azure @('cognitiveservices', 'account', 'show', '--resource-group', $ResourceGroupName, '--name', $FoundryName)
if ($foundry.kind -notin @('AIServices', 'OpenAI')) { throw 'Target account does not support Azure OpenAI model access.' }
if ($cluster.properties['state'] -ne 'Succeeded' -and $cluster.properties['provisioningState'] -ne 'Succeeded') { throw 'Wait for the cluster state to become Succeeded, then retry.' }

$identity = $cluster['identity']
$assignedIdentities = @{}
if ($identity -and $identity['userAssignedIdentities']) {
    foreach ($assignedId in $identity.userAssignedIdentities.Keys) { $assignedIdentities[$assignedId] = @{} }
}
if ($identity -and $identity['type'] -notin @('None', 'UserAssigned')) {
    throw "Unexpected existing identity type '$($identity.type)'. No changes made; review it before updating."
}
if (-not $IdentityResourceId -and $assignedIdentities.Count -gt 1) {
    throw 'Multiple user-assigned identities are attached. Specify -IdentityResourceId; SQL identity selection must be verified separately.'
}
$managedIdentity = $null
if (-not $IdentityResourceId -and $assignedIdentities.Count -eq 1) {
    $IdentityResourceId = @($assignedIdentities.Keys)[0]
}
if ($IdentityResourceId) {
    $managedIdentity = Invoke-Azure @('identity', 'show', '--ids', $IdentityResourceId)
} else {
    $identityName = "$ClusterName-model-access"
    $identities = @(Invoke-Azure @('identity', 'list', '--resource-group', $ResourceGroupName))
    $managedIdentity = $identities | Where-Object { $_.name -eq $identityName } | Select-Object -First 1
    $IdentityResourceId = "/subscriptions/$subscription/resourceGroups/$ResourceGroupName/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$identityName"
}
if ($managedIdentity) { $IdentityResourceId = $managedIdentity.id }
$isAttached = $assignedIdentities.ContainsKey($IdentityResourceId)
Write-Host "Subscription: $($account.name) ($subscription)"
Write-Host "DB: $ClusterName; Foundry: $FoundryName; mode: $Mode"
Write-Host "User Assigned Identity: $IdentityResourceId; attached: $isAttached"
Write-Host 'Only a User Assigned Identity, its DB attachment and a Foundry-scoped Cognitive Services OpenAI User role assignment are in scope.'
Write-Host 'DB password, parameters, firewall, Foundry authentication and model deployments are not updated.'

if ($managedIdentity -and -not $managedIdentity['principalId']) { throw 'User Assigned Identity has no principal ID yet. Retry after provisioning completes.' }
if ($Mode -eq 'Check') {
    Write-Host $(if ($managedIdentity) { "Model-access principal: $($managedIdentity.principalId)" } else { 'User Assigned Identity must be created before RBAC what-if is possible.' })
    return
}

$template = Join-Path $PSScriptRoot 'foundry-model-access.bicep'
Invoke-Azure @('bicep', 'build', '--file', $template, '--stdout') | Out-Null
if (-not $managedIdentity) {
    if ($Mode -eq 'WhatIf') {
        Write-Host 'Plan: create a User Assigned Identity, PATCH only the DB identity attachment, then use the identity resource principal ID for RBAC.'
        Write-Warning 'No changes were made. ARM RBAC what-if cannot run until the User Assigned Identity exists. Use -Mode Deploy to approve creation first.'
        return
    }
    Confirm-Change "Create User Assigned Identity '$identityName'?"
    $managedIdentity = Invoke-Azure @('identity', 'create', '--resource-group', $ResourceGroupName, '--name', $identityName, '--location', $cluster.location)
    if (-not $managedIdentity -or -not $managedIdentity['principalId']) { throw 'User Assigned Identity principal ID is unavailable. Rerun after provisioning completes.' }
    $IdentityResourceId = $managedIdentity.id
}
if (-not $isAttached -and $Mode -eq 'WhatIf') {
    Write-Host 'Plan: PATCH only the DB identity attachment during Deploy. The following what-if covers RBAC only.'
}
if (-not $isAttached -and $Mode -eq 'Deploy') {
    $assignedIdentities[$IdentityResourceId] = @{}
    $newIdentity = @{ type = 'UserAssigned'; userAssignedIdentities = $assignedIdentities }
    Confirm-Change "Attach User Assigned Identity '$IdentityResourceId' to '$ClusterName'?"
    $bodyFile = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText($bodyFile, (@{ identity = $newIdentity } | ConvertTo-Json -Depth 10))
        Invoke-Azure @('rest', '--method', 'patch', '--url', $clusterUrl, '--body', "@$bodyFile") | Out-Null
    } finally {
        Remove-Item -LiteralPath $bodyFile -ErrorAction SilentlyContinue
    }
    Invoke-Azure @(
        'resource', 'wait', '--ids', $clusterId, '--api-version', '2026-05-01-preview',
        '--custom', "(properties.state=='Succeeded' || properties.provisioningState=='Succeeded') && contains(keys(identity.userAssignedIdentities || ``{}``), '$IdentityResourceId')",
        '--interval', '10', '--timeout', '600'
    ) | Out-Null
    $cluster = Invoke-Azure @('rest', '--method', 'get', '--url', $clusterUrl)
    if (-not $cluster['identity'] -or -not $cluster.identity['userAssignedIdentities'] -or -not $cluster.identity.userAssignedIdentities.ContainsKey($IdentityResourceId)) {
        throw 'User Assigned Identity attachment was not confirmed. No role assignment was attempted.'
    }
}

$principalId = ([guid] $managedIdentity.principalId).ToString()
$deploymentArguments = @(
    '--subscription', $subscription, '--resource-group', $ResourceGroupName,
    '--name', 'horizonship-db-model-access', '--mode', 'Incremental',
    '--template-file', $template, '--parameters', "foundryName=$FoundryName", "principalId=$principalId",
    '--only-show-errors'
)
Write-Host "Model-access principal: $principalId; client ID: $($managedIdentity.clientId)"
Write-Warning 'Identity attachment and RBAC do not verify SQL token acquisition. Validate an actual managed-identity embedding call separately, especially when multiple identities are attached.'
& az deployment group what-if @deploymentArguments
if ($LASTEXITCODE -ne 0) { throw 'RBAC what-if failed. No role assignment was deployed; any completed identity update is retained.' }
if ($Mode -eq 'Deploy') {
    Confirm-Change 'Review the RBAC-only what-if above.'
    & az deployment group create @deploymentArguments --query properties.outputs --output json
    if ($LASTEXITCODE -ne 0) { throw 'RBAC deployment failed. DB identity is retained; correct the error and rerun this script.' }
    Write-Host 'DB identity and model access configured. Allow RBAC propagation before running database setup. Local chat-user access is separate.'
}