param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Error "Azure CLI (az) not found. Install Azure CLI first."
    exit 1
}

try {
    az account show --only-show-errors | Out-Null
} catch {
    Write-Error "Azure CLI not logged in. Run: az login"
    exit 1
}

if (-not (Test-Path $VarsFile)) {
    Write-Error "Vars file not found: $VarsFile"
    exit 1
}

. $VarsFile

if (-not $ResourceGroupName -or -not $Location -or -not $KeyVaultName -or -not $StorageAccountName) {
    Write-Error "Missing required variables in vars file."
    exit 1
}

$rg = az group show --name $ResourceGroupName --only-show-errors 2>$null
if (-not $rg) {
    Write-Error "Resource group not found: $ResourceGroupName"
    exit 1
}

try {
    az storage account show `
        --name $StorageAccountName `
        --resource-group $ResourceGroupName `
        --only-show-errors 2>$null | Out-Null
    Write-Host "Storage account already exists."
} catch {
    Write-Host "Creating Storage account: $StorageAccountName"
    az storage account create `
        --name $StorageAccountName `
        --resource-group $ResourceGroupName `
        --location $Location `
        --sku Standard_LRS `
        --kind StorageV2 `
        --only-show-errors | Out-Null
}

try {
    az keyvault show `
        --name $KeyVaultName `
        --resource-group $ResourceGroupName `
        --only-show-errors 2>$null | Out-Null
    Write-Host "Key Vault already exists."
} catch {
    Write-Host "Creating Key Vault: $KeyVaultName"
    az keyvault create `
        --name $KeyVaultName `
        --resource-group $ResourceGroupName `
        --location $Location `
        --enable-rbac-authorization true `
        --only-show-errors | Out-Null
}

Write-Host "Sprint 2 identity/secrets foundation is ready."
