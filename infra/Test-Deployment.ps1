#requires -Version 7.4

[CmdletBinding()]
param([switch] $CompileTemplates)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$deploymentScript = Join-Path $PSScriptRoot 'deploy.ps1'
$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile($deploymentScript, [ref] $tokens, [ref] $parseErrors) | Out-Null
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }

$testSubscription = '11111111-1111-1111-1111-111111111111'
$previousTestState = Get-Variable HorizonShipDeploymentTestState -Scope Global -ErrorAction SilentlyContinue
$global:HorizonShipDeploymentTestState = @{
    Calls = [System.Collections.Generic.List[string]]::new()
    Scenario = ''
    IpLookups = 0
    PasswordPrompts = 0
    RegisteredProviders = [System.Collections.Generic.HashSet[string]]::new()
    IdentityPatched = $false
    PatchedIdentity = $null
    BodyFile = $null
}

function az {
    $arguments = @($args)
    $command = $arguments -join ' '
    $global:HorizonShipDeploymentTestState.Calls.Add($command)
    Set-Variable LASTEXITCODE -Value 0 -Scope 1
    $registered = $global:HorizonShipDeploymentTestState.Scenario -notin @('unregistered', 'register')
    $state = if ($registered) { 'Registered' } else { 'NotRegistered' }
    $payload = switch -Regex ($command) {
        '^identity (list|show|create)' {
            $managedIdentity = @{
                id = "/subscriptions/$testSubscription/resourceGroups/rg-horizonship-dev-wus3/providers/Microsoft.ManagedIdentity/userAssignedIdentities/horizonship-db-6prmjv3zxbvfs-model-access"
                name = 'horizonship-db-6prmjv3zxbvfs-model-access'
                principalId = '22222222-2222-2222-2222-222222222222'
                clientId = '33333333-3333-3333-3333-333333333333'
            }
            if ($command -match '^identity show') { $managedIdentity.id = $arguments[[array]::IndexOf($arguments, '--ids') + 1] }
            if ($command -match '^identity create' -and $global:HorizonShipDeploymentTestState.Scenario -eq 'identity-create-fails') { Set-Variable LASTEXITCODE -Value 1 -Scope 1 }
            if ($command -match '^identity list') {
                if ($global:HorizonShipDeploymentTestState.Scenario -eq 'identity-unattached') { ,@($managedIdentity) } else { ,@() }
            } else { $managedIdentity }
            break
        }
        '^rest --method get .*HorizonDb/clusters/' {
            $identity = $null
            if ($global:HorizonShipDeploymentTestState.IdentityPatched) {
                $identity = $global:HorizonShipDeploymentTestState.PatchedIdentity
            } elseif ($global:HorizonShipDeploymentTestState.Scenario -in @('identity-existing', 'identity-user-assigned', 'identity-multiple')) {
                $identity = @{ type = 'UserAssigned'; userAssignedIdentities = @{ "/subscriptions/$testSubscription/resourceGroups/rg-horizonship-dev-wus3/providers/Microsoft.ManagedIdentity/userAssignedIdentities/existing" = @{ clientId = 'keep' } } }
                if ($global:HorizonShipDeploymentTestState.Scenario -in @('identity-user-assigned', 'identity-multiple')) {
                    $identity.userAssignedIdentities["/subscriptions/$testSubscription/resourceGroups/rg-horizonship-dev-wus3/providers/Microsoft.ManagedIdentity/userAssignedIdentities/other"] = @{}
                }
            }
            @{ identity = $identity; location = 'westus3'; properties = @{ state = 'Succeeded' } }
            break
        }
        '^rest --method patch ' {
            $bodyArgument = $arguments[[array]::IndexOf($arguments, '--body') + 1]
            $global:HorizonShipDeploymentTestState.BodyFile = $bodyArgument.Substring(1)
            $body = Get-Content -Raw $global:HorizonShipDeploymentTestState.BodyFile | ConvertFrom-Json -AsHashtable
            if ($body.Count -ne 1 -or -not $body.ContainsKey('identity')) { throw 'PATCH must only contain identity.' }
            if ($body.identity.type -ne 'UserAssigned') { throw 'CannotSetResourceIdentity: SystemAssigned is not supported.' }
            if ($global:HorizonShipDeploymentTestState.Scenario -eq 'identity-user-assigned' -and $body.identity.userAssignedIdentities.Count -ne 3) { throw 'Existing user identities were removed.' }
            foreach ($entry in $body.identity.userAssignedIdentities.Values) {
                if ($entry.Count) { throw 'Do not send read-only identity properties.' }
            }
            if ($global:HorizonShipDeploymentTestState.Scenario -eq 'identity-patch-fails') { Set-Variable LASTEXITCODE -Value 1 -Scope 1 }
            $global:HorizonShipDeploymentTestState.IdentityPatched = $true
            $global:HorizonShipDeploymentTestState.PatchedIdentity = $body.identity
            @{}
            break
        }
        '^cognitiveservices account show ' { @{ kind = 'AIServices' }; break }
        '^bicep build ' { @{}; break }
        '^resource wait ' {
            if ($command -match 'identity.principalId' -or $command -notmatch 'userAssignedIdentities') { throw 'Wait must check the UAMI attachment, not a system principal.' }
            if ($global:HorizonShipDeploymentTestState.Scenario -eq 'identity-wait-fails') { Set-Variable LASTEXITCODE -Value 1 -Scope 1 }
            @{}
            break
        }
        '^deployment group (what-if|create) ' {
            if ($command -notmatch 'foundry-model-access.bicep' -or $command -notmatch 'principalId=22222222-2222-2222-2222-222222222222' -or $command -notmatch '--mode Incremental') { throw 'Unexpected RBAC deployment target.' }
            if ($command -match 'what-if' -and $global:HorizonShipDeploymentTestState.Scenario -eq 'identity-whatif-fails') { Set-Variable LASTEXITCODE -Value 1 -Scope 1 }
            @{}
            break
        }
        '^account show' {
            if ($global:HorizonShipDeploymentTestState.Scenario -eq 'not-signed-in') {
                Set-Variable LASTEXITCODE -Value 1 -Scope 1
                break
            }
            @{ id = $testSubscription; name = 'Local test'; state = 'Enabled' }
            break
        }
        '^provider show' {
            $namespace = $arguments[[array]::IndexOf($arguments, '--namespace') + 1]
            @{
                registrationState = $(if ($global:HorizonShipDeploymentTestState.RegisteredProviders.Contains($namespace)) { 'Registered' } else { $state })
                resourceTypes = @(@{ resourceType = 'clusters'; locations = @('West US 3'); apiVersions = @('2026-05-01-preview') })
            }
            break
        }
        '^feature show' {
            @{ properties = @{ state = 'Pending' } }
            break
        }
        '^feature register' { throw 'Preview features must not be registered implicitly.' }
        '^provider register' {
            $namespace = $arguments[[array]::IndexOf($arguments, '--namespace') + 1]
            $global:HorizonShipDeploymentTestState.RegisteredProviders.Add($namespace) | Out-Null
            @{}
            break
        }
        '^cognitiveservices account list-skus' {
            @(@{ name = 'S0'; restrictions = @() })
            break
        }
        '^rest .*models' {
            if ($command -notmatch 'skiptoken') {
                @{
                    value = @()
                    nextLink = 'https://management.azure.com/test/models?api-version=2026-03-01&$skiptoken=next'
                }
            } else {
                $modelValues = if ($global:HorizonShipDeploymentTestState.Scenario -eq 'missing-model') { @() } else {
                    @(
                        @{ model = @{ name = 'gpt-5.4'; version = '2026-03-05'; skus = @(@{ name = 'GlobalStandard' }) } },
                        @{ model = @{ name = 'text-embedding-3-small'; version = '1'; skus = @(@{ name = 'GlobalStandard' }) } }
                    )
                }
                @{ value = @($modelValues) }
            }
            break
        }
        '^rest .*usages' {
            $quotaLimit = if ($global:HorizonShipDeploymentTestState.Scenario -eq 'no-quota') { 0 } else { 1000 }
            @{
                value = @(
                    @{ name = @{ value = 'OpenAI.GlobalStandard.gpt-5.4' }; limit = $quotaLimit; currentValue = 0 },
                    @{ name = @{ value = 'OpenAI.GlobalStandard.text-embedding-3-small' }; limit = 3000; currentValue = 0 }
                )
            }
            break
        }
        '^bicep version' { @{}; break }
        '^deployment sub what-if' {
            if ($global:HorizonShipDeploymentTestState.Scenario -eq 'whatif-fails') { Set-Variable LASTEXITCODE -Value 1 -Scope 1 }
            if ($command -match 'foundry.bicepparam') {
                $settings = $env:HORIZONSHIP_FOUNDRY_SETTINGS | ConvertFrom-Json
                if ($settings.location -ne 'westus3' -or $settings.PSObject.Properties['clientIpAddress'] -or
                    $settings.PSObject.Properties['administratorLogin'] -or $command -notmatch '--name horizonship-foundry') {
                    throw 'Foundry deployment must not include database settings.'
                }
                @{}
                break
            }
            if (-not $env:HORIZONSHIP_ADMIN_PASSWORD) { throw 'Password was not supplied to Bicep.' }
            $settings = $env:HORIZONSHIP_DEPLOYMENT_SETTINGS | ConvertFrom-Json
            if ($settings.location -ne 'westus3' -or $settings.clientIpAddress -ne '8.8.8.8') {
                throw 'Unexpected deployment settings.'
            }
            @{}
            break
        }
        '^deployment sub create' { @{}; break }
        default { throw "Unexpected mocked command: $command" }
    }
    ConvertTo-Json -InputObject $payload -Depth 12 -Compress
}

