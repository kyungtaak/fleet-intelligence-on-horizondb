#requires -Version 7.4

[CmdletBinding()]
param(
    [guid] $SubscriptionId,
    [ValidateSet('Check', 'Register', 'WhatIf', 'Deploy')]
    [string] $Mode = 'Check',
    [ValidatePattern('^[a-zA-Z0-9_-]{1,80}$')]
    [string] $ResourceGroupName = 'rg-horizonship-dev-wus3',
    [ValidatePattern('^[a-z][a-z0-9-]{1,14}[a-z0-9]$')]
    [string] $NamePrefix = 'horizonship',
    [ValidateSet('GlobalStandard', 'DataZoneStandard')]
    [string] $ModelSku = 'GlobalStandard',
    [ValidateRange(1, 1000000)]
    [int] $ChatCapacity = 10,
    [ValidateRange(1, 1000000)]
    [int] $EmbeddingCapacity = 10,
    [guid] $ModelCallerPrincipalId,
    [ValidateSet('User', 'ServicePrincipal', 'Group')]
    [string] $ModelCallerPrincipalType = 'User'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$location = 'westus3'
$subscription = if ($PSBoundParameters.ContainsKey('SubscriptionId')) { $SubscriptionId.ToString() } else { $null }

function Invoke-AzureJson {
    param([string[]] $Arguments)
    $subscriptionArguments = if ($subscription) { @('--subscription', $subscription) } else { @() }
    $result = & az @Arguments @subscriptionArguments --only-show-errors --output json
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI failed ($LASTEXITCODE). No further operations will run."
    }
    if ($result) { return ($result | Out-String | ConvertFrom-Json -Depth 100) }
}

function Get-AzureList {
    param([string] $Url)
    $items = [System.Collections.Generic.List[object]]::new()
    $visited = [System.Collections.Generic.HashSet[string]]::new()
    while ($Url) {
        if (-not $visited.Add($Url)) { throw 'Repeated ARM nextLink.' }
        $uri = [uri] $Url
        if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'management.azure.com') {
            throw 'Unexpected ARM nextLink host.'
        }
        $argumentUrl = if ($IsWindows) { '"' + $Url + '"' } else { $Url }
        $page = Invoke-AzureJson @('rest', '--method', 'get', '--url', $argumentUrl)
        foreach ($item in $page.value) { $items.Add($item) }
        $Url = if ($page.PSObject.Properties['nextLink']) { $page.nextLink } else { $null }
    }
    return $items.ToArray()
}

Get-Command az -ErrorAction Stop | Out-Null
try {
    $account = Invoke-AzureJson @('account', 'show')
} catch {
    throw 'Cannot read the signed-in Azure CLI account. Run az login yourself or verify -SubscriptionId, then retry.'
}
if (($subscription -and $account.id -ne $subscription) -or $account.state -ne 'Enabled') {
    throw 'The requested subscription is not enabled or could not be selected.'
}
$subscription = ([guid] $account.id).ToString()
Write-Host "Subscription: $($account.name) ($subscription)"
Write-Host "Mode: $Mode; region: $location; resource group: $ResourceGroupName; Foundry only"

if ($Mode -eq 'Register') {
    $approval = Read-Host 'Register the Cognitive Services resource provider? Type REGISTER'
    if ($approval -cne 'REGISTER') { throw 'Registration canceled.' }
    $provider = Invoke-AzureJson @('provider', 'show', '--namespace', 'Microsoft.CognitiveServices')
    if ($provider.registrationState -ne 'Registered') {
        Invoke-AzureJson @('provider', 'register', '--namespace', 'Microsoft.CognitiveServices', '--wait') | Out-Null
    }
    $provider = Invoke-AzureJson @('provider', 'show', '--namespace', 'Microsoft.CognitiveServices')
    if ($provider.registrationState -ne 'Registered') { throw 'Registration is not complete. Rerun Register later.' }
    Write-Host 'Microsoft.CognitiveServices: Registered'
    return
}

