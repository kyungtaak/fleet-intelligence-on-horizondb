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

function Set-AzdSecretFromPrompt {
    param(
        [Parameter(Mandatory)][string] $Name,
        [Parameter(Mandatory)][string] $Prompt,
        [scriptblock] $Validate
    )

    if (-not [string]::IsNullOrWhiteSpace((Get-AzdValue -Name $Name))) {
        return
    }

    $secureValue = Read-Host $Prompt -AsSecureString
    $valuePointer = [IntPtr]::Zero
    try {
        $valuePointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
        $plainValue = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($valuePointer)
        if ($null -ne $Validate -and -not (& $Validate $plainValue)) {
            throw "The value entered for $Name does not meet the required format."
        }

        & azd env set $Name $plainValue | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not store $Name in the selected azd environment."
        }
    } finally {
        if ($valuePointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($valuePointer)
        }
        $secureValue.Dispose()
        Remove-Variable plainValue -ErrorAction SilentlyContinue
    }
}

Get-Command azd -ErrorAction Stop | Out-Null

Set-AzdSecretFromPrompt `
    -Name 'AZURE_PG_PASSWORD' `
    -Prompt 'HorizonDB administrator password' `
    -Validate {
        param([string] $Value)
        $Value.Length -ge 8 `
            -and $Value.Length -le 128 `
            -and $Value -cmatch '[A-Z]' `
            -and $Value -cmatch '[a-z]' `
            -and $Value -match '[0-9]' `
            -and $Value -match '[^a-zA-Z0-9]'
    }

Set-AzdSecretFromPrompt `
    -Name 'AZURE_OPENAI_KEY' `
    -Prompt 'Azure OpenAI subscription key'