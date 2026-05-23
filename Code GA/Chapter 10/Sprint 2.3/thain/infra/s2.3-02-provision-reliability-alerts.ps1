param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$EnvFile = ".\\.env.dev",
    [string]$ActionGroupName = "ag-thain-ops",
    [string]$ActionGroupShortName = "thainops",
    [string]$ActionEmail = ""
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

function Get-EnvValue {
    param(
        [string]$Path,
        [string]$Name
    )
    $pattern = "^\s*$([regex]::Escape($Name))=(.*)$"
    $line = Get-Content $Path | Where-Object { $_ -match $pattern } | Select-Object -First 1
    if (-not $line) { return $null }
    $matches = [regex]::Match($line, $pattern)
    if ($matches.Success) { return $matches.Groups[1].Value.Trim() }
    return $null
}

function Get-EnvInt {
    param([string]$Name, [int]$Default)
    $raw = Get-EnvValue -Path $EnvFile -Name $Name
    if (-not $raw) { return $Default }
    try { return [int]$raw } catch { return $Default }
}

function Get-EnvDouble {
    param([string]$Name, [double]$Default)
    $raw = Get-EnvValue -Path $EnvFile -Name $Name
    if (-not $raw) { return $Default }
    try { return [double]$raw } catch { return $Default }
}

$errorRateThreshold = Get-EnvDouble -Name "THAIN_SLO_ERROR_RATE_PCT" -Default 5.0
$errorWindow = Get-EnvInt -Name "THAIN_SLO_ERROR_WINDOW_MIN" -Default 15
$p95LatencyThreshold = Get-EnvInt -Name "THAIN_SLO_P95_LATENCY_MS" -Default 30000
$p95Window = Get-EnvInt -Name "THAIN_SLO_P95_WINDOW_MIN" -Default 15
$depFailureThreshold = Get-EnvInt -Name "THAIN_SLO_DEP_FAILURE_COUNT" -Default 3
$depFailureWindow = Get-EnvInt -Name "THAIN_SLO_DEP_FAILURE_WINDOW_MIN" -Default 5

try {
    az extension show --name scheduled-query --only-show-errors | Out-Null
} catch {
    Write-Host "Installing Azure CLI extension: scheduled-query"
    az extension add --name scheduled-query --yes --only-show-errors | Out-Null
}

$appInsightsId = az resource show `
    --resource-group $ResourceGroupName `
    --name $AppInsightsName `
    --resource-type "Microsoft.Insights/components" `
    --query id -o tsv

if (-not $appInsightsId) {
    Write-Error "Unable to resolve Application Insights resource ID."
    exit 1
}

$actionGroupId = az monitor action-group list `
    --resource-group $ResourceGroupName `
    --query "[?name=='$ActionGroupName'].id | [0]" -o tsv `
    --only-show-errors

if (-not $actionGroupId) {
    Write-Host "Creating action group: $ActionGroupName"
    if ($ActionEmail) {
        az monitor action-group create `
            --resource-group $ResourceGroupName `
            --name $ActionGroupName `
            --short-name $ActionGroupShortName `
            --action email thain-ops $ActionEmail `
            --only-show-errors | Out-Null
    } else {
        az monitor action-group create `
            --resource-group $ResourceGroupName `
            --name $ActionGroupName `
            --short-name $ActionGroupShortName `
            --only-show-errors | Out-Null
        Write-Warning "No ActionEmail provided. Alerts will be created without an email receiver."
    }

    $actionGroupId = az monitor action-group list `
        --resource-group $ResourceGroupName `
        --query "[?name=='$ActionGroupName'].id | [0]" -o tsv `
        --only-show-errors
}

function Upsert-ScheduledQueryAlert {
    param(
        [string]$Name,
        [string]$Description,
        [int]$Severity,
        [string]$WindowSize,
        [string]$EvaluationFrequency,
        [string]$Query
    )

    $querySingleLine = ($Query -replace "`r", " " -replace "`n", " ").Trim()
    $escapedQuery = $querySingleLine.Replace('"', '\"')
    $conditionQueryArg = "Q1=""$escapedQuery"""
    $condition = "count 'Q1' > 0"
    $exists = az monitor scheduled-query list `
        --resource-group $ResourceGroupName `
        --query "[?name=='$Name'].id | [0]" -o tsv `
        --only-show-errors

    if ($exists) {
        Write-Host "Updating alert rule: $Name"
        az monitor scheduled-query update `
            --resource-group $ResourceGroupName `
            --name $Name `
            --description $Description `
            --severity $Severity `
            --window-size $WindowSize `
            --evaluation-frequency $EvaluationFrequency `
            --condition $condition `
            --condition-query $conditionQueryArg `
            --action-groups $actionGroupId `
            --skip-query-validation true `
            --only-show-errors | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to update alert rule: $Name"
        }
    } else {
        Write-Host "Creating alert rule: $Name"
        az monitor scheduled-query create `
            --resource-group $ResourceGroupName `
            --name $Name `
            --location $Location `
            --description $Description `
            --severity $Severity `
            --window-size $WindowSize `
            --evaluation-frequency $EvaluationFrequency `
            --scopes $appInsightsId `
            --condition $condition `
            --condition-query $conditionQueryArg `
            --action-groups $actionGroupId `
            --skip-query-validation true `
            --only-show-errors | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create alert rule: $Name"
        }
    }
}