function Invoke-RestMethod {
    param([string] $Uri, [int] $TimeoutSec, [string] $ErrorAction)
    if ($Uri -ne 'https://api4.ipify.org' -or $TimeoutSec -ne 15) { throw 'Unexpected IP lookup.' }
    $global:HorizonShipDeploymentTestState.IpLookups++
    switch ($global:HorizonShipDeploymentTestState.Scenario) {
        'ip-fails' { throw 'Simulated network failure' }
        'ip-invalid' { return '<html>Proxy error</html>' }
        'ip-private' { return '10.0.0.1' }
        default { return "8.8.8.8`n" }
    }
}

function Read-Host {
    param([string] $Prompt, [switch] $AsSecureString)
    if ($AsSecureString) {
        $global:HorizonShipDeploymentTestState.PasswordPrompts++
        return (ConvertTo-SecureString ('Local-test-' + [guid]::NewGuid() + '!9aA') -AsPlainText -Force)
    }
    if ($Prompt -match 'User Assigned Identity|RBAC-only') {
        if ($global:HorizonShipDeploymentTestState.Scenario -eq 'identity-cancel' -or
            ($global:HorizonShipDeploymentTestState.Scenario -eq 'identity-rbac-cancel' -and $Prompt -match 'RBAC-only')) { return 'CANCEL' }
        return ''
    }
    if ($Prompt -match 'REGISTER') { return 'REGISTER' }
    if ($Prompt -match '^Review the what-if') {
        if ($global:HorizonShipDeploymentTestState.Scenario -eq 'cancel') { return 'CANCEL' }
        if ($global:HorizonShipDeploymentTestState.Scenario -eq 'deploy-enter') { return '' }
        return 'DEPLOY'
    }
    return 'rg-horizonship-dev-wus3'
}

