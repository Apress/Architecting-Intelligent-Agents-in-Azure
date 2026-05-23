param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1"
)

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

if (-not $ResourceGroupName -or -not $ContainerAppName) {
    Write-Error "Missing required variables in vars file."
    exit 1
}

$fqdn = az containerapp show --name $ContainerAppName --resource-group $ResourceGroupName --query properties.configuration.ingress.fqdn -o tsv
if (-not $fqdn) {
    Write-Error "Container App FQDN not found."
    exit 1
}

$baseUrl = "https://$fqdn"
Write-Host "Validating $baseUrl"

try {
    $health = Invoke-RestMethod -Method Get -Uri "$baseUrl/health" -TimeoutSec 30
    if ($health.status -ne "ok") {
        throw "Health check failed."
    }
    Write-Host "Health check OK."
} catch {
    Write-Error "Health check failed: $_"
    exit 1
}

try {
    $payload = @{ message = "Wi-Fi keeps dropping across two sites." } | ConvertTo-Json
    $chat = Invoke-RestMethod -Method Post -Uri "$baseUrl/chat" -ContentType "application/json" -Body $payload -TimeoutSec 60
    if (-not $chat.response) {
        throw "Chat response missing."
    }
    Write-Host "Chat check OK."
} catch {
    Write-Error "Chat check failed: $_"
    exit 1
}
