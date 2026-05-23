param(
    [ValidateSet("normal", "openai", "search", "cosmos")]
    [string]$Scenario = "normal",
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$EnvFile = ".\\.env.dev",
    [string]$BaseUrl,
    [int]$WindowMinutes = 20,
    [int]$MaxAttempts = 10,
    [int]$DelaySeconds = 10,
    [string]$CompareToLabel = "improved_v12",
    [string]$EvalRunLabel,
    [double]$MaxAvgDrop = 0.10,
    [double]$MaxPassRateDrop = 1.0
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Error "Azure CLI (az) not found. Install Azure CLI first."
    exit 1
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "python not found. Install/activate python first."
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
    try {
        return Invoke-RestMethod -Method Post -Uri "$BaseUrl/chat" -ContentType "application/json" -Body $payload
    } catch {
        $msg = $_.Exception.Message
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $msg = "$msg | $($_.ErrorDetails.Message)"
        }
        throw "Chat request failed: $msg"
    }
}

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

function Get-EnvBool {
    param([string]$Name, [bool]$Default = $false)
    $raw = (Get-EnvValue -Path $EnvFile -Name $Name)
    if (-not $raw) { return $Default }
    return @("1","true","yes","y","on") -contains $raw.Trim().ToLowerInvariant()
}

function Ensure-RecallIndex {
    $searchMode = (Get-EnvValue -Path $EnvFile -Name "AZURE_SEARCH_MODE")
    if (-not $searchMode) { $searchMode = "semantic" }
    $searchMode = $searchMode.Trim().ToLowerInvariant()
    $recallEnabled = Get-EnvBool -Name "ENABLE_RECALL" -Default $true
    $indexName = Get-EnvValue -Path $EnvFile -Name "AZURE_SEARCH_INDEX_NAME"

    if ($searchMode -eq "off" -or -not $recallEnabled) {
        Write-Host "Recall index ensure skipped (search mode off or recall disabled)."
        return
    }

    if (-not $indexName) {
        Write-Error "Reliability validation failed: AZURE_SEARCH_INDEX_NAME is required when recall is enabled."
        exit 1
    }

    $ensureScript = ".\\infra\\scripts\\s2_3_ensure_recall_index.py"
    if (-not (Test-Path $ensureScript)) {
        Write-Error "Reliability validation failed: missing script $ensureScript"
        exit 1
    }

    Write-Host "Ensuring semantic recall index exists: $indexName"
    & python $ensureScript --env-file $EnvFile
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Reliability validation failed: unable to provision/verify recall index '$indexName'."
        exit $LASTEXITCODE
    }
}

Import-EnvFile -Path $EnvFile
if ($Scenario -eq "normal") {
    Ensure-RecallIndex
} else {
    Write-Host "Skipping recall index ensure for chaos scenario '$Scenario'."
}

$prompts = @(
    "What is the escalation policy for recurring network outages?",
    "Multiple sites report Wi-Fi drops. Which KB procedure should we follow?",
    "Summarize current guidance for repeated VPN authentication failures."
)

if ($Scenario -ne "normal") {
    Write-Host "Scenario '$Scenario' expects chaos flag deployment (env var change + redeploy) before validation."
}

Write-Host "Validating Sprint 2.3 reliability scenario '$Scenario' via $BaseUrl"
$traceIds = New-Object System.Collections.Generic.List[string]
$responses = New-Object System.Collections.Generic.List[string]
foreach ($prompt in $prompts) {
    try {
        $resp = Invoke-Chat -Prompt $prompt
    } catch {
        Write-Error ("Reliability validation failed in scenario '{0}': {1}" -f $Scenario, $_.Exception.Message)
        exit 1
    }

    if (-not $resp -or [string]::IsNullOrWhiteSpace([string]$resp.response)) {
        Write-Error ("Reliability validation failed: /chat response body is empty in scenario '{0}'." -f $Scenario)
        exit 1
    }

    if (-not $resp.trace_id) {
        Write-Error "Reliability validation failed: /chat did not return trace_id."
        exit 1
    }
    $traceIds.Add([string]$resp.trace_id)
    $responses.Add([string]$resp.response)
    Write-Host "Trace ID: $($resp.trace_id)"
}

