param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$EnvFile = ".\\.env.dev",
    [string]$BaseUrl,
    [int]$WindowMinutes = 20,
    [int]$MaxAttempts = 10,
    [int]$DelaySeconds = 10,
    [string]$CompareToLabel = "improved_v12",
    [string]$EvalRunLabel,
    [double]$MaxAvgDrop = 0.10,
    [double]$MaxPassRateDrop = 5.0,
    [switch]$SkipEvalGate
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
    $payload = @{ message = $Prompt } | ConvertTo-Json -Depth 4
    return Invoke-RestMethod -Method Post -Uri "$BaseUrl/chat" -ContentType "application/json" -Body $payload
}

$cacheEnabledRaw = [string](Get-EnvValue -Path $EnvFile -Name "THAIN_ENABLE_CACHE")
$cacheEnabled = $cacheEnabledRaw.Trim().ToLowerInvariant() -in @("1", "true", "yes", "y", "on")

$prompts = @(
    "Please summarize what you can help with in this support workflow.",
    "Please summarize what you can help with in this support workflow.",
    "What is the escalation policy for recurring network outages?",
    "Sensor calibration drift keeps reappearing. Need recovery playbook steps."
)

Write-Host "Validating Sprint 2.2 optimization telemetry via $BaseUrl"
$traceIds = New-Object System.Collections.Generic.List[string]
foreach ($prompt in $prompts) {
    $resp = Invoke-Chat -Prompt $prompt
    if (-not $resp.trace_id) {
        Write-Error "Optimization validation failed: /chat did not return trace_id."
        exit 1
    }
    $traceIds.Add([string]$resp.trace_id)
    Write-Host "Trace ID: $($resp.trace_id)"
}

$traceList = ($traceIds | ForEach-Object { "'$_'" }) -join ","
$kusto = "dependencies | where timestamp > ago(${WindowMinutes}m) | where name == 'thain.trace' | where tostring(customDimensions['thain.trace_id']) in ($traceList) | where isnotempty(tostring(customDimensions['thain.trace_id'])) | where isnotempty(tostring(customDimensions['thain.latency.total_ms'])) | where isnotempty(tostring(customDimensions['thain.tokens.total'])) | where isnotempty(tostring(customDimensions['thain.tokens.source'])) | where isnotempty(tostring(customDimensions['thain.cost.estimate_available'])) | where isnotempty(tostring(customDimensions['thain.cache.hit'])) | where isnotempty(tostring(customDimensions['thain.model.profile'])) | project trace_id=tostring(customDimensions['thain.trace_id']), latency_ms=toint(customDimensions['thain.latency.total_ms']), total_tokens=toint(customDimensions['thain.tokens.total']), token_source=tostring(customDimensions['thain.tokens.source']), cost_estimate_usd=todouble(customDimensions['thain.cost.estimate_usd']), cost_available=tostring(customDimensions['thain.cost.estimate_available']), cache_hit=tolower(tostring(customDimensions['thain.cache.hit'])), model_profile=tostring(customDimensions['thain.model.profile'])"