function Test-Scenario {
    param([string] $Name, [string] $Mode, [string] $ExpectedError = '', [string] $IpAddress = '8.8.8.8', [switch] $UseCurrentSubscription, [switch] $Foundry)
    $global:HorizonShipDeploymentTestState.Scenario = $Name
    $global:HorizonShipDeploymentTestState.Calls.Clear()
    $global:HorizonShipDeploymentTestState.RegisteredProviders.Clear()
    $global:HorizonShipDeploymentTestState.IpLookups = 0
    $global:HorizonShipDeploymentTestState.PasswordPrompts = 0
    $oldSettings = $env:HORIZONSHIP_DEPLOYMENT_SETTINGS
    $oldFoundrySettings = $env:HORIZONSHIP_FOUNDRY_SETTINGS
    $oldPassword = $env:HORIZONSHIP_ADMIN_PASSWORD
    $failure = $null
    try {
        $invokeParameters = @{ Mode = $Mode }
        $script = $deploymentScript
        if ($Foundry) { $script = Join-Path $PSScriptRoot 'deploy-foundry.ps1' }
        else { $invokeParameters.ClientIpAddress = $IpAddress }
        if (-not $UseCurrentSubscription) { $invokeParameters.SubscriptionId = $testSubscription }
        & $script @invokeParameters 6>$null | Out-Null
    } catch { $failure = $_.Exception.Message }
    if ($ExpectedError) {
        if (-not $failure -or $failure -notlike "*$ExpectedError*") { throw "$Name expected '$ExpectedError', got '$failure'." }
    } elseif ($failure) { throw "$Name failed: $failure" }
    if ($env:HORIZONSHIP_DEPLOYMENT_SETTINGS -cne $oldSettings -or $env:HORIZONSHIP_ADMIN_PASSWORD -cne $oldPassword -or
        $env:HORIZONSHIP_FOUNDRY_SETTINGS -cne $oldFoundrySettings) {
        throw "$Name did not restore environment variables."
    }
    $writes = @($global:HorizonShipDeploymentTestState.Calls | Where-Object { $_ -match '^(feature register|provider register|deployment sub create)' })
    if ($Name -in @('deploy', 'deploy-enter')) {
        if (@($writes | Where-Object { $_ -match '^deployment sub create' }).Count -ne 1) { throw 'Expected exactly one deployment.' }
        if (@($writes | Where-Object { $_ -notmatch '^deployment sub create' }).Count) { throw 'Deploy must not register providers implicitly.' }
    } elseif ($Name -eq 'register') {
        if ($writes.Count -ne 1 -or @($writes | Where-Object { $_ -notmatch '^provider register' }).Count) { throw 'Only the required provider should be registered.' }
    } elseif ($writes.Count) { throw "$Name unexpectedly performed writes: $writes" }
    if (@($global:HorizonShipDeploymentTestState.Calls | Where-Object { $_ -match '^feature ' }).Count) {
        throw "$Name must not depend on unverified preview feature requirements."
    }
    if ($Foundry -and $Mode -ne 'Register' -and $Name -notin @('not-signed-in', 'unregistered') -and @($global:HorizonShipDeploymentTestState.Calls | Where-Object { $_ -match 'skiptoken' }).Count -ne 1) {
        throw "$Name did not follow model pagination."
    }
    $calls = $global:HorizonShipDeploymentTestState.Calls
    if ($Foundry) {
        if ($global:HorizonShipDeploymentTestState.PasswordPrompts -or
            @($calls | Where-Object { $_ -match 'HorizonDB|ManagedIdentity|main.bicepparam|listKeys' }).Count) {
            throw 'Foundry script must not access HorizonDB or retrieve keys.'
        }
    } elseif (@($calls | Where-Object { $_ -match 'CognitiveServices|ManagedIdentity|models\?|usages\?|foundry.bicepparam' }).Count) {
        throw 'Database deployment must be independent of Foundry and model quota.'
    }
    $expectedLookups = if ($Name -in @('auto-ip', 'ip-fails', 'ip-invalid', 'ip-private')) { 1 } else { 0 }
    if ($global:HorizonShipDeploymentTestState.IpLookups -ne $expectedLookups) { throw "$Name performed unexpected IP lookups." }
    if ($UseCurrentSubscription) {
        if ($global:HorizonShipDeploymentTestState.Calls[0] -match '--subscription') { throw 'Current account lookup should not require a subscription.' }
        foreach ($call in $global:HorizonShipDeploymentTestState.Calls | Select-Object -Skip 1) {
            if ($call -notmatch '^bicep ' -and $call -notmatch "--subscription $testSubscription") { throw 'Resolved subscription was not pinned.' }
        }
    }
    Write-Output "PASS $Name (Foundry=$Foundry)"
}

