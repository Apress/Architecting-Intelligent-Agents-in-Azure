param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1"
)

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

if (-not $ResourceGroupName -or -not $AcrName -or -not $LogAnalyticsName -or -not $ContainerAppsEnvName) {
    Write-Error "Missing required variables in vars file."
    exit 1
}

Write-Host "Deleting Sprint 1 resources (RG kept): $ResourceGroupName"

az containerapp env delete `
    --name $ContainerAppsEnvName `
    --resource-group $ResourceGroupName `
    --yes `
    --only-show-errors 2>$null

az monitor log-analytics workspace delete `
    --workspace-name $LogAnalyticsName `
    --resource-group $ResourceGroupName `
    --yes `
    --only-show-errors 2>$null

az acr delete `
    --name $AcrName `
    --resource-group $ResourceGroupName `
    --yes `
    --only-show-errors 2>$null

Write-Host "Cleanup complete. Resource group retained."
