param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$ImageTag
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker not found. Install Docker Desktop first."
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

if (-not $AcrName -or -not $ImageRepository) {
    Write-Error "Missing required variables in vars file."
    exit 1
}

if (-not $ImageTag) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        $ImageTag = (Get-Date -Format "yyyyMMddHHmmss")
    }
    try {
        if (-not $ImageTag) {
            $ImageTag = (git rev-parse --short HEAD).Trim()
        }
    } catch {
        if (-not $ImageTag) {
            $ImageTag = (Get-Date -Format "yyyyMMddHHmmss")
        }
    }
}

$image = "$AcrName.azurecr.io/${ImageRepository}:$ImageTag"
$tagFile = ".\\infra\\.last_image_tag"

Set-Content -Path $tagFile -Value $ImageTag -Encoding ASCII
Write-Host "Recorded image tag: $ImageTag ($tagFile)"

Write-Host "Logging into ACR..."
az acr login --name $AcrName --only-show-errors | Out-Null

Write-Host "Building image: $image"
docker build -t $image .

Write-Host "Pushing image: $image"
docker push $image

Write-Host "Build and push complete."
