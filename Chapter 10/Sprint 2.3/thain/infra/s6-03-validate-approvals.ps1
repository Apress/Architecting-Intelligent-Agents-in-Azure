param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$EnvFile,
    [string]$BaseUrl,
    [int]$MaxAttempts = 6,
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

function Invoke-Chat {
    param([string]$Prompt)
    $payload = @{ message = $Prompt } | ConvertTo-Json -Depth 3
    return Invoke-RestMethod -Method Post -Uri "$BaseUrl/chat" -ContentType "application/json" -Body $payload
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

$approvalsGroup = $env:APPROVALS_GROUP
if ($approvalsGroup) {
    $group = az ad group list `
        --filter "displayName eq '$approvalsGroup' or mail eq '$approvalsGroup'" `
        --query "[0]" -o json 2>$null | ConvertFrom-Json
    if ($group -and $group.id) {
        $groupMail = $group.mail
        if ($groupMail) {
            Write-Host "Approval group email address: $groupMail"
        }
        else {
            Write-Warning "Approval group is not mail-enabled. Approval emails may not deliver."
        }
        $memberEmails = az ad group member list --group $group.id --query "[].mail" -o tsv 2>$null
        if (-not $memberEmails) {
            $memberEmails = az ad group member list --group $group.id --query "[].userPrincipalName" -o tsv 2>$null
        }
        if ($memberEmails) {
            $emails = ($memberEmails -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }) -join ", "
            Write-Host "Approval emails will be sent to: $emails"
        }
        else {
            Write-Warning "No mail addresses found for approval group members."
        }
    }
    elseif ($approvalsGroup -match "@") {
        Write-Host "Approval emails will be sent to: $approvalsGroup"
    }
    else {
        Write-Warning "Approval group not found in AAD: $approvalsGroup"
    }
}

$prompt = "Please create a ticket for repeated network outages at two sites."
Write-Host "Running /chat approval smoke test via $BaseUrl"
$response = Invoke-Chat -Prompt $prompt
if (-not $response.trace_id) {
    Write-Error "Validation failed: /chat response did not return trace_id."
    exit 1
}

$traceId = $response.trace_id
Write-Host "Trace ID: $traceId"

Write-Host "Resolving approval request..."
$approvalJson = python .\infra\scripts\s6_validate_approvals.py --trace-id $traceId --wait-seconds 0 --poll-interval 1
$approvalExit = $LASTEXITCODE
if ($approvalExit -notin @(0, 2)) {
    Write-Error "Approval validation failed. Status: $approvalJson"
    exit $approvalExit
}

try {
    $approval = $approvalJson | ConvertFrom-Json
}
catch {
    Write-Error "Approval validation returned unexpected output."
    exit 1
}

$approvalId = $approval.approval_id
Write-Host "Approval ID: $approvalId"

Start-Sleep -Seconds 30
Write-Host "Checking approval status via /chat..."
$statusResponse = Invoke-Chat -Prompt "status $approvalId"
if (-not $statusResponse.trace_id) {
    Write-Error "Status check failed: /chat did not return trace_id."
    exit 1
}
$statusTraceId = $statusResponse.trace_id
$statusText = $statusResponse.response
Write-Host "Status Trace ID: $statusTraceId"

if ($statusText -match "approved" -or $statusText -match "Ticket created" -or $statusText -match "Notification sent") {
    $finalStatus = "approved"
}
elseif ($statusText -match "denied" -or $statusText -match "expired") {
    $finalStatus = "denied"
}
else {
    $finalStatus = "pending"
}

if ($finalStatus -eq "pending") {
    Write-Host "Approval is still pending. No action has been executed. Re-check using: status $approvalId"
    exit 0
}

$shouldCheckTelemetry = $true
$expectToolTelemetry = $false
$expectedApprovalStatus = $finalStatus

if ($finalStatus -eq "approved") {
    Write-Host "Approval granted. Action execution confirmed by status response."
    $expectToolTelemetry = $true
} else {
    Write-Host "Approval was not granted (status: $finalStatus). The requested action was not executed."
}

if (-not $AppInsightsName -or -not $ResourceGroupName) {
    Write-Host "AppInsightsName/ResourceGroupName missing; skipping telemetry lookup."
    Write-Host "Validation partially complete: approval workflow is enforced. Telemetry lookup skipped due to missing App Insights configuration."
    exit 0
}

$approvalSignalKusto = "dependencies | where timestamp > ago(${WindowMinutes}m) | where name == 'thain.trace' | where tostring(customDimensions['thain.trace_id']) == '$statusTraceId' | where tostring(customDimensions['thain.approval.statuses']) has '$expectedApprovalStatus' | summarize hits=count()"
$toolKusto = "dependencies | where timestamp > ago(${WindowMinutes}m) | where name == 'thain.trace' | where tostring(customDimensions['thain.trace_id']) == '$statusTraceId' | where tostring(customDimensions['thain.tool.names']) has 'create_ticket' | summarize hits=count()"

$approvalFound = $false
for ($i = 1; $i -le $MaxAttempts; $i++) {
    Write-Host "Querying App Insights for approval signal (attempt $i/$MaxAttempts)..."
    $result = az monitor app-insights query `
        --app $AppInsightsName `
        --resource-group $ResourceGroupName `
        --analytics-query "$approvalSignalKusto" `
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
        $approvalFound = $true
        break
    }
    Start-Sleep -Seconds $DelaySeconds
}

if (-not $approvalFound) {
    Write-Error "Validation failed: approval telemetry was not found in Application Insights within the configured time window."
    exit 1
}
Write-Host "App Insights approval telemetry found (status: $expectedApprovalStatus)."

$toolFound = $false
if ($expectToolTelemetry) {
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        Write-Host "Querying App Insights for create_ticket tool (attempt $i/$MaxAttempts)..."
        $result = az monitor app-insights query `
            --app $AppInsightsName `
            --resource-group $ResourceGroupName `
            --analytics-query "$toolKusto" `
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
            $toolFound = $true
            break
        }
        Start-Sleep -Seconds $DelaySeconds
    }

    if (-not $toolFound) {
        Write-Error "Validation failed: create_ticket tool telemetry was not observed in Application Insights within the configured time window."
        exit 1
    }
    Write-Host "App Insights tool telemetry found (create_ticket)."
}
Write-Host "Validation passed: approval workflow is enforced and auditable (approval status + tool execution telemetry present)."
