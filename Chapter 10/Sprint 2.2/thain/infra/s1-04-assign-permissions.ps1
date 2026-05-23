param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [Parameter(Mandatory = $true)]
    [string]$ScopeResourceId,
    [string[]]$RoleNames = @("Azure AI Developer", "Azure AI Project Manager")
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

if (-not $ResourceGroupName -or -not $ContainerAppName) {
    Write-Error "Missing required variables in vars file."
    exit 1
}

$principalId = az containerapp show --name $ContainerAppName --resource-group $ResourceGroupName --query identity.principalId -o tsv
if (-not $principalId) {
    Write-Error "Container App managed identity not found. Ensure the app is deployed with --system-assigned."
    exit 1
}

Write-Host "Using Container App principal ID: $principalId"

foreach ($roleName in $RoleNames) {
    $existing = az role assignment list --assignee-object-id $principalId --scope $ScopeResourceId --role $roleName -o tsv
    if ($existing) {
        Write-Host "Role assignment already exists for $roleName on scope."
        continue
    }

    Write-Host "Assigning role '$roleName' to principal $principalId on scope:"
    Write-Host "  $ScopeResourceId"

    az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal --role $roleName --scope $ScopeResourceId --only-show-errors | Out-Null
}

Write-Host "Role assignment complete."
