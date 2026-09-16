#requires -Version 7.4

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-AzdValue {
    param(
        [Parameter(Mandatory)]
        [string] $Name,
        [string] $Default = '',
        [switch] $Required
    )

    $value = (& azd env get-value $Name 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($value)) {
        $value = $Default
    }
    if ($Required -and [string]::IsNullOrWhiteSpace($value)) {
        throw "Set $Name with './azd-hooks/configure.ps1 ...' before running azd provision. azd up prompts for missing secrets in its preup hook."
    }
    return $value
}

function Invoke-AzureJson {
    param([string[]] $Arguments)

    $result = & az @Arguments --only-show-errors --output json
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI failed while running: az $($Arguments -join ' ')"
    }
    if ($result) {
        return ($result | Out-String | ConvertFrom-Json -Depth 100)
    }
}

Get-Command az -ErrorAction Stop | Out-Null
Get-Command azd -ErrorAction Stop | Out-Null

$subscriptionId = Get-AzdValue -Name 'AZURE_SUBSCRIPTION_ID' -Required
$location = (Get-AzdValue -Name 'AZURE_LOCATION' -Default 'westus3').ToLowerInvariant()
$mode = (Get-AzdValue -Name 'HORIZONDB_MODE' -Default 'existing').ToLowerInvariant()

if ($location -ne 'westus3') {
    throw 'This deployment currently supports AZURE_LOCATION=westus3 only.'
}
if ($mode -notin @('create', 'existing')) {
    throw 'HORIZONDB_MODE must be create or existing.'
}

foreach ($namespace in @(
    'Microsoft.App',
    'Microsoft.ContainerRegistry',
    'Microsoft.ManagedIdentity',
    'Microsoft.HorizonDB'
)) {
    $state = & az provider show `
        --subscription $subscriptionId `
        --namespace $namespace `
        --query registrationState `
        --output tsv `
        --only-show-errors
    if ($LASTEXITCODE -ne 0 -or $state -ne 'Registered') {
        throw "$namespace is not registered in subscription $subscriptionId."
    }
}

$administratorPassword = Get-AzdValue -Name 'AZURE_PG_PASSWORD' -Required
if (
    $administratorPassword.Length -lt 8 `
    -or $administratorPassword.Length -gt 128 `
    -or $administratorPassword -cnotmatch '[A-Z]' `
    -or $administratorPassword -cnotmatch '[a-z]' `
    -or $administratorPassword -notmatch '[0-9]' `
    -or $administratorPassword -notmatch '[^a-zA-Z0-9]'
) {
    throw 'AZURE_PG_PASSWORD must contain 8-128 characters with uppercase, lowercase, numbers and symbols.'
}

$openAiEndpoint = Get-AzdValue -Name 'AZURE_OPENAI_ENDPOINT' -Required
$endpointUri = $null
if (
    -not [Uri]::TryCreate($openAiEndpoint, [UriKind]::Absolute, [ref] $endpointUri) `
    -or $endpointUri.Scheme -ne 'https' `
    -or -not [string]::IsNullOrEmpty($endpointUri.UserInfo)
) {
    throw 'AZURE_OPENAI_ENDPOINT must be an HTTPS resource endpoint without credentials.'
}
Get-AzdValue -Name 'AZURE_OPENAI_KEY' -Required | Out-Null

if ($mode -eq 'existing') {
    $applicationResourceGroup = Get-AzdValue -Name 'AZURE_RESOURCE_GROUP' -Required
    $databaseResourceGroup = Get-AzdValue -Name 'HORIZONDB_RESOURCE_GROUP' -Required
    $clusterName = Get-AzdValue -Name 'HORIZONDB_CLUSTER_NAME' -Required
    if ($applicationResourceGroup -eq $databaseResourceGroup) {
        throw 'In existing mode, AZURE_RESOURCE_GROUP must be different from HORIZONDB_RESOURCE_GROUP so azd down cannot remove the existing database resource group.'
    }
    $resourceId = "/subscriptions/$subscriptionId/resourceGroups/$databaseResourceGroup/providers/Microsoft.HorizonDb/clusters/$clusterName"
    $cluster = Invoke-AzureJson @(
        'resource', 'show',
        '--subscription', $subscriptionId,
        '--ids', $resourceId,
        '--api-version', '2026-05-01-preview'
    )
    if ($cluster.properties.state -ne 'Succeeded') {
        throw "Existing HorizonDB cluster $clusterName is not ready. State: $($cluster.properties.state)"
    }
} else {
    $previousResourceGroup = Get-AzdValue -Name 'HORIZONDB_RESOURCE_GROUP'
    $previousClusterName = Get-AzdValue -Name 'HORIZONDB_CLUSTER_NAME'
    $createMode = 'Create'
    if (
        -not [string]::IsNullOrWhiteSpace($previousResourceGroup) `
        -and -not [string]::IsNullOrWhiteSpace($previousClusterName)
    ) {
        $resourceId = "/subscriptions/$subscriptionId/resourceGroups/$previousResourceGroup/providers/Microsoft.HorizonDb/clusters/$previousClusterName"
        & az resource show `
            --subscription $subscriptionId `
            --ids $resourceId `
            --api-version '2026-05-01-preview' `
            --only-show-errors `
            --output none 2>$null
        if ($LASTEXITCODE -eq 0) {
            $createMode = 'Update'
        }
    }
    & azd env set HORIZONDB_CREATE_MODE $createMode | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not set HORIZONDB_CREATE_MODE for this azd environment.'
    }
}

$allowAzureServices = (Get-AzdValue -Name 'ALLOW_AZURE_SERVICES_TO_HORIZONDB' -Default 'true').ToLowerInvariant()
if ($allowAzureServices -notin @('true', 'false')) {
    throw 'ALLOW_AZURE_SERVICES_TO_HORIZONDB must be true or false.'
}
if ($allowAzureServices -eq 'true') {
    Write-Warning 'HorizonDB will accept connections from Azure service public IP addresses for this demo environment.'
}

Write-Host "Preprovision passed: mode=$mode; location=$location; model deployments are not created."