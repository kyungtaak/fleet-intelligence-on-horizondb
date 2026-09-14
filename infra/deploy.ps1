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
    [ValidatePattern('^[a-zA-Z][a-zA-Z0-9]{0,62}$')]
    [string] $AdministratorLogin = 'horizonadmin',
    [string] $ClientIpAddress,
    [ValidateSet(2, 4, 8, 16)]
    [int] $VCores = 2,
    [ValidateRange(1, 3)]
    [int] $ReplicaCount = 1,
    [ValidateSet('BestEffort', 'Strict')]
    [string] $ZonePlacementPolicy = 'BestEffort',
    [switch] $UpdateExistingCluster
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

function Get-RegistrationStatus {
    foreach ($namespace in @('Microsoft.HorizonDB')) {
        $provider = Invoke-AzureJson @('provider', 'show', '--namespace', $namespace)
        [pscustomobject]@{ Kind = 'Provider'; Name = $namespace; State = $provider.registrationState }
    }
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
Write-Host "Mode: $Mode; region: $location; resource group: $ResourceGroupName"

if ($Mode -eq 'Register') {
    $approval = Read-Host 'Register the HorizonDB resource provider? Type REGISTER'
    if ($approval -cne 'REGISTER') { throw 'Registration canceled.' }
    $status = @(Get-RegistrationStatus)
    foreach ($providerStatus in $status) {
        if ($providerStatus.State -ne 'Registered') {
            Invoke-AzureJson @('provider', 'register', '--namespace', $providerStatus.Name, '--wait') | Out-Null
        }
    }
    $status = @(Get-RegistrationStatus)
    $status | Format-Table | Out-Host
    if (@($status | Where-Object State -ne 'Registered').Count -gt 0) {
        throw 'Registration is not complete. Rerun Register later.'
    }
    return
}

$status = @(Get-RegistrationStatus)
$status | Format-Table | Out-Host
$provider = Invoke-AzureJson @('provider', 'show', '--namespace', 'Microsoft.HorizonDB')
$clusterType = @($provider.resourceTypes | Where-Object resourceType -eq 'clusters')
if ($clusterType.Count -ne 1 -or 'West US 3' -notin $clusterType[0].locations -or
    '2026-05-01-preview' -notin $clusterType[0].apiVersions) {
    throw 'HorizonDB West US 3 or the required API version is unavailable.'
}
if (@($status | Where-Object State -ne 'Registered').Count -gt 0) {
    throw 'Registration is incomplete. Run with -Mode Register before WhatIf or Deploy.'
}
if ($Mode -eq 'Check') {
    Write-Host 'Preflight passed. Azure Policy, RBAC and live capacity still require deployment validation.'
    return
}

if ([string]::IsNullOrWhiteSpace($ClientIpAddress)) {
    Write-Host 'Detecting public IPv4 using https://api4.ipify.org ...'
    try {
        $ClientIpAddress = ([string](Invoke-RestMethod -Uri 'https://api4.ipify.org' -TimeoutSec 15 -ErrorAction Stop)).Trim()
    } catch {
        throw 'Public IPv4 detection failed. Retry with -ClientIpAddress set to your public database egress IPv4.'
    }
    Write-Warning 'An HTTP proxy or VPN may use a different egress IP from PostgreSQL. Override with -ClientIpAddress if needed.'
}
$address = $null
if ($ClientIpAddress -notmatch '^\d{1,3}(\.\d{1,3}){3}$' -or
    -not [System.Net.IPAddress]::TryParse($ClientIpAddress, [ref] $address) -or
    $address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'Provide -ClientIpAddress with one public IPv4 address, not CIDR or a range.'
}
$octets = $address.GetAddressBytes()
if ($octets[0] -in @(0, 10, 127) -or $octets[0] -ge 224 -or
    ($octets[0] -eq 172 -and $octets[1] -ge 16 -and $octets[1] -le 31) -or
    ($octets[0] -eq 192 -and $octets[1] -eq 168) -or
    ($octets[0] -eq 169 -and $octets[1] -eq 254)) {
    throw 'The database firewall requires your public egress IPv4 address.'
}
Write-Host "Database firewall IPv4: $($address.ToString())"
if ($ZonePlacementPolicy -eq 'Strict' -and $ReplicaCount -lt 2) {
    throw 'Strict zone placement requires at least two replicas.'
}
& az bicep version --only-show-errors | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Install Bicep with az bicep install first.' }

if ($Mode -eq 'Deploy') {
    Write-Host 'This creates or updates billable HorizonDB resources only. Foundry and model deployments are not changed.'
    Write-Host 'Database access is restricted to the supplied IPv4. Existing resources are not automatically deleted on failure.'
    $approval = Read-Host "Type the resource group name '$ResourceGroupName' to deploy"
    if ($approval -cne $ResourceGroupName) { throw 'Deployment canceled.' }
}

$settings = @{
    resourceGroupName = $ResourceGroupName
    location = $location
    namePrefix = $NamePrefix
    administratorLogin = $AdministratorLogin
    clientIpAddress = $address.ToString()
    clusterCreateMode = $(if ($UpdateExistingCluster) { 'Update' } else { 'Create' })
    vCores = $VCores
    replicaCount = $ReplicaCount
    zonePlacementPolicy = $ZonePlacementPolicy
}
$previousSettings = $env:HORIZONSHIP_DEPLOYMENT_SETTINGS
$previousPassword = $env:HORIZONSHIP_ADMIN_PASSWORD
$password = $null
$passwordPointer = [IntPtr]::Zero
try {
    $password = Read-Host 'HorizonDB administrator password (use the existing password when updating)' -AsSecureString
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
    $env:HORIZONSHIP_ADMIN_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    if ($env:HORIZONSHIP_ADMIN_PASSWORD.Length -lt 8 -or $env:HORIZONSHIP_ADMIN_PASSWORD.Length -gt 128 -or
        $env:HORIZONSHIP_ADMIN_PASSWORD -cnotmatch '[A-Z]' -or
        $env:HORIZONSHIP_ADMIN_PASSWORD -cnotmatch '[a-z]' -or
        $env:HORIZONSHIP_ADMIN_PASSWORD -notmatch '[0-9]' -or
        $env:HORIZONSHIP_ADMIN_PASSWORD -notmatch '[^a-zA-Z0-9]') {
        throw 'Use 8-128 characters including uppercase, lowercase, numbers and symbols.'
    }
    $env:HORIZONSHIP_DEPLOYMENT_SETTINGS = $settings | ConvertTo-Json -Compress
    $deploymentArguments = @(
        '--name', 'horizonship-db', '--location', $location,
        '--parameters', (Join-Path $PSScriptRoot 'main.bicepparam'),
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
    $env:HORIZONSHIP_DEPLOYMENT_SETTINGS = $previousSettings
    $env:HORIZONSHIP_ADMIN_PASSWORD = $previousPassword
    if ($passwordPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer) }
    if ($null -ne $password) { $password.Dispose() }
}