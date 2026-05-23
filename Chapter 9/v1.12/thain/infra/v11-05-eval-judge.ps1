param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$EnvFile,
    [string]$DataFile = ".\\infra\\data\\v11-eval-set.json",
    [string]$RunLabel = "baseline",
    [string]$CompareTo,
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

. $VarsFile

if (-not $EnvFile) {
    $defaultEnv = ".\\.env.dev"
    if (Test-Path $defaultEnv) {
        $EnvFile = $defaultEnv
    } else {
        $EnvFile = ".\\.env"
    }
}

if (-not (Test-Path $EnvFile)) {
    Write-Error "Env file not found: $EnvFile"
    exit 1
}

if (-not (Test-Path $DataFile)) {
    Write-Error "Eval data file not found: $DataFile"
    exit 1
}

function Import-EnvFile {
    param([string]$Path)
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }
        if ($line -notmatch "=") {
            return
        }
        $parts = $line.Split("=", 2)
        $name = $parts[0].Trim()
        $value = $parts[1]
        if ($name) {
            [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

Write-Host "Loading environment from $EnvFile"
Import-EnvFile -Path $EnvFile

if (-not $env:AZURE_OPENAI_EVAL_API_KEY) {
    $kvName = $env:KV_EVAL_OPENAI_API_KEY_NAME
    $kvUri = $env:KEY_VAULT_URI
    if ($kvName -and $kvUri) {
        try {
            $vaultName = ([System.Uri]$kvUri).Host.Split(".")[0]
            if ($vaultName) {
                $secretValue = az keyvault secret show `
                    --vault-name $vaultName `
                    --name $kvName `
                    --query value -o tsv
                if ($secretValue) {
                    $env:AZURE_OPENAI_EVAL_API_KEY = $secretValue
                }
            }
        } catch {
            Write-Warning "Unable to load eval API key from Key Vault; ensure KV_EVAL_OPENAI_API_KEY_NAME is valid."
        }
    }
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

$evalContainer = if ($env:EVAL_CONTAINER) { $env:EVAL_CONTAINER } else { $EvalContainerName }
if (-not $evalContainer) {
    $evalContainer = "thain-evals"
}

$cosmosDatabase = $env:COSMOS_DATABASE
if (-not $cosmosDatabase) {
    Write-Error "COSMOS_DATABASE not found in $EnvFile."
    exit 1
}

Write-Host "Ensuring Cosmos DB eval container: $evalContainer"
try {
    $userObjectId = az ad signed-in-user show --query id -o tsv 2>$null
} catch {
    $userObjectId = $null
}
if ($userObjectId) {
    $roleName = "Cosmos DB Built-in Data Contributor"
    $roleId = $null
    try {
        $roleId = az cosmosdb sql role definition list `
            --account-name $CosmosAccountName `
            --resource-group $ResourceGroupName `
            --query "[?roleName=='$roleName'].id | [0]" -o tsv
    } catch {
        $roleId = $null
    }
    if (-not $roleId) {
        Write-Error "Cosmos SQL data-plane role '$roleName' not found. Check Cosmos RBAC roles."
        exit 1
    }

    $scope = "/dbs/$cosmosDatabase/colls/$evalContainer"
    $existingRole = $null
    try {
        $existingRole = az cosmosdb sql role assignment list `
            --account-name $CosmosAccountName `
            --resource-group $ResourceGroupName `
            --query "[?principalId=='$userObjectId' && roleDefinitionId=='$roleId'] | [0].id" -o tsv
    } catch {
        $existingRole = $null
    }
    if (-not $existingRole) {
        Write-Host "Assigning $roleName to signed-in user for eval writes."
        az cosmosdb sql role assignment create `
            --account-name $CosmosAccountName `
            --resource-group $ResourceGroupName `
            --scope $scope `
            --principal-id $userObjectId `
            --role-definition-id $roleId `
            --only-show-errors | Out-Null
        Write-Host "Role assignment created. It may take a minute to propagate."
    } else {
        Write-Host "$roleName already assigned to signed-in user."
    }
}

$containerExists = $null
try {
    $containerExists = az cosmosdb sql container show `
        --account-name $CosmosAccountName `
        --resource-group $ResourceGroupName `
        --database-name $cosmosDatabase `
        --name $evalContainer `
        --query "id" -o tsv 2>$null
} catch {
    $containerExists = $null
}

if (-not $containerExists) {
    az cosmosdb sql container create `
        --account-name $CosmosAccountName `
        --resource-group $ResourceGroupName `
        --database-name $cosmosDatabase `
        --name $evalContainer `
        --partition-key-path "/run_label" `
        --only-show-errors | Out-Null
    Write-Host "Eval container created."
} else {
    Write-Host "Eval container already exists."
}

Write-Host "Running LLM-as-judge eval (run label: $RunLabel)"
$args = @(
    ".\\infra\\scripts\\v11_eval_judge.py",
    "--data-file", $DataFile,
    "--run-label", $RunLabel,
    "--base-url", $BaseUrl
)
if ($CompareTo) {
    $args += @("--compare-to", $CompareTo)
}

python @args
