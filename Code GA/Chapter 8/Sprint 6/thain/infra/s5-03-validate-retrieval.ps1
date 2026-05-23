param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$EnvFile,
    [string]$BaseUrl,
    [int]$MaxAttempts = 8,
    [int]$DelaySeconds = 10,
    [int]$WindowMinutes = 20
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "python not found. Activate your environment first."
    exit 1
}

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

if (-not $EnvFile) {
    $defaultEnv = ".\\.env.dev"
    if (Test-Path $defaultEnv) {
        $EnvFile = $defaultEnv
    } else {
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

function Invoke-Chat {
    param(
        [string]$Prompt
    )
    $payload = @{ message = $Prompt } | ConvertTo-Json -Depth 3
    return Invoke-RestMethod -Method Post -Uri "$BaseUrl/chat" -ContentType "application/json" -Body $payload
}

Write-Host "Loading environment from $EnvFile"
Import-EnvFile -Path $EnvFile

Write-Host "Running retrieval contract checks against Azure AI Search..."
python .\infra\scripts\s5_validate_retrieval.py
if ($LASTEXITCODE -ne 0) {
    Write-Error "Retrieval contract validation failed."
    exit $LASTEXITCODE
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

$prompt = "Wi-Fi is dropping across two sites. Please provide a triage summary and include the standard procedure."
Write-Host "Running /chat retrieval smoke test via $BaseUrl"
$response = Invoke-Chat -Prompt $prompt
if (-not $response.trace_id) {
    Write-Error "Validation failed: /chat response did not return trace_id."
    exit 1
}

$traceId = $response.trace_id
Write-Host "Trace ID: $traceId"

if (-not $AppInsightsName -or -not $ResourceGroupName) {
    Write-Host "AppInsightsName/ResourceGroupName missing in vars file; skipping telemetry lookup."
    Write-Host "Retrieval validation OK (service + /chat smoke)."
    exit 0
}

$kusto = "union traces, dependencies, requests | where timestamp > ago(${WindowMinutes}m) | where tostring(customDimensions['thain.trace_id']) == '$traceId' | summarize hits=count()"
    $docsKusto = "dependencies | where timestamp > ago(${WindowMinutes}m) | where tostring(customDimensions['thain.trace_id']) == '$traceId' | where tostring(customDimensions['thain.tool.names']) has 'retrieve_docs' | summarize hits=count()"

$found = $false
for ($i = 1; $i -le $MaxAttempts; $i++) {
    Write-Host "Querying App Insights for retrieval trace (attempt $i/$MaxAttempts)..."
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
    Write-Error "Validation failed: retrieval smoke trace not found in App Insights."
    exit 1
}

$docsFound = $false
for ($i = 1; $i -le $MaxAttempts; $i++) {
    Write-Host "Querying App Insights for retrieve_docs signal (attempt $i/$MaxAttempts)..."
    $docsResult = az monitor app-insights query `
        --app $AppInsightsName `
        --resource-group $ResourceGroupName `
        --analytics-query "$docsKusto" `
        --only-show-errors `
        -o json | ConvertFrom-Json

    $docsHits = 0
    if ($docsResult.tables -and $docsResult.tables[0].rows -and $docsResult.tables[0].rows.Count -gt 0) {
        try {
            $docsHits = [int]$docsResult.tables[0].rows[0][0]
        } catch {
            $docsHits = 0
        }
    }

    if ($docsHits -gt 0) {
        $docsFound = $true
        break
    }
    Start-Sleep -Seconds $DelaySeconds
}

if (-not $docsFound) {
    Write-Error "Validation failed: retrieve_docs signal not found in App Insights."
    exit 1
}

Write-Host "Retrieval validation OK."