$traceList = ($traceIds | ForEach-Object { "'$_'" }) -join ","
$kusto = "dependencies | where timestamp > ago(${WindowMinutes}m) | where name == 'thain.trace' | where tostring(customDimensions['thain.trace_id']) in ($traceList) | extend degraded = tolower(coalesce(tostring(customDimensions['thain.reliability.degraded']), tostring(customDimensions['thain.fallback.used']))) | project trace_id=tostring(customDimensions['thain.trace_id']), latency_ms=todouble(customDimensions['thain.latency.total_ms']), retry_count=toint(customDimensions['thain.dependency.retry_count']), failure_count=toint(customDimensions['thain.dependency.failure_count']), suppressed=tolower(tostring(customDimensions['thain.dependency.suppressed'])), degraded=degraded, fallback_path=tostring(customDimensions['thain.fallback.path']), failed_deps=tostring(customDimensions['thain.dependency.failed'])"

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
    Write-Error "Reliability validation failed: telemetry rows not found for all traces."
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

$validated = @()
foreach ($row in $rows) {
    $validated += [pscustomobject]@{
        trace_id = [string](Get-FieldValue -Row $row -IndexMap $columnIndex -Name "trace_id")
        latency_ms = [double](Get-FieldValue -Row $row -IndexMap $columnIndex -Name "latency_ms")
        retry_count = [int](Get-FieldValue -Row $row -IndexMap $columnIndex -Name "retry_count")
        failure_count = [int](Get-FieldValue -Row $row -IndexMap $columnIndex -Name "failure_count")
        suppressed = [string](Get-FieldValue -Row $row -IndexMap $columnIndex -Name "suppressed")
        fallback_used = [string](Get-FieldValue -Row $row -IndexMap $columnIndex -Name "degraded")
        fallback_path = [string](Get-FieldValue -Row $row -IndexMap $columnIndex -Name "fallback_path")
        failed_deps = [string](Get-FieldValue -Row $row -IndexMap $columnIndex -Name "failed_deps")
    }
}

$uniqueTraceIds = $validated | Select-Object -ExpandProperty trace_id -Unique
$missingTraceIds = @($traceIds | Where-Object { $uniqueTraceIds -notcontains $_ })
if ($missingTraceIds.Count -gt 0) {
    Write-Error ("Reliability validation failed: missing telemetry for trace_id(s): {0}" -f ($missingTraceIds -join ", "))
    exit 1
}

$avgLatency = [math]::Round((($validated | Measure-Object latency_ms -Average).Average), 2)
$totalRetries = ($validated | Measure-Object retry_count -Sum).Sum
$totalFailures = ($validated | Measure-Object failure_count -Sum).Sum
$fallbackCount = @($validated | Where-Object { $_.fallback_used -eq "true" }).Count
$suppressedCount = @($validated | Where-Object { $_.suppressed -eq "true" }).Count

Write-Host ("Reliability telemetry OK: avg_latency_ms={0}, retries={1}, failures={2}, fallback_used={3}/{4}" -f $avgLatency, $totalRetries, $totalFailures, $fallbackCount, $validated.Count)

if ($Scenario -ne "normal") {
    $scenarioEvidence = @(
        $validated | Where-Object {
            $_.failed_deps.ToLowerInvariant().Contains($Scenario.ToLowerInvariant()) -or
            ($Scenario -eq "openai" -and $_.fallback_used -eq "true")
        }
    )
    if ($scenarioEvidence.Count -lt 1) {
        $flagName = "THAIN_CHAOS_SIMULATE_{0}_FAILURE" -f $Scenario.ToUpperInvariant()
        Write-Error "Reliability validation failed: no '$Scenario' failure signal found. Enable $flagName=true, redeploy, and re-run."
        exit 1
    }

    if ($Scenario -eq "openai") {
        $degradedResponses = @($responses | Where-Object { $_ -match "temporarily degraded" })
        if ($degradedResponses.Count -lt 1) {
            Write-Error "Reliability validation failed: openai chaos scenario did not produce a degraded response."
            exit 1
        }
    }

    Write-Host "Scenario '$Scenario' validation passed."
    exit 0
}

