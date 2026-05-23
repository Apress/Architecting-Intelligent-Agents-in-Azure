param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$EnvFile = ".\\.env.dev",
    [string]$DocsIndexName = "thain-kb-v1",
    [int]$DocsTopK = 3,
    [string]$SearchSku = "basic",
    [int]$SearchReplicaCount = 1,
    [int]$SearchPartitionCount = 1,
    [string]$SearchLocation,
    [switch]$SkipCreate
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

if (-not $ResourceGroupName -or -not $SearchServiceName -or -not $Location) {
    Write-Error "Missing ResourceGroupName, SearchServiceName, or Location in vars file."
    exit 1
}

if (-not $SearchLocation) {
    $SearchLocation = $Location
}

if (-not $PSBoundParameters.ContainsKey("DocsIndexName") -and $SearchDocsIndexName) {
    $DocsIndexName = $SearchDocsIndexName
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

function Ensure-ProviderRegistered {
    param([string]$Namespace)
    $state = az provider show --namespace $Namespace --query registrationState -o tsv 2>$null
    if ($state -ne "Registered") {
        Write-Host "Registering provider: $Namespace"
        az provider register --namespace $Namespace --only-show-errors | Out-Null
        $tries = 0
        do {
            Start-Sleep -Seconds 5
            $state = az provider show --namespace $Namespace --query registrationState -o tsv 2>$null
            $tries++
        } while ($state -ne "Registered" -and $tries -lt 24)
        if ($state -ne "Registered") {
            Write-Error "Provider registration timed out: $Namespace"
            exit 1
        }
    }
}

function Ensure-RoleAssignment {
    param(
        [string]$RoleName,
        [string]$Scope,
        [string]$PrincipalId,
        [string]$PrincipalType
    )
    if (-not $RoleName -or -not $Scope -or -not $PrincipalId) {
        return
    }
    $roleId = az role definition list --name $RoleName --query "[0].id" -o tsv
    if (-not $roleId) {
        Write-Warning "Role '$RoleName' not found. Skipping assignment."
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
        --assignee-principal-type $PrincipalType `
        --role $roleId `
        --scope $Scope `
        --only-show-errors | Out-Null
}

function Get-SearchEndpoint {
    param([string]$Name)
    $endpoint = az search service show `
        --name $Name `
        --resource-group $ResourceGroupName `
        --query "endpoint" `
        -o tsv `
        --only-show-errors 2>$null
    if ($endpoint) {
        return $endpoint
    }
    $endpoint = az resource show `
        --resource-group $ResourceGroupName `
        --resource-type "Microsoft.Search/searchServices" `
        --name $Name `
        --query "properties.endpoint" `
        -o tsv `
        --only-show-errors 2>$null
    if ($endpoint) {
        return $endpoint
    }
    $endpoint = az search service list `
        --resource-group $ResourceGroupName `
        --query "[?name=='$Name'].endpoint | [0]" `
        -o tsv `
        --only-show-errors 2>$null
    return $endpoint
}

Write-Host "Checking Azure AI Search service: $SearchServiceName"
$existingSearch = $null
$prevErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$existingSearch = az search service show `
    --name $SearchServiceName `
    --resource-group $ResourceGroupName `
    --only-show-errors 2>$null
$searchLookupExit = $LASTEXITCODE
$ErrorActionPreference = $prevErrorAction
if ($searchLookupExit -ne 0) {
    $existingSearch = $null
}

$searchExists = $false
if (-not $existingSearch) {
    $prevErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $count = az search service list `
        --resource-group $ResourceGroupName `
        --query "[?name=='$SearchServiceName'] | length(@)" `
        -o tsv 2>$null
    $listExit = $LASTEXITCODE
    $ErrorActionPreference = $prevErrorAction
    if ($listExit -eq 0) {
        try {
            $searchExists = ([int]$count -gt 0)
        } catch {
            $searchExists = $false
        }
    }
}

if (-not $existingSearch -and -not $searchExists) {
    if ($SkipCreate) {
        Write-Error "Azure AI Search service not found and -SkipCreate was specified."
        exit 1
    }
    Ensure-ProviderRegistered -Namespace "Microsoft.Search"
    Write-Host "Creating Azure AI Search service: $SearchServiceName"
    az search service create `
        --name $SearchServiceName `
        --resource-group $ResourceGroupName `
        --location $SearchLocation `
        --sku $SearchSku `
        --replica-count $SearchReplicaCount `
        --partition-count $SearchPartitionCount `
        --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create Azure AI Search service. Try another region or SKU."
        exit 1
    }
} else {
    Write-Host "Azure AI Search service already exists."
}

Write-Host "Ensuring Azure AI Search allows AAD authentication..."
az search service update `
    --name $SearchServiceName `
    --resource-group $ResourceGroupName `
    --auth-options aadOrApiKey `
    --aad-auth-failure-mode http403 `
    --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to enable AAD authentication on Azure AI Search."
    exit 1
}

$searchResourceId = az search service show `
    --name $SearchServiceName `
    --resource-group $ResourceGroupName `
    --query id -o tsv `
    --only-show-errors 2>$null

if ($searchResourceId) {
    $callerId = az ad signed-in-user show --query id -o tsv 2>$null
    if ($callerId) {
        Ensure-RoleAssignment `
            -RoleName "Search Index Data Contributor" `
            -Scope $searchResourceId `
            -PrincipalId $callerId `
            -PrincipalType "User"
    } else {
        Write-Warning "Unable to resolve signed-in user object id. Skipping RBAC assignment."
    }
}

$searchEndpoint = Get-SearchEndpoint -Name $SearchServiceName
if (-not $searchEndpoint) {
    Write-Error "Failed to resolve Azure AI Search endpoint. Run 'az search service show' to confirm the service is ready."
    exit 1
}

Write-Host "Updating retrieval env vars in $EnvFile"
Set-EnvVarInFile -Path $EnvFile -Name "ENABLE_DOCS" -Value "true"
Set-EnvVarInFile -Path $EnvFile -Name "AZURE_SEARCH_ENDPOINT" -Value $searchEndpoint
Set-EnvVarInFile -Path $EnvFile -Name "AZURE_SEARCH_DOCS_INDEX_NAME" -Value $DocsIndexName
Set-EnvVarInFile -Path $EnvFile -Name "AZURE_SEARCH_DOCS_TOP_K" -Value "$DocsTopK"

Write-Host "Sprint 5 retrieval provisioning complete."
