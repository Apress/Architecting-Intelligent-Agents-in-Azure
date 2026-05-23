param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$BaseUrl,
    [int]$MaxAttempts = 8,
    [int]$DelaySeconds = 10,
    [int]$WindowMinutes = 10
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

Write-Host "Validating telemetry via $BaseUrl"
$response = Invoke-Chat -Prompt "Quick telemetry check."
if (-not $response.trace_id) {
    Write-Error "Telemetry validation failed: /chat did not return trace_id."
    exit 1
}

$traceId = $response.trace_id
Write-Host "Trace ID: $traceId"

$kusto = "dependencies | where timestamp > ago(${WindowMinutes}m) | where name == 'thain.trace' | where tostring(customDimensions['thain.trace_id']) == '$traceId' | project customDimensions"

$dims = $null
for ($i = 1; $i -le $MaxAttempts; $i++) {
    Write-Host "Querying App Insights (attempt $i/$MaxAttempts)..."
    $result = az monitor app-insights query `
        --app $AppInsightsName `
        --resource-group $ResourceGroupName `
        --analytics-query "$kusto" `
        --only-show-errors `
        -o json | ConvertFrom-Json

    if ($result.tables -and $result.tables[0].rows -and $result.tables[0].rows.Count -gt 0) {
        $raw = $result.tables[0].rows[0][0]
        try {
            $dims = $raw | ConvertFrom-Json
        } catch {
            $dims = $null
        }
        if ($dims) { break }
    }
    Start-Sleep -Seconds $DelaySeconds
}

if (-not $dims) {
    Write-Error "Telemetry validation failed: trace_id not found in App Insights."
    exit 1
}

$requiredKeys = @(
    "thain.tokens.total",
    "thain.latency.total_ms",
    "thain.cost.estimate_available",
    "thain.tokens.source"
)

$missing = @()
$dimKeys = @($dims.PSObject.Properties.Name)
foreach ($key in $requiredKeys) {
    if (-not ($dimKeys -contains $key)) {
        $missing += $key
    }
}

if ($missing.Count -gt 0) {
    Write-Error ("Telemetry validation failed. Missing fields: {0}" -f ($missing -join ", "))
    exit 1
}

$costAvailable = [string]$dims."thain.cost.estimate_available"
if ($costAvailable.ToLowerInvariant() -ne "true") {
    Write-Error "Telemetry validation failed. Cost estimate is unavailable. Set THAIN_COST_INPUT_PER_1K_USD and THAIN_COST_OUTPUT_PER_1K_USD, redeploy, and retry."
    exit 1
}

if (-not ($dimKeys -contains "thain.cost.estimate_usd")) {
    Write-Error "Telemetry validation failed. thain.cost.estimate_usd is missing."
    exit 1
}

Write-Host "Telemetry validation OK."