function Test-IdentityScenario {
    param([string] $Name, [string] $Mode, [int] $ExpectedPatches, [int] $ExpectedDeployments, [string] $ExpectedError = '', [int] $ExpectedCreations = 0)
    $global:HorizonShipDeploymentTestState.Scenario = $Name
    $global:HorizonShipDeploymentTestState.Calls.Clear()
    $global:HorizonShipDeploymentTestState.IdentityPatched = $false
    $global:HorizonShipDeploymentTestState.PatchedIdentity = $null
    $global:HorizonShipDeploymentTestState.BodyFile = $null
    $failure = $null
    try {
        $parameters = @{ Mode = $Mode }
        if ($Name -eq 'identity-user-assigned') {
            $parameters.IdentityResourceId = "/subscriptions/$testSubscription/resourceGroups/rg-horizonship-dev-wus3/providers/Microsoft.ManagedIdentity/userAssignedIdentities/selected"
        }
        & (Join-Path $PSScriptRoot 'configure-db-identity.ps1') @parameters 6>$null | Out-Null
    } catch { $failure = $_.Exception.Message }
    if ($ExpectedError) {
        if (-not $failure -or $failure -notlike "*$ExpectedError*") { throw "$Name expected '$ExpectedError', got '$failure'." }
    } elseif ($failure) { throw "$Name failed: $failure" }
    $calls = $global:HorizonShipDeploymentTestState.Calls
    if (@($calls | Where-Object { $_ -match '^identity create ' }).Count -ne $ExpectedCreations) { throw "$Name unexpected identity creations." }
    if ($Name -in @('identity-create-fails', 'identity-patch-fails', 'identity-wait-fails') -and @($calls | Where-Object { $_ -match '^deployment group' }).Count) { throw "$Name must stop before RBAC." }
    if (@($calls | Where-Object { $_ -match '^rest --method patch ' }).Count -ne $ExpectedPatches) { throw "$Name unexpected PATCH count." }
    if (@($calls | Where-Object { $_ -match '^deployment group create ' }).Count -ne $ExpectedDeployments) { throw "$Name unexpected RBAC writes." }
    if (@($calls | Where-Object { $_ -match 'deployment sub|listKeys|administratorLoginPassword|ipify' }).Count) { throw "$Name touched unrelated settings." }
    if ($global:HorizonShipDeploymentTestState.BodyFile -and (Test-Path $global:HorizonShipDeploymentTestState.BodyFile)) { throw "$Name leaked its temporary request file." }
    foreach ($call in $calls | Select-Object -Skip 1) {
        if ($call -notmatch "--subscription $testSubscription") { throw "$Name did not pin the subscription." }
    }
    Write-Output "PASS $Name/$Mode"
}

