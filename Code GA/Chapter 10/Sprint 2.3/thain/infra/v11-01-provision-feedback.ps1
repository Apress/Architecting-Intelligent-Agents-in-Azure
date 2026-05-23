param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$EnvFile = ".\\.env.dev",
    [string]$FeedbackContainerNameOverride
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

if (-not (Test-Path $EnvFile)) {
    Write-Error "Env file not found: $EnvFile"
    exit 1
}

. $VarsFile

function Import-EnvFile {
    param([string]$Path)
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }
        if ($line -notmatch "=") {
            return
        }
        $parts = $line.Split("=", 2)
        $name = $parts[0].Trim()
        $value = $parts[1]
        if ($name) {
            [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

Import-EnvFile -Path $EnvFile

$CosmosDatabaseName = $env:COSMOS_DATABASE
if (-not $CosmosDatabaseName) {
    Write-Error "COSMOS_DATABASE not found in $EnvFile."
    exit 1
}

$FeedbackContainerParam = if ($FeedbackContainerNameOverride) { $FeedbackContainerNameOverride } else { $FeedbackContainerName }
if (-not $FeedbackContainerParam) {
    Write-Error "FeedbackContainerName not provided and not found in vars file."
    exit 1
}

$ttlDaysRaw = $env:FEEDBACK_TTL_DAYS
$ttlDays = 365
if ($ttlDaysRaw) {
    try {
        $ttlDays = [int]$ttlDaysRaw
    } catch {
        $ttlDays = 365
    }
}
$ttlSeconds = $null
if ($ttlDays -gt 0) {
    $ttlSeconds = $ttlDays * 24 * 60 * 60
} elseif ($ttlDays -eq 0) {
    $ttlSeconds = -1
}

Write-Host "Ensuring Cosmos DB feedback container: $FeedbackContainerParam"
try {
    az cosmosdb sql database create `
        --account-name $CosmosAccountName `
        --resource-group $ResourceGroupName `
        --name $CosmosDatabaseName `
        --only-show-errors | Out-Null
} catch {
    Write-Warning "Failed to create Cosmos DB database; attempting to continue."
}

$containerExists = $null
try {
    $containerExists = az cosmosdb sql container show `
        --account-name $CosmosAccountName `
        --resource-group $ResourceGroupName `
        --database-name $CosmosDatabaseName `
        --name $FeedbackContainerParam `
        --query "id" -o tsv 2>$null
} catch {
    $containerExists = $null
}

if (-not $containerExists) {
    $createArgs = @(
        "--account-name", $CosmosAccountName,
        "--resource-group", $ResourceGroupName,
        "--database-name", $CosmosDatabaseName,
        "--name", $FeedbackContainerParam,
        "--partition-key-path", "/scenario",
        "--only-show-errors"
    )
    if ($ttlSeconds -ne $null) {
        $createArgs += @("--ttl", $ttlSeconds)
    }
    az cosmosdb sql container create @createArgs *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Feedback container created."
    } else {
        Write-Error "Failed to create feedback container."
        exit 1
    }
} else {
    Write-Host "Feedback container already exists."
}

Write-Host "v1.1 feedback provisioning complete."
Write-Host "Workbook template: .\\infra\\templates\\workbook-feedback.json"

