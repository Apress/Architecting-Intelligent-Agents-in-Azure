param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$EnvFile = ".\\.env.dev",
    [string]$BaseUrl
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

$callbackUrl = "$BaseUrl/approvals/callback"
$group = $ApprovalsGroupName
if ($group) {
    $groupMail = az ad group list `
        --filter "displayName eq '$group'" `
        --query "[0].mail" -o tsv
    if ($groupMail) {
        $group = $groupMail
    }
}

Write-Host "Updating approval configuration in $EnvFile"
Set-EnvVarInFile -Path $EnvFile -Name "ENABLE_WRITE_APPROVALS" -Value "true"
Set-EnvVarInFile -Path $EnvFile -Name "ENABLE_TICKETS" -Value "true"
Set-EnvVarInFile -Path $EnvFile -Name "ENABLE_NOTIFICATIONS" -Value "false"
Set-EnvVarInFile -Path $EnvFile -Name "APPROVALS_CONTAINER" -Value $ApprovalsContainerName
Set-EnvVarInFile -Path $EnvFile -Name "APPROVALS_GROUP" -Value $group
Set-EnvVarInFile -Path $EnvFile -Name "APPROVALS_CALLBACK_URL" -Value $callbackUrl
Set-EnvVarInFile -Path $EnvFile -Name "KV_APPROVALS_LOGIC_APP_URL_NAME" -Value $ApprovalsLogicAppUrlSecretName
Set-EnvVarInFile -Path $EnvFile -Name "KV_APPROVALS_CALLBACK_SECRET_NAME" -Value $ApprovalsCallbackSecretName
Set-EnvVarInFile -Path $EnvFile -Name "APPROVALS_TIMEOUT_SECONDS" -Value "90"
Set-EnvVarInFile -Path $EnvFile -Name "APPROVALS_EXPIRES_SECONDS" -Value "900"
Set-EnvVarInFile -Path $EnvFile -Name "APPROVALS_POLL_INTERVAL_SECONDS" -Value "2"
Set-EnvVarInFile -Path $EnvFile -Name "APPROVALS_MAX_POLL_INTERVAL_SECONDS" -Value "10"
Set-EnvVarInFile -Path $EnvFile -Name "APPROVALS_TTL_DAYS" -Value "30"

Write-Host "Sprint 6 configuration complete."
