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

Write-Host "Scaling Container App(s) to allow scale-to-zero..."
foreach ($appName in @($ContainerAppName, $ContainerAppStageName)) {
    if (-not $appName) {
        continue
    }
    $exists = $null
    try {
        $exists = az containerapp show `
            --name $appName `
            --resource-group $ResourceGroupName `
            --query "name" -o tsv 2>$null
    } catch {
        $exists = $null
    }
    if (-not $exists) {
        Write-Warning "Container App not found: $appName"
        continue
    }
    Write-Host "Scaling Container App: $appName"
    az containerapp update `
        --name $appName `
        --resource-group $ResourceGroupName `
        --min-replicas 0 `
        --max-replicas 1 `
        --only-show-errors | Out-Null
    Write-Host "Scaled Container App: $appName"
}

Write-Host "Pause complete."
Write-Host "Note: AI Search, App Insights/Log Analytics, Key Vault, ACS, and storage still incur base costs unless deleted."