$provider = Invoke-AzureJson @('provider', 'show', '--namespace', 'Microsoft.CognitiveServices')
if ($provider.registrationState -ne 'Registered') {
    throw 'Registration is incomplete. Run with -Mode Register before WhatIf or Deploy.'
}
$skus = @(Invoke-AzureJson @('cognitiveservices', 'account', 'list-skus', '--kind', 'AIServices', '--location', $location))
$foundrySku = @($skus | Where-Object { $_.name -eq 'S0' -and @($_.restrictions).Count -eq 0 })
if ($foundrySku.Count -eq 0) { throw 'Foundry AIServices/S0 is unavailable or restricted.' }
$baseUrl = "https://management.azure.com/subscriptions/$subscription/providers/Microsoft.CognitiveServices/locations/$location"
$models = @(Get-AzureList "$baseUrl/models?api-version=2026-03-01")
$usages = @(Get-AzureList "$baseUrl/usages?api-version=2026-03-01")
$requirements = @(
    @{ Name = 'gpt-5.4'; Version = '2026-03-05'; Capacity = $ChatCapacity },
    @{ Name = 'text-embedding-3-small'; Version = '1'; Capacity = $EmbeddingCapacity }
)
foreach ($requirement in $requirements) {
    $available = @($models | Where-Object {
        $_.model.name -eq $requirement.Name -and $_.model.version -eq $requirement.Version -and
        $ModelSku -in $_.model.skus.name
    })
    if ($available.Count -eq 0) { throw "Model $($requirement.Name)/$($requirement.Version) with $ModelSku is unavailable." }
    $quotaName = "OpenAI.$ModelSku.$($requirement.Name)"
    $quota = @($usages | Where-Object { $_.name.value -eq $quotaName })
    if ($quota.Count -ne 1) { throw "Cannot determine quota for $quotaName." }
    $remaining = $quota[0].limit - $quota[0].currentValue
    Write-Host "$quotaName available: $remaining; requested: $($requirement.Capacity) (capacity units)"
    if ($remaining -lt $requirement.Capacity) { throw "Insufficient unallocated quota for $quotaName." }
}
if ($Mode -eq 'Check') {
    Write-Host 'Preflight passed. Azure Policy, RBAC and live capacity still require deployment validation.'
    return
}

& az bicep version --only-show-errors | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Install Bicep with az bicep install first.' }
if ($Mode -eq 'Deploy') {
    Write-Host 'This creates or updates billable Foundry resources and two model deployments. API key authentication stays disabled (Entra ID required).'
    Write-Host 'HorizonDB is not changed. Existing resources are not automatically deleted on failure.'
    $approval = Read-Host "Type the resource group name '$ResourceGroupName' to deploy"
    if ($approval -cne $ResourceGroupName) { throw 'Deployment canceled.' }
}
$principalId = if ($PSBoundParameters.ContainsKey('ModelCallerPrincipalId')) { $ModelCallerPrincipalId.ToString() } else { '' }
if ($principalId) {
    Write-Host "Assign Cognitive Services OpenAI User to $ModelCallerPrincipalType object ID: $principalId"
} else {
    Write-Warning 'No caller RBAC is assigned. Grant Cognitive Services OpenAI User on the Foundry resource to the backend identity before running the app.'
}
$settings = @{
    resourceGroupName = $ResourceGroupName
    location = $location
    namePrefix = $NamePrefix
    modelSku = $ModelSku
    chatCapacity = $ChatCapacity
    embeddingCapacity = $EmbeddingCapacity
    modelCallerPrincipalId = $principalId
    modelCallerPrincipalType = $ModelCallerPrincipalType
}
$previousSettings = $env:HORIZONSHIP_FOUNDRY_SETTINGS
try {
    $env:HORIZONSHIP_FOUNDRY_SETTINGS = $settings | ConvertTo-Json -Compress
    $deploymentArguments = @(
        '--name', 'horizonship-foundry', '--location', $location,
        '--parameters', (Join-Path $PSScriptRoot 'foundry.bicepparam'),
        '--subscription', $subscription, '--only-show-errors'
    )
    & az deployment sub what-if @deploymentArguments
    if ($LASTEXITCODE -ne 0) { throw 'What-if failed. No deployment was started.' }
    if ($Mode -eq 'Deploy') {
        $approval = Read-Host 'Review the what-if above. Press Enter to apply [DEPLOY], or type CANCEL to stop'
        if ($approval -ceq '') { $approval = 'DEPLOY' }
        if ($approval -cne 'DEPLOY') { throw 'Deployment canceled.' }
        & az deployment sub create @deploymentArguments --query properties.outputs --output json
        if ($LASTEXITCODE -ne 0) { throw 'Deployment failed. Inspect deployment operations; successful resources may still incur charges.' }
    }
} finally {
    $env:HORIZONSHIP_FOUNDRY_SETTINGS = $previousSettings
}