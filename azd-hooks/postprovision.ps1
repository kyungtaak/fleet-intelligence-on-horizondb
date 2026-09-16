#requires -Version 7.4

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-AzdValue {
    param([Parameter(Mandatory)][string] $Name)

    $value = (& azd env get-value $Name 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($value)) {
        throw "azd did not publish $Name."
    }
    return $value
}

$mode = (Get-AzdValue -Name 'HORIZONDB_MODE').ToLowerInvariant()
if ($mode -ne 'create') {
    Write-Host 'Existing HorizonDB selected; parameter group attachment was not changed.'
    return
}

$subscriptionId = Get-AzdValue -Name 'AZURE_SUBSCRIPTION_ID'
$resourceGroupName = Get-AzdValue -Name 'HORIZONDB_RESOURCE_GROUP'
$clusterName = Get-AzdValue -Name 'HORIZONDB_CLUSTER_NAME'
$parameterGroupId = Get-AzdValue -Name 'HORIZONDB_PARAMETER_GROUP_ID'
$clusterUrl = "https://management.azure.com/subscriptions/$subscriptionId/resourceGroups/$resourceGroupName/providers/Microsoft.HorizonDb/clusters/$clusterName"
$body = @{
    properties = @{
        parameterGroup = @{
            id = $parameterGroupId
            applyImmediately = $true
        }
    }
} | ConvertTo-Json -Depth 10 -Compress

& az rest `
    --method patch `
    --url "${clusterUrl}?api-version=2026-05-01-preview" `
    --body $body `
    --only-show-errors `
    --output none
if ($LASTEXITCODE -ne 0) {
    throw 'The new HorizonDB cluster was created, but its parameter group could not be attached.'
}

$clusterId = "/subscriptions/$subscriptionId/resourceGroups/$resourceGroupName/providers/Microsoft.HorizonDb/clusters/$clusterName"
& az resource wait `
    --subscription $subscriptionId `
    --ids $clusterId `
    --api-version '2026-05-01-preview' `
    --custom "properties.parameterGroup.id == '$parameterGroupId' && properties.parameterGroup.status == 'InSync'" `
    --interval 15 `
    --timeout 900 `
    --only-show-errors
if ($LASTEXITCODE -ne 0) {
    throw 'HorizonDB did not report the requested parameter group as InSync within 15 minutes.'
}

Write-Host 'New HorizonDB parameter group is attached and InSync.'