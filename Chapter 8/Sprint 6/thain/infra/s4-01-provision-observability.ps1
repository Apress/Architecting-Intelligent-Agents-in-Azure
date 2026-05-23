param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$EnvFile = ".\\.env.dev",
    [switch]$IncludeStage = $true
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

if (-not $ResourceGroupName -or -not $Location -or -not $LogAnalyticsName -or -not $AppInsightsName) {
    Write-Error "Missing required variables in vars file."
    exit 1
}

function Set-EnvVarInFile {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )
    if (-not (Test-Path $Path)) {
        Write-Error "Env file not found: $Path"
        exit 1
    }
    $content = Get-Content $Path
    $escaped = [regex]::Escape($Name)
    $updated = $false
    $content = $content | ForEach-Object {
        if ($_ -match "^\s*$escaped=") {
            $updated = $true
            return "$Name=$Value"
        }
        $_
    }
    if (-not $updated) {
        $content += "$Name=$Value"
    }
    $content | Set-Content $Path
}

Write-Host "Ensuring Application Insights exists..."
$prevErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$null = az monitor app-insights component show `
    --app $AppInsightsName `
    --resource-group $ResourceGroupName `
    --only-show-errors 2>$null
$aiExists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevErrorAction

if (-not $aiExists) {
    $lawId = az monitor log-analytics workspace show `
        --resource-group $ResourceGroupName `
        --workspace-name $LogAnalyticsName `
        --query id -o tsv
    if (-not $lawId) {
        Write-Error "Failed to resolve Log Analytics workspace id."
        exit 1
    }
    az monitor app-insights component create `
        --app $AppInsightsName `
        --resource-group $ResourceGroupName `
        --location $Location `
        --workspace $lawId `
        --application-type web `
        --only-show-errors | Out-Null
}

$connectionString = az monitor app-insights component show `
    --app $AppInsightsName `
    --resource-group $ResourceGroupName `
    --query connectionString -o tsv
if (-not $connectionString) {
    Write-Error "Failed to resolve App Insights connection string."
    exit 1
}

$serviceName = $ContainerAppName
if (-not $serviceName) {
    $serviceName = "thain"
}

Write-Host "Updating $EnvFile with App Insights config..."
Set-EnvVarInFile -Path $EnvFile -Name "APPINSIGHTS_CONNECTION_STRING" -Value $connectionString
Set-EnvVarInFile -Path $EnvFile -Name "APPINSIGHTS_SERVICE_NAME" -Value $serviceName

if ($ContainerAppName) {
    Write-Host "Updating Container App env vars for App Insights: $ContainerAppName"
    az containerapp update `
        --name $ContainerAppName `
        --resource-group $ResourceGroupName `
        --set-env-vars `
            APPINSIGHTS_CONNECTION_STRING=$connectionString `
            APPINSIGHTS_SERVICE_NAME=$serviceName `
        --only-show-errors | Out-Null
}

if ($IncludeStage -and $ContainerAppStageName) {
    $prevErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $null = az containerapp show `
        --name $ContainerAppStageName `
        --resource-group $ResourceGroupName `
        --only-show-errors 2>$null
    $stageExists = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prevErrorAction

    if ($stageExists) {
        Write-Host "Updating Stage Container App env vars for App Insights: $ContainerAppStageName"
        az containerapp update `
            --name $ContainerAppStageName `
            --resource-group $ResourceGroupName `
            --set-env-vars `
                APPINSIGHTS_CONNECTION_STRING=$connectionString `
                APPINSIGHTS_SERVICE_NAME=$serviceName `
            --only-show-errors | Out-Null
    } else {
        Write-Host "Stage Container App not found ($ContainerAppStageName); skipping stage App Insights update."
    }
}

Write-Host "Observability provisioning complete."
