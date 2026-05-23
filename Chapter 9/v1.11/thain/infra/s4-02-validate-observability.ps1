param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$BaseUrl,
    [int]$MaxAttempts = 8,
    [int]$DelaySeconds = 10,
    [int]$WindowMinutes = 10,
    [int]$MaxErrorRatePercent = 5
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

if (-not $AppInsightsName -or -not $ResourceGroupName) {
    Write-Error "Missing AppInsightsName or ResourceGroupName in vars file."
    exit 1
}

if (-not $BaseUrl) {
    $fqdn = az containerapp show `
        --name $ContainerAppName `
        --resource-group $ResourceGroupName `
        --query properties.configuration.ingress.fqdn -o tsv
    if (-not $fqdn) {
        Write-Error "Unable to resolve Container App FQDN."
        exit 1
    }
    $BaseUrl = "https://$fqdn"
}

function Invoke-Chat {
    param([string]$Prompt)
    $payload = @{ message = $Prompt } | ConvertTo-Json -Depth 3
    return Invoke-RestMethod -Method Post -Uri "$BaseUrl/chat" -ContentType "application/json" -Body $payload
}

Write-Host "Validating App Insights trace export via $BaseUrl"

$prompt = "Quick check: please confirm receipt."
$response = Invoke-Chat -Prompt $prompt
if (-not $response.trace_id) {
    Write-Error "Observability validation failed: /chat did not return trace_id."
    exit 1
}

$traceId = $response.trace_id
Write-Host "Trace ID: $traceId"

$health = Invoke-RestMethod -Method Get -Uri "$BaseUrl/health"
if (-not $health.status -or $health.status -ne "ok") {
    Write-Error "Observability validation failed: /health did not return ok."
    exit 1
}

$kusto = "union traces, dependencies, requests | where timestamp > ago(${WindowMinutes}m) | where tostring(customDimensions['thain.trace_id']) == '$traceId' | summarize hits=count()"

$found = $false
for ($i = 1; $i -le $MaxAttempts; $i++) {
    Write-Host "Querying App Insights (attempt $i/$MaxAttempts)..."
    $result = az monitor app-insights query `
        --app $AppInsightsName `
        --resource-group $ResourceGroupName `
        --analytics-query "$kusto" `
        --only-show-errors `
        -o json | ConvertFrom-Json

    $hits = 0
    if ($result.tables -and $result.tables[0].rows -and $result.tables[0].rows.Count -gt 0) {
        try {
            $hits = [int]$result.tables[0].rows[0][0]
        } catch {
            $hits = 0
        }
    }

    if ($hits -gt 0) {
        $found = $true
        break
    }
    Start-Sleep -Seconds $DelaySeconds
}

if (-not $found) {
    Write-Error "Observability validation failed: trace_id not found in App Insights."
    exit 1
}

Write-Host "Checking App Insights error rate window (last $WindowMinutes minutes)..."
$errorQuery = "requests | where timestamp > ago(${WindowMinutes}m) | summarize total=count(), failed=countif(success == false) | extend errorRate = iif(total == 0, 0.0, todouble(failed) / todouble(total) * 100.0)"

$errResult = az monitor app-insights query `
    --app $AppInsightsName `
    --resource-group $ResourceGroupName `
    --analytics-query "$errorQuery" `
    --only-show-errors `
    -o json | ConvertFrom-Json

$errorRate = 0.0
if ($errResult.tables -and $errResult.tables[0].rows -and $errResult.tables[0].rows.Count -gt 0) {
    $row = $errResult.tables[0].rows[0]
    if ($row.Count -ge 3) {
        $errorRate = [double]$row[2]
    }
}

Write-Host ("App Insights error rate: {0:N2}%" -f $errorRate)
if ($errorRate -gt $MaxErrorRatePercent) {
    Write-Error "Observability validation failed: error rate ${errorRate}% exceeds threshold ${MaxErrorRatePercent}%."
    exit 1
}

Write-Host "Observability validation OK."
