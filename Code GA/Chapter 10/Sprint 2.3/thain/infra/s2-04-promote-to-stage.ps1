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

function Set-InfraConfigValue {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )
    $escaped = [regex]::Escape($Name)
    $content = Get-Content -Path $Path
    $updated = $false
    $content = $content | ForEach-Object {
        if ($_ -match "^\s*\$$escaped\s*=") {
            $updated = $true
            return "`$$Name = `"$Value`""
        }
        $_
    }
    if (-not $updated) {
        $content += "`$$Name = `"$Value`""
    }
    $content | Set-Content -Path $Path
}

if (-not $ContainerAppStageName) {
    $ContainerAppStageName = "$ContainerAppName-stage"
    Set-InfraConfigValue -Path $VarsFile -Name "ContainerAppStageName" -Value $ContainerAppStageName
    Write-Host "Set ContainerAppStageName in vars file: $ContainerAppStageName"
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

$blockedKeys = @(
    "COSMOS_KEY",
    "AZURE_SEARCH_API_KEY",
    "AZURE_OPENAI_EMBEDDING_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_CONTENT_SAFETY_API_KEY"
)

try {
    $app = az containerapp show --name $ContainerAppStageName --resource-group $ResourceGroupName --only-show-errors 2>$null
} catch {
    $app = $null
}

if (-not $app) {
    Write-Host "Creating Stage Container App: $ContainerAppStageName"
    az containerapp create `
        --name $ContainerAppStageName `
        --resource-group $ResourceGroupName `
        --environment $ContainerAppsEnvName `
        --image $image `
        --registry-server "$AcrName.azurecr.io" `
        --registry-identity system `
        --ingress external `
        --target-port $ContainerAppPort `
        --env-vars $envVars `
        --only-show-errors | Out-Null
    az containerapp update `
        --name $ContainerAppStageName `
        --resource-group $ResourceGroupName `
        --remove-env-vars $blockedKeys `
        --min-replicas 1 `
        --only-show-errors | Out-Null
} else {
    Write-Host "Updating Stage Container App: $ContainerAppStageName"
    az containerapp update `
        --name $ContainerAppStageName `
        --resource-group $ResourceGroupName `
        --remove-env-vars $blockedKeys `
        --min-replicas 1 `
        --only-show-errors | Out-Null
    az containerapp update `
        --name $ContainerAppStageName `
        --resource-group $ResourceGroupName `
        --image $image `
        --set-env-vars $envVars `
        --only-show-errors | Out-Null
}

$acrId = az acr show --name $AcrName --resource-group $ResourceGroupName --query id -o tsv
$principalId = az containerapp show --name $ContainerAppStageName --resource-group $ResourceGroupName --query identity.principalId -o tsv
if ($principalId -and $acrId) {
    Write-Host "Assigning AcrPull role to Stage Container App identity..."
    az role assignment create `
        --assignee $principalId `
        --role AcrPull `
        --scope $acrId `
        --only-show-errors 2>$null | Out-Null
}

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

$FoundryProjectResourceId = $FoundryProjectResourceId
$FoundryAccountResourceId = $FoundryAccountResourceId

$cosmosId = Get-ResourceId -Type "Microsoft.DocumentDB/databaseAccounts" -Name $CosmosAccountName
$searchId = Get-ResourceId -Type "Microsoft.Search/searchServices" -Name $SearchServiceName
$keyVaultId = Get-ResourceId -Type "Microsoft.KeyVault/vaults" -Name $KeyVaultName
$storageId = Get-ResourceId -Type "Microsoft.Storage/storageAccounts" -Name $StorageAccountName

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

Write-Host "Promotion to stage complete."
