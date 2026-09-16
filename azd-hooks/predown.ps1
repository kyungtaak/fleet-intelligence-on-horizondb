#requires -Version 7.4

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-AzdValue {
    param([Parameter(Mandatory)][string] $Name)

    $value = (& azd env get-value $Name 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        return ''
    }
    return $value
}

$mode = (Get-AzdValue -Name 'HORIZONDB_MODE').ToLowerInvariant()
$firewallRuleId = Get-AzdValue -Name 'HORIZONDB_FIREWALL_RULE_ID'

if ($mode -eq 'existing' -and -not [string]::IsNullOrWhiteSpace($firewallRuleId)) {
    & az resource show `
        --ids $firewallRuleId `
        --api-version '2026-05-01-preview' `
        --only-show-errors `
        --output none 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'The temporary HorizonDB Azure-services firewall rule is already absent.'
        return
    }
    & az resource delete `
        --ids $firewallRuleId `
        --api-version '2026-05-01-preview' `
        --only-show-errors
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not remove the temporary HorizonDB Azure-services firewall rule.'
    }
    Write-Host 'Removed the temporary HorizonDB Azure-services firewall rule.'
}