$rows = $null
for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    Write-Host "Querying App Insights (attempt $attempt/$MaxAttempts)..."
    $query = az monitor app-insights query `
        --app $AppInsightsName `
        --resource-group $ResourceGroupName `
        --analytics-query $kusto `
        --only-show-errors `
        -o json | ConvertFrom-Json
    if ($query.tables -and $query.tables[0].rows -and $query.tables[0].rows.Count -ge $traceIds.Count) {
        $rows = $query.tables[0].rows
        break
    }
    Start-Sleep -Seconds $DelaySeconds
}

if (-not $rows) {
    Write-Error "Optimization validation failed: telemetry rows not found for all traces."
    exit 1
}

$columns = $query.tables[0].columns
$columnIndex = @{}
for ($i = 0; $i -lt $columns.Count; $i++) {
    $columnIndex[[string]$columns[$i].name] = $i
}

function Get-FieldValue {
    param(
        [object[]]$Row,
        [hashtable]$IndexMap,
        [string]$Name
    )
    if ($IndexMap.ContainsKey($Name)) {
        return $Row[$IndexMap[$Name]]
    }
    return $null
}

function Get-RequiredValue {
    param(
        [object[]]$Row,
        [hashtable]$IndexMap,
        [string]$ProjectedName,
        [string]$DimensionName
    )
    $projected = Get-FieldValue -Row $Row -IndexMap $IndexMap -Name $ProjectedName
    if ($null -ne $projected -and -not [string]::IsNullOrWhiteSpace([string]$projected)) {
        return $projected
    }
    $dims = Get-FieldValue -Row $Row -IndexMap $IndexMap -Name "customDimensions"
    if ($dims -and $dims.PSObject.Properties.Name -contains $DimensionName) {
        return $dims.$DimensionName
    }
    return $null
}

$validated = @()
foreach ($row in $rows) {
    $record = @{
        trace_id = [string](Get-RequiredValue -Row $row -IndexMap $columnIndex -ProjectedName "trace_id" -DimensionName "thain.trace_id")
        latency_ms = [string](Get-RequiredValue -Row $row -IndexMap $columnIndex -ProjectedName "latency_ms" -DimensionName "thain.latency.total_ms")
        total_tokens = [string](Get-RequiredValue -Row $row -IndexMap $columnIndex -ProjectedName "total_tokens" -DimensionName "thain.tokens.total")
        token_source = [string](Get-RequiredValue -Row $row -IndexMap $columnIndex -ProjectedName "token_source" -DimensionName "thain.tokens.source")
        cost_estimate_usd = [string](Get-RequiredValue -Row $row -IndexMap $columnIndex -ProjectedName "cost_estimate_usd" -DimensionName "thain.cost.estimate_usd")
        cost_available = [string](Get-RequiredValue -Row $row -IndexMap $columnIndex -ProjectedName "cost_available" -DimensionName "thain.cost.estimate_available")
        cache_hit = [string](Get-RequiredValue -Row $row -IndexMap $columnIndex -ProjectedName "cache_hit" -DimensionName "thain.cache.hit")
        model_profile = [string](Get-RequiredValue -Row $row -IndexMap $columnIndex -ProjectedName "model_profile" -DimensionName "thain.model.profile")
    }

    foreach ($key in @("trace_id", "latency_ms", "total_tokens", "token_source", "cost_available", "model_profile")) {
        if ([string]::IsNullOrWhiteSpace([string]$record[$key])) {
            Write-Error "Optimization validation failed: missing '$key' in telemetry row."
            exit 1
        }
    }

    if ($record.cost_available.ToLowerInvariant() -ne "true") {
        Write-Error "Optimization validation failed: cost_estimate_available is not true."
        exit 1
    }

    $record.cache_hit = $record.cache_hit.ToLowerInvariant()
    $validated += [pscustomobject]$record
}

$uniqueTraceIds = $validated | Select-Object -ExpandProperty trace_id -Unique
$missingTraceIds = @($traceIds | Where-Object { $uniqueTraceIds -notcontains $_ })
if ($missingTraceIds.Count -gt 0) {
    Write-Error ("Optimization validation failed: missing telemetry for trace_id(s): {0}" -f ($missingTraceIds -join ", "))
    exit 1
}

$cacheHits = @($validated | Where-Object { $_.cache_hit -eq "true" }).Count
if ($cacheEnabled -and $cacheHits -lt 1) {
    Write-Warning "Cache is enabled but no cache hits were recorded in this run. Continuing (non-fatal)."
}

$latencyValues = @()
$tokenValues = @()
$costValues = @()
foreach ($row in $validated) {
    $latencyValues += [double]$row.latency_ms
    $tokenValues += [double]$row.total_tokens
    $costValues += [double]$row.cost_estimate_usd
}

$avgLatency = [math]::Round((($latencyValues | Measure-Object -Average).Average), 2)
$avgTokens = [math]::Round((($tokenValues | Measure-Object -Average).Average), 2)
$avgCost = [math]::Round((($costValues | Measure-Object -Average).Average), 6)

Write-Host ("Optimization telemetry OK: avg_latency_ms={0}, avg_tokens={1}, avg_cost_usd={2}, cache_hits={3}/{4}" -f $avgLatency, $avgTokens, $avgCost, $cacheHits, $validated.Count)

if ($SkipEvalGate) {
    Write-Host "Skipped eval regression gate (-SkipEvalGate)."
    exit 0
}

$evalScript = ".\\infra\\v11-05-eval-judge.ps1"
if (-not (Test-Path $evalScript)) {
    Write-Error "Optimization validation failed: missing eval script $evalScript"
    exit 1
}

if (-not $EvalRunLabel) {
    $EvalRunLabel = "s2_2_guard_" + (Get-Date -Format "yyyyMMddHHmmss")
}

Write-Host "Running quality regression gate via eval script..."
$evalOutput = & $evalScript -RunLabel $EvalRunLabel -CompareTo $CompareToLabel 2>&1 | Out-String
Write-Host $evalOutput

$deltaMatch = [regex]::Match($evalOutput, "delta:\s*avg=([-+]?\d+(?:\.\d+)?),\s*pass_rate=([-+]?\d+(?:\.\d+)?)%")
if (-not $deltaMatch.Success) {
    Write-Error "Optimization validation failed: could not parse eval delta from output."
    exit 1
}

$avgDelta = [double]$deltaMatch.Groups[1].Value
$passDelta = [double]$deltaMatch.Groups[2].Value

if ($avgDelta -lt (-1.0 * $MaxAvgDrop)) {
    Write-Error ("Optimization validation failed: avg score regression {0} exceeds threshold {1}." -f $avgDelta, -1.0 * $MaxAvgDrop)
    exit 1
}

if ($passDelta -lt (-1.0 * $MaxPassRateDrop)) {
    Write-Error ("Optimization validation failed: pass-rate regression {0}% exceeds threshold {1}%." -f $passDelta, -1.0 * $MaxPassRateDrop)
    exit 1
}

Write-Host ("Quality gate OK: avg_delta={0}, pass_rate_delta={1}%" -f $avgDelta, $passDelta)
Write-Host "Sprint 2.2 validation passed."
