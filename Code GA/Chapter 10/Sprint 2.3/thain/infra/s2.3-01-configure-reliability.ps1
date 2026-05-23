param(
    [string]$EnvFile = ".\\.env.dev",
    [switch]$EnableReliability,
    [int]$RetryMaxAttempts = 3,
    [int]$RetryBaseDelayMs = 250,
    [int]$RetryMaxDelayMs = 2000,
    [double]$RetryJitterRatio = 0.2,
    [int]$DependencyCooldownSeconds = 30,
    [int]$DependencyFailureThreshold = 2,
    [int]$TimeoutOpenAiMs = 45000,
    [int]$TimeoutSearchMs = 8000,
    [int]$TimeoutCosmosMs = 5000,
    [switch]$ChaosOpenAiFailure,
    [switch]$ChaosSearchFailure,
    [switch]$ChaosCosmosFailure,
    [double]$SloErrorRatePct = 5.0,
    [int]$SloErrorWindowMin = 15,
    [int]$SloP95LatencyMs = 30000,
    [int]$SloP95WindowMin = 15,
    [int]$SloDependencyFailures = 3,
    [int]$SloDependencyWindowMin = 5
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $EnvFile)) {
    Write-Error "Env file not found: $EnvFile"
    exit 1
}

function Set-EnvVarInFile {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )
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
    $content | Set-Content $Path -Encoding ASCII
}

$reliabilityEnabled = if ($PSBoundParameters.ContainsKey("EnableReliability")) {
    $EnableReliability.IsPresent
} else {
    $true
}

Set-EnvVarInFile -Path $EnvFile -Name "THAIN_ENABLE_RELIABILITY" -Value ($reliabilityEnabled.ToString().ToLowerInvariant())
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_RETRY_MAX_ATTEMPTS" -Value ([string]([math]::Max($RetryMaxAttempts, 1)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_RETRY_BASE_DELAY_MS" -Value ([string]([math]::Max($RetryBaseDelayMs, 10)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_RETRY_MAX_DELAY_MS" -Value ([string]([math]::Max($RetryMaxDelayMs, 50)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_RETRY_JITTER_RATIO" -Value ([string]([math]::Max($RetryJitterRatio, 0.0)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_DEPENDENCY_COOLDOWN_SECONDS" -Value ([string]([math]::Max($DependencyCooldownSeconds, 1)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_DEPENDENCY_FAILURE_THRESHOLD" -Value ([string]([math]::Max($DependencyFailureThreshold, 1)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_TIMEOUT_OPENAI_MS" -Value ([string]([math]::Max($TimeoutOpenAiMs, 1000)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_TIMEOUT_SEARCH_MS" -Value ([string]([math]::Max($TimeoutSearchMs, 500)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_TIMEOUT_COSMOS_MS" -Value ([string]([math]::Max($TimeoutCosmosMs, 500)))

Set-EnvVarInFile -Path $EnvFile -Name "THAIN_CHAOS_SIMULATE_OPENAI_FAILURE" -Value ($ChaosOpenAiFailure.IsPresent.ToString().ToLowerInvariant())
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_CHAOS_SIMULATE_SEARCH_FAILURE" -Value ($ChaosSearchFailure.IsPresent.ToString().ToLowerInvariant())
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_CHAOS_SIMULATE_COSMOS_FAILURE" -Value ($ChaosCosmosFailure.IsPresent.ToString().ToLowerInvariant())

Set-EnvVarInFile -Path $EnvFile -Name "THAIN_SLO_ERROR_RATE_PCT" -Value ([string]([math]::Max($SloErrorRatePct, 0.1)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_SLO_ERROR_WINDOW_MIN" -Value ([string]([math]::Max($SloErrorWindowMin, 1)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_SLO_P95_LATENCY_MS" -Value ([string]([math]::Max($SloP95LatencyMs, 1000)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_SLO_P95_WINDOW_MIN" -Value ([string]([math]::Max($SloP95WindowMin, 1)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_SLO_DEP_FAILURE_COUNT" -Value ([string]([math]::Max($SloDependencyFailures, 1)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_SLO_DEP_FAILURE_WINDOW_MIN" -Value ([string]([math]::Max($SloDependencyWindowMin, 1)))

Write-Host "Sprint 2.3 reliability settings written to $EnvFile"
Write-Host "  THAIN_ENABLE_RELIABILITY=$($reliabilityEnabled.ToString().ToLowerInvariant())"
Write-Host "  THAIN_RETRY_MAX_ATTEMPTS=$RetryMaxAttempts"
Write-Host "  THAIN_RETRY_BASE_DELAY_MS=$RetryBaseDelayMs"
Write-Host "  THAIN_RETRY_MAX_DELAY_MS=$RetryMaxDelayMs"
Write-Host "  THAIN_RETRY_JITTER_RATIO=$RetryJitterRatio"
Write-Host "  THAIN_DEPENDENCY_COOLDOWN_SECONDS=$DependencyCooldownSeconds"
Write-Host "  THAIN_DEPENDENCY_FAILURE_THRESHOLD=$DependencyFailureThreshold"
Write-Host "  THAIN_TIMEOUT_OPENAI_MS=$TimeoutOpenAiMs"
Write-Host "  THAIN_TIMEOUT_SEARCH_MS=$TimeoutSearchMs"
Write-Host "  THAIN_TIMEOUT_COSMOS_MS=$TimeoutCosmosMs"
Write-Host "  THAIN_CHAOS_SIMULATE_OPENAI_FAILURE=$($ChaosOpenAiFailure.IsPresent.ToString().ToLowerInvariant())"
Write-Host "  THAIN_CHAOS_SIMULATE_SEARCH_FAILURE=$($ChaosSearchFailure.IsPresent.ToString().ToLowerInvariant())"
Write-Host "  THAIN_CHAOS_SIMULATE_COSMOS_FAILURE=$($ChaosCosmosFailure.IsPresent.ToString().ToLowerInvariant())"
Write-Host "  THAIN_SLO_ERROR_RATE_PCT=$SloErrorRatePct"
Write-Host "  THAIN_SLO_ERROR_WINDOW_MIN=$SloErrorWindowMin"
Write-Host "  THAIN_SLO_P95_LATENCY_MS=$SloP95LatencyMs"
Write-Host "  THAIN_SLO_P95_WINDOW_MIN=$SloP95WindowMin"
Write-Host "  THAIN_SLO_DEP_FAILURE_COUNT=$SloDependencyFailures"
Write-Host "  THAIN_SLO_DEP_FAILURE_WINDOW_MIN=$SloDependencyWindowMin"
Write-Host ""
Write-Host "Note: chaos flags are deployment-time env vars; redeploy is required after changes."