function Test-CompiledTemplates {
    $azureCli = (Get-Command az -CommandType Application | Select-Object -First 1).Source
    $oldSettings = $env:HORIZONSHIP_DEPLOYMENT_SETTINGS
    $oldFoundrySettings = $env:HORIZONSHIP_FOUNDRY_SETTINGS
    $oldPassword = $env:HORIZONSHIP_ADMIN_PASSWORD
    try {
        $env:HORIZONSHIP_ADMIN_PASSWORD = 'Not-A-Real-Password-9aA!'
        $env:HORIZONSHIP_DEPLOYMENT_SETTINGS = @{
            resourceGroupName = 'rg-horizonship-test'
            location = 'westus3'
            namePrefix = 'horizonship'
            administratorLogin = 'horizonadmin'
            clientIpAddress = '8.8.8.8'
            clusterCreateMode = 'Create'
            vCores = 2
            replicaCount = 1
            zonePlacementPolicy = 'BestEffort'
        } | ConvertTo-Json -Compress
        $env:HORIZONSHIP_FOUNDRY_SETTINGS = @{
            resourceGroupName = 'rg-horizonship-test'
            location = 'westus3'
            namePrefix = 'horizonship'
            modelSku = 'GlobalStandard'
            chatCapacity = 10
            embeddingCapacity = 10
            modelCallerPrincipalId = $testSubscription
            modelCallerPrincipalType = 'User'
        } | ConvertTo-Json -Compress
        foreach ($file in @('main.bicepparam', 'foundry.bicepparam')) {
            $output = & $azureCli bicep build-params --file (Join-Path $PSScriptRoot $file) --stdout --only-show-errors
            if ($LASTEXITCODE -ne 0) { throw "Offline Bicep compilation failed: $file" }
            $compiled = $output | Out-String | ConvertFrom-Json
            $template = $compiled.templateJson | ConvertFrom-Json -AsHashtable
            $parameters = $compiled.parametersJson | ConvertFrom-Json -AsHashtable
            $module = @($template.resources.Values | Where-Object type -eq 'Microsoft.Resources/deployments')[0]
            if ($module.properties.mode -ne 'Incremental') { throw 'Service deployments must use Incremental mode.' }
            $resources = $module.properties.template.resources
            if ($resources -is [System.Collections.IDictionary]) { $resources = @($resources.Values) }
            if ($file -eq 'main.bicepparam') {
                if (@($resources | Where-Object type -Match 'CognitiveServices|ManagedIdentity|roleAssignments').Count) {
                    throw 'Database template contains model-service resources.'
                }
                if (@($resources | Where-Object type -eq 'Microsoft.HorizonDb/clusters').Count -ne 1) {
                    throw 'Expected one HorizonDB cluster.'
                }
                if ($parameters.parameters.administratorPassword.value -ne $env:HORIZONSHIP_ADMIN_PASSWORD) {
                    throw 'Secure database password parameter was not passed correctly.'
                }
            } else {
                if (@($resources | Where-Object type -Match 'HorizonDb|ManagedIdentity').Count -or
                    $parameters.parameters.ContainsKey('administratorPassword')) { throw 'Foundry template depends on database resources.' }
                $account = @($resources | Where-Object type -eq 'Microsoft.CognitiveServices/accounts')[0]
                if ($account.properties.disableLocalAuth -ne $true) { throw 'Foundry must disable API key authentication.' }
                if (@($resources | Where-Object type -eq 'Microsoft.CognitiveServices/accounts/deployments').Count -ne 2) {
                    throw 'Expected two model deployments.'
                }
                if (@($resources | Where-Object type -eq 'Microsoft.Authorization/roleAssignments').Count -ne 1) {
                    throw 'Expected optional backend caller RBAC.'
                }
            }
            Write-Output "PASS offline compilation and resource isolation: $file"
        }
    } finally {
        $env:HORIZONSHIP_DEPLOYMENT_SETTINGS = $oldSettings
        $env:HORIZONSHIP_FOUNDRY_SETTINGS = $oldFoundrySettings
        $env:HORIZONSHIP_ADMIN_PASSWORD = $oldPassword
    }
}

