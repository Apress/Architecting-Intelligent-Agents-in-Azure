param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$DevUrl,
    [string]$StageUrl
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $VarsFile)) {
    Write-Error "Vars file not found: $VarsFile"
    exit 1
}

. $VarsFile

function Resolve-AppUrl {
    param([string]$AppName)
    $url = az containerapp show --name $AppName --resource-group $ResourceGroupName --query properties.configuration.ingress.fqdn -o tsv
    if (-not $url) {
        return $null
    }
    return "https://$url"
}

function Validate-ManagedIdentityConfig {
    param([string]$AppName)
    $envs = az containerapp show --name $AppName --resource-group $ResourceGroupName --query "properties.template.containers[0].env" -o json | ConvertFrom-Json
    $authMode = ($envs | Where-Object { $_.name -eq "THAIN_AUTH_MODE" }).value
    if ($authMode -ne "managed_identity") {
        Write-Error "THAIN_AUTH_MODE is not managed_identity for $AppName."
        exit 1
    }
    $blocked = @("COSMOS_KEY","AZURE_SEARCH_API_KEY","AZURE_OPENAI_EMBEDDING_API_KEY","AZURE_OPENAI_API_KEY","AZURE_CONTENT_SAFETY_API_KEY")
    $found = $envs | Where-Object { $blocked -contains $_.name }
    if ($found) {
        $names = ($found | ForEach-Object { $_.name }) -join ", "
        Write-Error "Embedded secrets still present in $AppName env: $names"
        exit 1
    }
    Write-Host "Managed Identity config OK for $AppName"
}

function Get-SearchMode {
    param([string]$AppName)
    $envs = az containerapp show --name $AppName --resource-group $ResourceGroupName --query "properties.template.containers[0].env" -o json | ConvertFrom-Json
    $mode = ($envs | Where-Object { $_.name -eq "AZURE_SEARCH_MODE" }).value
    if (-not $mode) { $mode = "semantic" }
    return $mode.ToLower()
}

function Invoke-Chat {
    param([string]$BaseUrl, [string]$Message)
    $payload = @{ message = $Message } | ConvertTo-Json
    try {
        return Invoke-RestMethod -Method Post -Uri "$BaseUrl/chat" -ContentType "application/json" -Body $payload -TimeoutSec 120
    } catch {
        throw
    }
}

if (-not $DevUrl) {
    $DevUrl = Resolve-AppUrl -AppName $ContainerAppName
}
if (-not $StageUrl) {
    $StageUrl = Resolve-AppUrl -AppName $ContainerAppStageName
}

if (-not $DevUrl) {
    Write-Error "Dev Container App URL not found."
    exit 1
}
if (-not $StageUrl) {
    Write-Error "Stage Container App URL not found."
    exit 1
}

Write-Host "Validating Dev: $DevUrl"
Validate-ManagedIdentityConfig -AppName $ContainerAppName
.\infra\s1-05-validate.ps1 -BaseUrl $DevUrl
$devSearchMode = Get-SearchMode -AppName $ContainerAppName
Invoke-Chat -BaseUrl $DevUrl -Message "Check prior complaints for recurring Wi-Fi drops." | Out-Null
if ($devSearchMode -ne "off") {
    Invoke-Chat -BaseUrl $DevUrl -Message "Do we have a troubleshooting procedure for Wi-Fi drops?" | Out-Null
}

Write-Host "Validating Stage: $StageUrl"
Validate-ManagedIdentityConfig -AppName $ContainerAppStageName
.\infra\s1-05-validate.ps1 -BaseUrl $StageUrl
$stageSearchMode = Get-SearchMode -AppName $ContainerAppStageName
Invoke-Chat -BaseUrl $StageUrl -Message "Check prior complaints for recurring Wi-Fi drops." | Out-Null
if ($stageSearchMode -ne "off") {
    Invoke-Chat -BaseUrl $StageUrl -Message "Do we have a troubleshooting procedure for Wi-Fi drops?" | Out-Null
}

Write-Host "Dev and Stage validation complete."
