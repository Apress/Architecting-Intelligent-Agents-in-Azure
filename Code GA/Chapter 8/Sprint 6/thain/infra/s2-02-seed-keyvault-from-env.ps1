param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$EnvFile = ".\\.env.dev",
    [string]$KeyVaultName,
    [string]$EmbeddingSecretName = "thain-embedding-api-key",
    [switch]$ScrubEnv = $true,
    [switch]$ConfigureContainerApp = $true
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
$KeyVaultNameParam = $KeyVaultName
if (-not $KeyVaultNameParam) {
    $KeyVaultNameParam = $KeyVaultName
}

if (-not $KeyVaultNameParam) {
    Write-Error "KeyVaultName not provided and not found in vars file."
    exit 1
}

$seederObjectId = $KeyVaultSeederObjectId
if (-not $seederObjectId) {
    try {
        $seederObjectId = az ad signed-in-user show --query id -o tsv
    } catch {
        $seederObjectId = $null
    }
}

if ($seederObjectId) {
    $kvScope = "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$ResourceGroupName/providers/Microsoft.KeyVault/vaults/$KeyVaultNameParam"
    $existingSeeder = az role assignment list `
        --assignee-object-id $seederObjectId `
        --scope $kvScope `
        --query "[?roleDefinitionName=='Key Vault Secrets Officer']" -o tsv
    if (-not $existingSeeder) {
        Write-Host "Assigning Key Vault Secrets Officer to seeder on scope:"
        Write-Host "  $kvScope"
        az role assignment create `
            --assignee-object-id $seederObjectId `
            --assignee-principal-type User `
            --role "Key Vault Secrets Officer" `
            --scope $kvScope `
            --only-show-errors | Out-Null
        Write-Host "Role assignment created. It may take a minute to propagate."
    }
}

$sourceEnv = ".\\.env"
if (-not (Test-Path $sourceEnv)) {
    Write-Error "Env file not found: $sourceEnv"
    exit 1
}
Copy-Item $sourceEnv $EnvFile -Force
Write-Host "Refreshed $EnvFile from $sourceEnv"

$secretMap = @{
    "AZURE_OPENAI_EMBEDDING_API_KEY" = $EmbeddingSecretName
    "AZURE_OPENAI_API_KEY" = "thain-openai-api-key"
}

$scrubOnlyKeys = @(
    "COSMOS_KEY",
    "AZURE_SEARCH_API_KEY"
)

$rawLines = Get-Content $EnvFile
$keptLines = New-Object System.Collections.Generic.List[string]
$seedFailures = $false

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

function Normalize-EnvVars {
    param([string[]]$Entries)
    $map = @{}
    foreach ($entry in $Entries) {
        $parts = $entry -split "=", 2
        if ($parts.Count -lt 2) { continue }
        $name = $parts[0].Trim()
        if (-not $name) { continue }
        $map[$name] = $entry
    }
    return $map.Values
}

foreach ($line in $rawLines) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#") -or $trimmed -notmatch "=") {
        $keptLines.Add($line)
        continue
    }
    $parts = $line.Split("=", 2)
    $name = $parts[0].Trim()
    $value = $parts[1]

    if ($secretMap.ContainsKey($name)) {
        $secretValue = $value.Trim()
        if ($secretValue) {
            $secretName = $secretMap[$name]
            Write-Host "Seeding Key Vault secret '$secretName' from $name..."
            try {
                az keyvault secret set --vault-name $KeyVaultNameParam --name $secretName --value $secretValue --only-show-errors | Out-Null
            } catch {
                Write-Error "Failed to seed Key Vault secret '$secretName'."
                $seedFailures = $true
            }
        }
        if ($ScrubEnv) {
            continue
        }
    }

    if ($ScrubEnv -and ($scrubOnlyKeys -contains $name)) {
        continue
    }

    $keptLines.Add($line)
}

if ($ScrubEnv -and -not $seedFailures) {
    $backup = "$EnvFile.bak"
    if (Test-Path $backup) {
        $stamp = Get-Date -Format "yyyyMMddHHmmss"
        $backup = "$EnvFile.bak.$stamp"
    }
    Copy-Item $EnvFile $backup
    $kvUri = "https://$KeyVaultNameParam.vault.azure.net/"
    $overrideLines = @("THAIN_AUTH_MODE=managed_identity", "KEY_VAULT_URI=$kvUri", "KV_EMBEDDING_API_KEY_NAME=$EmbeddingSecretName")
    $merged = Normalize-EnvVars -Entries ($keptLines + $overrideLines)
    Set-Content -Path $EnvFile -Value $merged -Encoding ascii
    Write-Host "Scrubbed secrets from $EnvFile (backup: $backup)"
}

if ($seedFailures) {
    Write-Error "Key Vault seeding failed. Secrets were not scrubbed."
    exit 1
}

Write-Host "Key Vault seeding complete."

if ($ConfigureContainerApp) {
    $kvUri = "https://$KeyVaultNameParam.vault.azure.net/"
    Write-Host "Configuring Container App env vars for managed identity..."

    $blockedKeys = @(
        "COSMOS_KEY",
        "AZURE_SEARCH_API_KEY",
        "AZURE_OPENAI_EMBEDDING_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZURE_CONTENT_SAFETY_API_KEY"
    )

    $envVars = Get-EnvVarsFromFile -Path $EnvFile
    $filtered = @()
    foreach ($entry in $envVars) {
        $parts = $entry -split "=", 2
        if ($parts.Count -lt 2) { continue }
        $name = $parts[0].Trim()
        if ($blockedKeys -contains $name) {
            continue
        }
        $filtered += $entry
    }

    $overrides = @("THAIN_AUTH_MODE=managed_identity")
    if ($kvUri) {
        $overrides += "KEY_VAULT_URI=$kvUri"
    }
    if ($EmbeddingSecretName) {
        $overrides += "KV_EMBEDDING_API_KEY_NAME=$EmbeddingSecretName"
    }

    $finalEnv = Normalize-EnvVars -Entries ($filtered + $overrides)

    az containerapp update `
        --name $ContainerAppName `
        --resource-group $ResourceGroupName `
        --remove-env-vars "COSMOS_KEY" "AZURE_SEARCH_API_KEY" "AZURE_OPENAI_EMBEDDING_API_KEY" "AZURE_OPENAI_API_KEY" `
        --only-show-errors | Out-Null

    az containerapp update `
        --name $ContainerAppName `
        --resource-group $ResourceGroupName `
        --set-env-vars $finalEnv `
        --only-show-errors | Out-Null
    Write-Host "Container App env configuration complete."
}