$evalScript = ".\\infra\\v11-05-eval-judge.ps1"
if (-not (Test-Path $evalScript)) {
    Write-Error "Reliability validation failed: missing eval script $evalScript"
    exit 1
}

if (-not $EvalRunLabel) {
    $EvalRunLabel = "s2_3_guard_" + (Get-Date -Format "yyyyMMddHHmmss")
}

if ($totalFailures -gt 0 -or $suppressedCount -gt 0) {
    $cooldownSeconds = Get-EnvInt -Name "THAIN_DEPENDENCY_COOLDOWN_SECONDS" -Default 30
    $cacheEnabled = Get-EnvBool -Name "THAIN_ENABLE_CACHE" -Default $false
    $cacheTtlSeconds = if ($cacheEnabled) { Get-EnvInt -Name "THAIN_CACHE_TTL_SECONDS" -Default 120 } else { 0 }
    $stabilizeSeconds = [math]::Max($cooldownSeconds + 5, $cacheTtlSeconds + 5)
    Write-Host ("Stabilizing before eval gate due to transient failures/suppression (wait {0}s)..." -f $stabilizeSeconds)
    Start-Sleep -Seconds $stabilizeSeconds
}

Write-Host "Running mandatory quality regression gate via eval script..."
$evalOutput = & $evalScript -RunLabel $EvalRunLabel -CompareTo $CompareToLabel 2>&1 | Out-String
Write-Host $evalOutput

$deltaMatch = [regex]::Match($evalOutput, "delta:\s*avg=([-+]?\d+(?:\.\d+)?),\s*pass_rate=([-+]?\d+(?:\.\d+)?)%")
if (-not $deltaMatch.Success) {
    Write-Error "Reliability validation failed: could not parse eval delta from output."
    exit 1
}

$avgDelta = [double]$deltaMatch.Groups[1].Value
$passDelta = [double]$deltaMatch.Groups[2].Value

# Pass-rate is quantized by dataset size (e.g., n=11 -> 9.1% per item).
# Derive an effective threshold that allows one-item variance by default.
$effectivePassRateDrop = $MaxPassRateDrop
$summaryMatches = [regex]::Matches(
    $evalOutput,
    "summary:\s*avg=[-+]?\d+(?:\.\d+)?,\s*pass_rate=[-+]?\d+(?:\.\d+)?%,\s*n=(\d+)"
)
if ($summaryMatches.Count -gt 0) {
    $sampleSizes = @()
    foreach ($m in $summaryMatches) {
        try { $sampleSizes += [int]$m.Groups[1].Value } catch {}
    }
    if ($sampleSizes.Count -gt 0) {
        $minSampleSize = ($sampleSizes | Measure-Object -Minimum).Minimum
        if ($minSampleSize -gt 0) {
            $singleItemStepPct = [math]::Round((100.0 / [double]$minSampleSize), 1)
            $effectivePassRateDrop = [math]::Max($MaxPassRateDrop, $singleItemStepPct)
            Write-Host ("Quality gate pass-rate threshold adjusted for sample size n={0}: {1}% (requested {2}%)." -f $minSampleSize, $effectivePassRateDrop, $MaxPassRateDrop)
        }
    }
}

if ($avgDelta -lt (-1.0 * $MaxAvgDrop)) {
    Write-Error ("Reliability validation failed: avg score regression {0} exceeds threshold {1}." -f $avgDelta, -1.0 * $MaxAvgDrop)
    exit 1
}

if ($passDelta -lt (-1.0 * $effectivePassRateDrop)) {
    Write-Error ("Reliability validation failed: pass-rate regression {0}% exceeds threshold {1}%." -f $passDelta, -1.0 * $effectivePassRateDrop)
    exit 1
}

Write-Host ("Quality gate OK: avg_delta={0}, pass_rate_delta={1}%" -f $avgDelta, $passDelta)
Write-Host "Sprint 2.3 reliability validation passed."
