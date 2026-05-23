param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$ImageTag,
    [string]$EnvFile = ".\\.env"
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

. $VarsFile

if (-not $ResourceGroupName -or -not $ContainerAppsEnvName -or -not $ContainerAppName -or -not $AcrName -or -not $ImageRepository -or -not $ContainerAppPort) {
    Write-Error "Missing required variables in vars file."
    exit 1
}

function Get-EnvVarsFromFile {
    param([string]$Path)
    $envVars = @()
    if (-not (Test-Path $Path)) {
        return $envVars
    }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }
        if ($line -notmatch "=") {
            return
        }
        $envVars += $line
    }
    return $envVars
}

if (-not $ImageTag) {
    $tagFile = ".\\infra\\.last_image_tag"
    if (-not (Test-Path $tagFile)) {
        Write-Error "ImageTag not provided and tag file not found: $tagFile"
        exit 1
    }
    $ImageTag = (Get-Content $tagFile -ErrorAction Stop).Trim()
    if (-not $ImageTag) {
        Write-Error "Tag file is empty: $tagFile"
        exit 1
    }
    Write-Host "Using image tag from ${tagFile}: $ImageTag"
}

$image = "$AcrName.azurecr.io/${ImageRepository}:$ImageTag"
$envVars = Get-EnvVarsFromFile -Path $EnvFile

try {
    $app = az containerapp show --name $ContainerAppName --resource-group $ResourceGroupName --only-show-errors 2>$null
} catch {
    $app = $null
}
if (-not $app) {
    Write-Host "Creating Container App: $ContainerAppName"
    az containerapp create `
        --name $ContainerAppName `
        --resource-group $ResourceGroupName `
        --environment $ContainerAppsEnvName `
        --image $image `
        --registry-server "$AcrName.azurecr.io" `
        --registry-identity system `
        --ingress external `
        --target-port $ContainerAppPort `
        --env-vars $envVars `
        --only-show-errors | Out-Null
} else {
    Write-Host "Updating Container App: $ContainerAppName"
    az containerapp update `
        --name $ContainerAppName `
        --resource-group $ResourceGroupName `
        --image $image `
        --set-env-vars $envVars `
        --only-show-errors | Out-Null
}

$acrId = az acr show --name $AcrName --resource-group $ResourceGroupName --query id -o tsv
$principalId = az containerapp show --name $ContainerAppName --resource-group $ResourceGroupName --query identity.principalId -o tsv
if ($principalId -and $acrId) {
    Write-Host "Assigning AcrPull role to Container App identity..."
    az role assignment create `
        --assignee $principalId `
        --role AcrPull `
        --scope $acrId `
        --only-show-errors 2>$null | Out-Null
}

Write-Host "Deployment complete."
