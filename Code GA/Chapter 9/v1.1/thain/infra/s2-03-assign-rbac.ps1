param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$FoundryProjectScope,
    [string]$FoundryAccountScope
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

$FoundryProjectResourceIdFromConfig = $FoundryProjectResourceId
$FoundryAccountResourceIdFromConfig = $FoundryAccountResourceId

$FoundryProjectResourceId = if ($FoundryProjectScope) { $FoundryProjectScope } else { $FoundryProjectResourceIdFromConfig }
$FoundryAccountResourceId = if ($FoundryAccountScope) { $FoundryAccountScope } else { $FoundryAccountResourceIdFromConfig }

function Get-ResourceId {
    param(
        [string]$Type,
        [string]$Name
    )
    if (-not $Name) {
        return $null
    }
    return az resource show `
        --resource-group $ResourceGroupName `
        --name $Name `
        --resource-type $Type `
        --query id -o tsv
}

function Get-PrincipalId {
    param([string]$AppName)
    try {
        return az containerapp show --name $AppName --resource-group $ResourceGroupName --query identity.principalId -o tsv
    } catch {
        return $null
    }
}

$principalId = Get-PrincipalId -AppName $ContainerAppName
if (-not $principalId) {
    Write-Error "Dev Container App not found or has no identity: $ContainerAppName"
    exit 1
}


$cosmosId = Get-ResourceId -Type "Microsoft.DocumentDB/databaseAccounts" -Name $CosmosAccountName
$searchId = Get-ResourceId -Type "Microsoft.Search/searchServices" -Name $SearchServiceName
$keyVaultId = Get-ResourceId -Type "Microsoft.KeyVault/vaults" -Name $KeyVaultName
$storageId = Get-ResourceId -Type "Microsoft.Storage/storageAccounts" -Name $StorageAccountName

function Ensure-Role {
    param(
        [string]$RoleName,
        [string]$Scope,
        [string]$PrincipalId
    )
    if (-not $RoleName -or -not $Scope -or -not $PrincipalId) {
        return
    }
    $roleId = az role definition list --name $RoleName --query "[0].id" -o tsv
    if (-not $roleId) {
        Write-Warning "Role '$RoleName' not found in this subscription. Skipping assignment."
        return
    }
    $existing = az role assignment list `
        --assignee-object-id $PrincipalId `
        --scope $Scope `
        --query "[?roleDefinitionId=='$roleId']" -o tsv
    if ($existing) {
        Write-Host "Role '$RoleName' already assigned on $Scope for principal $PrincipalId"
        return
    }
    Write-Host "Assigning role '$RoleName' on scope:"
    Write-Host "  $Scope"
    az role assignment create `
        --assignee-object-id $PrincipalId `
        --assignee-principal-type ServicePrincipal `
        --role $roleId `
        --scope $Scope `
        --only-show-errors | Out-Null
}

if ($FoundryProjectResourceId) {
    Ensure-Role -RoleName "Azure AI Developer" -Scope $FoundryProjectResourceId -PrincipalId $principalId
    Ensure-Role -RoleName "Azure AI Project Manager" -Scope $FoundryProjectResourceId -PrincipalId $principalId
}
if ($FoundryAccountResourceId) {
    Ensure-Role -RoleName "Azure AI Developer" -Scope $FoundryAccountResourceId -PrincipalId $principalId
}

if ($cosmosId) {
    $cosmosDataRoleId = az cosmosdb sql role definition list `
        --account-name $CosmosAccountName `
        --resource-group $ResourceGroupName `
        --query "[?roleName=='Cosmos DB Built-in Data Contributor'].id" -o tsv
    if ($cosmosDataRoleId) {
        $existingCosmos = az cosmosdb sql role assignment list `
            --account-name $CosmosAccountName `
            --resource-group $ResourceGroupName `
            --query "[?principalId=='$principalId' && roleDefinitionId=='$cosmosDataRoleId']" -o tsv
        if (-not $existingCosmos) {
            Write-Host "Assigning Cosmos data-plane role on account: $CosmosAccountName for principal $principalId"
            az cosmosdb sql role assignment create `
                --account-name $CosmosAccountName `
                --resource-group $ResourceGroupName `
                --principal-id $principalId `
                --role-definition-id $cosmosDataRoleId `
                --scope "/" `
                --only-show-errors | Out-Null
        } else {
            Write-Host "Cosmos data-plane role already assigned for principal $principalId."
        }
    } else {
        Write-Warning "Cosmos data-plane role not found. Skipping."
    }
}
if ($searchId) {
    Ensure-Role -RoleName "Search Index Data Contributor" -Scope $searchId -PrincipalId $principalId
}
if ($keyVaultId) {
    Ensure-Role -RoleName "Key Vault Secrets User" -Scope $keyVaultId -PrincipalId $principalId
}
if ($storageId) {
    Ensure-Role -RoleName "Storage Blob Data Contributor" -Scope $storageId -PrincipalId $principalId
}

Write-Host "Sprint 2 RBAC assignments complete."
