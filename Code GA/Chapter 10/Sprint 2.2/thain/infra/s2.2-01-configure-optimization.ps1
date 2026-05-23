param(
    [string]$EnvFile = ".\\.env.dev",
    [string]$ModelProfile = "standard",
    [switch]$EnableCache,
    [int]$CacheTtlSeconds = 120,
    [int]$CacheMaxEntries = 200,
    [int]$SummaryMaxChars = 300,
    [int]$SuggestMaxChars = 520
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

$profile = ($ModelProfile.Trim().ToLowerInvariant())
if (-not $profile) {
    $profile = "standard"
}

$cacheEnabled = if ($PSBoundParameters.ContainsKey("EnableCache")) {
    $EnableCache.IsPresent
} else {
    $true
}

Set-EnvVarInFile -Path $EnvFile -Name "THAIN_MODEL_PROFILE" -Value $profile
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_ENABLE_RESPONSE_COMPACTION" -Value "true"
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_RESPONSE_SUMMARY_MAX_CHARS" -Value ([string]([math]::Max($SummaryMaxChars, 80)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_RESPONSE_SUGGEST_MAX_CHARS" -Value ([string]([math]::Max($SuggestMaxChars, 160)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_ENABLE_CACHE" -Value ($cacheEnabled.ToString().ToLowerInvariant())
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_CACHE_TTL_SECONDS" -Value ([string]([math]::Max($CacheTtlSeconds, 10)))
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_CACHE_MAX_ENTRIES" -Value ([string]([math]::Max($CacheMaxEntries, 20)))

Write-Host "Sprint 2.2 optimization settings written to $EnvFile"
Write-Host "  THAIN_MODEL_PROFILE=$profile"
Write-Host "  THAIN_ENABLE_RESPONSE_COMPACTION=true"
Write-Host ("  THAIN_RESPONSE_SUMMARY_MAX_CHARS={0}" -f [math]::Max($SummaryMaxChars, 80))
Write-Host ("  THAIN_RESPONSE_SUGGEST_MAX_CHARS={0}" -f [math]::Max($SuggestMaxChars, 160))
Write-Host ("  THAIN_ENABLE_CACHE={0}" -f ($cacheEnabled.ToString().ToLowerInvariant()))
Write-Host ("  THAIN_CACHE_TTL_SECONDS={0}" -f [math]::Max($CacheTtlSeconds, 10))
Write-Host ("  THAIN_CACHE_MAX_ENTRIES={0}" -f [math]::Max($CacheMaxEntries, 20))
Write-Host ""
Write-Host "Note: cache is local to each container replica and does not persist across restarts."
