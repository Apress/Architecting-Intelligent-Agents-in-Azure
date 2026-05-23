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

if (-not $ResourceGroupName -or -not $Location -or -not $AcrName -or -not $LogAnalyticsName -or -not $ContainerAppsEnvName) {
    Write-Error "Missing required variables in vars file."
    exit 1
}

function Ensure-ProviderRegistered {
    param([string]$Namespace)
    $state = az provider show --namespace $Namespace --query registrationState -o tsv 2>$null
    if ($state -ne "Registered") {
        Write-Host "Registering provider: $Namespace"
        az provider register --namespace $Namespace --only-show-errors | Out-Null
        $tries = 0
        do {
            Start-Sleep -Seconds 5
            $state = az provider show --namespace $Namespace --query registrationState -o tsv 2>$null
            $tries++
        } while ($state -ne "Registered" -and $tries -lt 24)
        if ($state -ne "Registered") {
            Write-Error "Provider registration timed out: $Namespace"
            exit 1
        }
    }
}

Ensure-ProviderRegistered -Namespace "Microsoft.ContainerRegistry"
Ensure-ProviderRegistered -Namespace "Microsoft.App"
Ensure-ProviderRegistered -Namespace "Microsoft.OperationalInsights"

Write-Host "Using Resource Group: $ResourceGroupName"
Write-Host "Location: $Location"
Write-Host "ACR: $AcrName"
Write-Host "Log Analytics: $LogAnalyticsName"
Write-Host "Container Apps Env: $ContainerAppsEnvName"

$rgExists = az group exists --name $ResourceGroupName | ConvertFrom-Json
if (-not $rgExists) {
    Write-Host "Creating resource group..."
    az group create --name $ResourceGroupName --location $Location --only-show-errors | Out-Null
} else {
    Write-Host "Resource group already exists."
}

$acr = az acr show --name $AcrName --resource-group $ResourceGroupName --only-show-errors 2>$null
if (-not $acr) {
    Write-Host "Creating ACR..."
    az acr create `
        --name $AcrName `
        --resource-group $ResourceGroupName `
        --location $Location `
        --sku Basic `
        --admin-enabled false `
        --only-show-errors | Out-Null
} else {
    Write-Host "ACR already exists."
}

$law = az monitor log-analytics workspace show --name $LogAnalyticsName --resource-group $ResourceGroupName --only-show-errors 2>$null
if (-not $law) {
    Write-Host "Creating Log Analytics workspace..."
    az monitor log-analytics workspace create `
        --resource-group $ResourceGroupName `
        --workspace-name $LogAnalyticsName `
        --location $Location `
        --only-show-errors | Out-Null
} else {
    Write-Host "Log Analytics workspace already exists."
}

$lawCustomerId = az monitor log-analytics workspace show --resource-group $ResourceGroupName --workspace-name $LogAnalyticsName --query customerId -o tsv
$lawKey = az monitor log-analytics workspace get-shared-keys --resource-group $ResourceGroupName --workspace-name $LogAnalyticsName --query primarySharedKey -o tsv

$env = az containerapp env show --name $ContainerAppsEnvName --resource-group $ResourceGroupName --only-show-errors 2>$null
if (-not $env) {
    Write-Host "Creating Container Apps environment..."
    az containerapp env create `
        --name $ContainerAppsEnvName `
        --resource-group $ResourceGroupName `
        --location $Location `
        --logs-workspace-id $lawCustomerId `
        --logs-workspace-key $lawKey `
        --only-show-errors | Out-Null
} else {
    Write-Host "Container Apps environment already exists."
}

Write-Host "Sprint 1 infrastructure is ready."
