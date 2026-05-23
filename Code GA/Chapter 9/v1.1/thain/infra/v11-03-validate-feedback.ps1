param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$EnvFile,
    [string]$BaseUrl,
    [int]$MaxAttempts = 6,
    [int]$DelaySeconds = 10,
    [int]$WindowMinutes = 20
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Error "Azure CLI (az) not found. Install Azure CLI first."
    exit 1
}

try {
    az account show --only-show-errors | Out-Null
}
catch {
    Write-Error "Azure CLI not logged in. Run: az login"
    exit 1
}

if (-not (Test-Path $VarsFile)) {
    Write-Error "Vars file not found: $VarsFile"
    exit 1
}

. $VarsFile

if (-not $EnvFile) {
    $defaultEnv = ".\\.env.dev"
    if (Test-Path $defaultEnv) {
        $EnvFile = $defaultEnv
    }
    else {
        $EnvFile = ".\\.env"
    }
}

if (-not (Test-Path $EnvFile)) {
    Write-Error "Env file not found: $EnvFile"
    exit 1
}

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

function Invoke-Feedback {
    param([hashtable]$Payload)
    return Invoke-RestMethod -Method Post -Uri "$BaseUrl/feedback" -ContentType "application/json" -Body ($Payload | ConvertTo-Json -Depth 5)
}

Write-Host "Loading environment from $EnvFile"
Import-EnvFile -Path $EnvFile

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

$feedbackTraceId = [System.Guid]::NewGuid().ToString("N")
$samples = @(
    @{
        scenario = "answer"
        decision = "rejected"
        reason = "wrong_evidence"
        rating = 2
        comment = "Validation feedback sample"
        source = "qa"
        traceId = $feedbackTraceId
    },
    @{
        scenario = "answer"
        decision = "approved"
        reason = "should_approve"
        rating = 5
        comment = "Approval confirmed"
        source = "qa"
        traceId = $feedbackTraceId
    },
    @{
        scenario = "retrieval"
        decision = "overridden"
        reason = "missing_evidence"
        rating = 3
        comment = "Retrieve_docs missed evidence"
        source = "qa"
        traceId = $feedbackTraceId
    }
)

Write-Host "Submitting feedback via $BaseUrl"
$responses = @()
foreach ($payload in $samples) {
    $resp = Invoke-Feedback -Payload $payload
    if (-not $resp.id) {
        Write-Error "Feedback submission failed: response did not return id."
        exit 1
    }
    $responses += $resp
    Write-Host "Feedback ID: $($resp.id)"
}

$feedbackId = $responses[0].id
Write-Host "Fetching feedback record..."
$record = Invoke-RestMethod -Method Get -Uri "$BaseUrl/feedback/$feedbackId" -ContentType "application/json"
if (-not $record.id) {
    Write-Error "Feedback record lookup failed."
    exit 1
}

if (-not $AppInsightsName -or -not $ResourceGroupName) {
    Write-Host "AppInsightsName/ResourceGroupName missing; skipping telemetry lookup."
    Write-Host "Validation partially complete: feedback recorded and retrievable."
    exit 0
}

$feedbackKusto = "dependencies | where timestamp > ago(${WindowMinutes}m) | where name == 'thain.trace' | where tostring(customDimensions['thain.trace_id']) == '$feedbackTraceId' | where tostring(customDimensions['thain.feedback.submitted']) == 'true' | summarize hits=count()"

$feedbackFound = $false
for ($i = 1; $i -le $MaxAttempts; $i++) {
    Write-Host "Querying App Insights for feedback telemetry (attempt $i/$MaxAttempts)..."
    $result = az monitor app-insights query `
        --app $AppInsightsName `
        --resource-group $ResourceGroupName `
        --analytics-query "$feedbackKusto" `
        --only-show-errors `
        -o json | ConvertFrom-Json
    $hits = 0
    if ($result.tables -and $result.tables[0].rows -and $result.tables[0].rows.Count -gt 0) {
        try {
            $hits = [int]$result.tables[0].rows[0][0]
        }
        catch {
            $hits = 0
        }
    }
    if ($hits -gt 0) {
        $feedbackFound = $true
        break
    }
    Start-Sleep -Seconds $DelaySeconds
}

if (-not $feedbackFound) {
    Write-Error "Validation failed: feedback telemetry not found in Application Insights."
    exit 1
}

Write-Host "Validation passed: feedback recorded and telemetry emitted."
