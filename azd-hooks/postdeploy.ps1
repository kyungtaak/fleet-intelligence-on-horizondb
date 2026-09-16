#requires -Version 7.4

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-AzdValue {
    param(
        [Parameter(Mandatory)][string] $Name,
        [string] $Default = ''
    )

    $value = (& azd env get-value $Name 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($value)) {
        if (-not [string]::IsNullOrWhiteSpace($Default)) {
            return $Default
        }
        throw "azd did not publish $Name."
    }
    return $value
}

$frontendUri = (Get-AzdValue -Name 'SERVICE_FRONTEND_URI').TrimEnd('/')
$health = $null
$lastHealthError = ''
$requiredHealthProperties = @(
    'connected',
    'agent_framework',
    'diskann_spherical_quantization',
    'diskann_sq_bits',
    'diskann_sq_training_samples',
    'shipment_count',
    'azure_embedding_count'
)

for ($attempt = 1; $attempt -le 40; $attempt++) {
    try {
        $candidate = Invoke-RestMethod -Uri "$frontendUri/api/health" -TimeoutSec 30
        $propertyNames = @($candidate.PSObject.Properties.Name)
        $missingProperties = @($requiredHealthProperties | Where-Object { $_ -notin $propertyNames })
        if ($missingProperties.Count -gt 0) {
            throw "Health response is missing properties: $($missingProperties -join ', ')."
        }
        $health = $candidate
        break
    } catch {
        $lastHealthError = $_.Exception.Message
        if ($attempt -eq 40) {
            throw "The deployed application did not become ready within 10 minutes at $frontendUri/api/health. Last error: $lastHealthError"
        }
        Write-Host "Waiting for database setup and application startup ($attempt/40): $lastHealthError"
        Start-Sleep -Seconds 15
    }
}

if (-not $health.connected) {
    throw 'The deployed API is not connected to HorizonDB.'
}
if (-not $health.agent_framework) {
    throw 'The deployed Agent Framework health check failed.'
}
if (
    -not $health.diskann_spherical_quantization `
    -or $health.diskann_sq_bits -ne 4 `
    -or $health.diskann_sq_training_samples -ne 25000
) {
    throw 'The deployed SQ4 DiskANN index is not ready.'
}
if ($health.shipment_count -lt 1 -or $health.azure_embedding_count -ne $health.shipment_count) {
    throw 'Shipment embeddings are not ready.'
}

$runDatabaseSetup = (Get-AzdValue -Name 'RUN_DATABASE_SETUP' -Default 'false').ToLowerInvariant()
if ($runDatabaseSetup -eq 'true') {
    $subscriptionId = Get-AzdValue -Name 'AZURE_SUBSCRIPTION_ID'
    $resourceGroupName = Get-AzdValue -Name 'AZURE_RESOURCE_GROUP'
    $backendName = Get-AzdValue -Name 'SERVICE_BACKEND_NAME'
    & az containerapp update `
        --subscription $subscriptionId `
        --resource-group $resourceGroupName `
        --name $backendName `
        --set-env-vars 'RUN_DATABASE_SETUP=false' `
        --only-show-errors `
        --output none
    if ($LASTEXITCODE -ne 0) {
        throw 'The application is healthy, but RUN_DATABASE_SETUP could not be disabled.'
    }
    & azd env set RUN_DATABASE_SETUP false | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'The application is healthy, but RUN_DATABASE_SETUP could not be saved for the next deployment.'
    }
}

Write-Host 'HorizonShip deployment is ready.'
Write-Host "Frontend: $frontendUri"
Write-Host "Health: $frontendUri/api/health"