$errorRateQuery = @"
dependencies
| where timestamp > ago(${errorWindow}m)
| where name == "thain.trace"
| extend error_count = todouble(customDimensions["thain.error.count"])
| extend degraded = tolower(coalesce(tostring(customDimensions["thain.reliability.degraded"]), tostring(customDimensions["thain.fallback.used"])))
| summarize total=count(), failures=countif(error_count > 0 or degraded == "true")
| extend error_rate_pct = iif(total == 0, 0.0, todouble(failures) * 100.0 / todouble(total))
| where error_rate_pct > ${errorRateThreshold}
| project breach="error_rate", error_rate_pct
"@

$latencyQuery = @"
dependencies
| where timestamp > ago(${p95Window}m)
| where name == "thain.trace"
| extend latency_ms = todouble(customDimensions["thain.latency.total_ms"])
| where isnotnull(latency_ms)
| summarize p95_latency_ms = percentile(latency_ms, 95)
| where p95_latency_ms > ${p95LatencyThreshold}
| project breach="p95_latency", p95_latency_ms
"@

$dependencyFailureQuery = @"
dependencies
| where timestamp > ago(${depFailureWindow}m)
| where name == "thain.trace"
| extend failures = todouble(customDimensions["thain.dependency.failure_count"])
| where isnotnull(failures)
| summarize dependency_failures = sum(failures)
| where dependency_failures > ${depFailureThreshold}
| project breach="dependency_failures", dependency_failures
"@

Upsert-ScheduledQueryAlert `
    -Name "thain-s2-3-error-rate" `
    -Description "Thain reliability alert: error rate threshold exceeded." `
    -Severity 2 `
    -WindowSize ("{0}m" -f [math]::Max($errorWindow, 1)) `
    -EvaluationFrequency "5m" `
    -Query $errorRateQuery

Upsert-ScheduledQueryAlert `
    -Name "thain-s2-3-p95-latency" `
    -Description "Thain reliability alert: p95 latency threshold exceeded." `
    -Severity 2 `
    -WindowSize ("{0}m" -f [math]::Max($p95Window, 1)) `
    -EvaluationFrequency "5m" `
    -Query $latencyQuery

Upsert-ScheduledQueryAlert `
    -Name "thain-s2-3-dependency-failures" `
    -Description "Thain reliability alert: dependency failures exceeded threshold." `
    -Severity 2 `
    -WindowSize ("{0}m" -f [math]::Max($depFailureWindow, 1)) `
    -EvaluationFrequency "5m" `
    -Query $dependencyFailureQuery

Write-Host "Reliability alerts provisioned successfully."
Write-Host "  Action Group: $actionGroupId"
Write-Host ("  Error rate threshold: > {0}% over {1}m" -f $errorRateThreshold, $errorWindow)
Write-Host ("  P95 latency threshold: > {0}ms over {1}m" -f $p95LatencyThreshold, $p95Window)
Write-Host ("  Dependency failures threshold: > {0} over {1}m" -f $depFailureThreshold, $depFailureWindow)