try {
    Test-Scenario 'check' 'Check'
    Test-Scenario 'current-subscription' 'Check' -IpAddress '' -UseCurrentSubscription
    Test-Scenario 'not-signed-in' 'Check' 'Cannot read the signed-in' -UseCurrentSubscription
    Test-Scenario 'auto-ip' 'WhatIf' -IpAddress '' -UseCurrentSubscription
    Test-Scenario 'ip-fails' 'WhatIf' 'Public IPv4 detection failed' -IpAddress ''
    Test-Scenario 'ip-invalid' 'WhatIf' 'Provide -ClientIpAddress' -IpAddress ''
    Test-Scenario 'ip-private' 'WhatIf' 'public egress IPv4' -IpAddress ''
    Test-Scenario 'unregistered' 'Check' 'Registration is incomplete'
    Test-Scenario 'register' 'Register'
    Test-Scenario 'already-registered' 'Register'
    Test-Scenario 'pending-feature' 'WhatIf'
    Test-Scenario 'missing-model' 'Check'
    Test-Scenario 'no-quota' 'Check'
    Test-Scenario 'bad-ip' 'WhatIf' 'public egress IPv4' '0.0.0.0'
    Test-Scenario 'whatif' 'WhatIf'
    Test-Scenario 'whatif-fails' 'Deploy' 'What-if failed'
    Test-Scenario 'cancel' 'Deploy' 'Deployment canceled'
    Test-Scenario 'deploy' 'Deploy'
    Test-Scenario 'deploy-enter' 'Deploy'
    Test-Scenario 'check' 'Check' -Foundry
    Test-Scenario 'current-subscription' 'Check' -UseCurrentSubscription -Foundry
    Test-Scenario 'not-signed-in' 'Check' 'Cannot read the signed-in' -Foundry
    Test-Scenario 'unregistered' 'Check' 'Registration is incomplete' -Foundry
    Test-Scenario 'register' 'Register' -Foundry
    Test-Scenario 'already-registered' 'Register' -Foundry
    Test-Scenario 'missing-model' 'Check' 'is unavailable' -Foundry
    Test-Scenario 'no-quota' 'Deploy' 'Insufficient unallocated quota' -Foundry
    Test-Scenario 'whatif' 'WhatIf' -Foundry
    Test-Scenario 'whatif-fails' 'Deploy' 'What-if failed' -Foundry
    Test-Scenario 'cancel' 'Deploy' 'Deployment canceled' -Foundry
    Test-Scenario 'deploy' 'Deploy' -Foundry
    Test-Scenario 'deploy-enter' 'Deploy' -Foundry
    Test-IdentityScenario 'identity-check' 'Check' 0 0
    Test-IdentityScenario 'identity-plan' 'WhatIf' 0 0
    Test-IdentityScenario 'identity-new' 'Deploy' 1 1 -ExpectedCreations 1
    Test-IdentityScenario 'identity-existing' 'Deploy' 0 1
    Test-IdentityScenario 'identity-existing' 'WhatIf' 0 0
    Test-IdentityScenario 'identity-user-assigned' 'Deploy' 1 1
    Test-IdentityScenario 'identity-unattached' 'Deploy' 1 1
    Test-IdentityScenario 'identity-unattached' 'WhatIf' 0 0
    Test-IdentityScenario 'identity-multiple' 'Deploy' 0 0 'Multiple user-assigned identities'
    Test-IdentityScenario 'identity-create-fails' 'Deploy' 0 0 'Azure CLI failed' 1
    Test-IdentityScenario 'identity-cancel' 'Deploy' 0 0 'canceled'
    Test-IdentityScenario 'identity-rbac-cancel' 'Deploy' 1 0 'canceled' 1
    Test-IdentityScenario 'identity-patch-fails' 'Deploy' 1 0 'Azure CLI failed' 1
    Test-IdentityScenario 'identity-wait-fails' 'Deploy' 1 0 'Azure CLI failed' 1
    Test-IdentityScenario 'identity-whatif-fails' 'Deploy' 1 0 'RBAC what-if failed' 1
    if ($CompileTemplates) { Test-CompiledTemplates }
    Write-Output 'All deployment tests passed. No Azure resource operations were executed.'
} finally {
    if ($null -ne $previousTestState) {
        $global:HorizonShipDeploymentTestState = $previousTestState.Value
    } else {
        Remove-Variable HorizonShipDeploymentTestState -Scope Global
    }
}