param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$EnvFile = ".\\.env.dev"
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

if (-not $ResourceGroupName -or -not $Location -or -not $KeyVaultName -or -not $ContentSafetyName -or -not $ContentSafetyKeySecretName) {
    Write-Error "Missing required variables in vars file."
    exit 1
}
if (-not $SafetyTemplateHumanEscalateSecretName -or -not $SafetyTemplateRefuseSecretName) {
    Write-Error "Missing safety template secret names in vars file."
    exit 1
}

function Set-EnvVarInFile {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )
    if (-not (Test-Path $Path)) {
        Write-Error "Env file not found: $Path"
        exit 1
    }
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
    $content | Set-Content $Path
}

Write-Host "Ensuring Azure AI Content Safety resource exists..."
$prevErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$null = az cognitiveservices account show `
    --name $ContentSafetyName `
    --resource-group $ResourceGroupName `
    --only-show-errors 2>$null
$csExists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevErrorAction

if ($csExists) {
    Write-Host "Content Safety resource already exists."
} else {
    az cognitiveservices account create `
        --name $ContentSafetyName `
        --resource-group $ResourceGroupName `
        --kind ContentSafety `
        --sku S0 `
        --location $Location `
        --yes `
        --only-show-errors | Out-Null
}

$endpoint = $null
for ($i = 0; $i -lt 6 -and -not $endpoint; $i++) {
    Start-Sleep -Seconds 5
    $endpoint = az cognitiveservices account show `
        --name $ContentSafetyName `
        --resource-group $ResourceGroupName `
        --query properties.endpoint -o tsv 2>$null
    if ($endpoint) {
        break
    }
}
if (-not $endpoint) {
    Write-Error "Failed to resolve Content Safety endpoint."
    exit 1
}

$apiKey = az cognitiveservices account keys list `
    --name $ContentSafetyName `
    --resource-group $ResourceGroupName `
    --query key1 -o tsv 2>$null
if (-not $apiKey) {
    Write-Error "Failed to fetch Content Safety API key."
    exit 1
}

Write-Host "Seeding Content Safety key into Key Vault: $KeyVaultName"
az keyvault secret set `
    --vault-name $KeyVaultName `
    --name $ContentSafetyKeySecretName `
    --value $apiKey `
    --only-show-errors | Out-Null

$defaultHumanEscalate = @"
I'm really sorry you're feeling this way. You're not alone, and help is available.

If you feel like you might hurt yourself or are in immediate danger, please call your local emergency number. In the U.S., you can call or text 988 to reach the Suicide & Crisis Lifeline (24/7). If you're outside the U.S., I can help find local support resources.

If it helps, consider reaching out to someone you trust right now. I'm here to support you.
"@

$defaultRefuse = "I'm sorry, but I can't assist with that request."

Write-Host "Seeding safety response templates into Key Vault: $KeyVaultName"
$tempDir = Join-Path $env:TEMP "thain-safety-templates"
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
$humanFile = Join-Path $tempDir "human_escalate.txt"
$refuseFile = Join-Path $tempDir "refuse.txt"
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($humanFile, $defaultHumanEscalate, $utf8NoBom)
[System.IO.File]::WriteAllText($refuseFile, $defaultRefuse, $utf8NoBom)
az keyvault secret set `
    --vault-name $KeyVaultName `
    --name $SafetyTemplateHumanEscalateSecretName `
    --file $humanFile `
    --only-show-errors | Out-Null
az keyvault secret set `
    --vault-name $KeyVaultName `
    --name $SafetyTemplateRefuseSecretName `
    --file $refuseFile `
    --only-show-errors | Out-Null
Remove-Item -Force $humanFile, $refuseFile -ErrorAction SilentlyContinue

Write-Host "Updating $EnvFile with Content Safety config..."
Set-EnvVarInFile -Path $EnvFile -Name "AZURE_CONTENT_SAFETY_ENDPOINT" -Value $endpoint
Set-EnvVarInFile -Path $EnvFile -Name "KV_CONTENT_SAFETY_KEY_NAME" -Value $ContentSafetyKeySecretName
Set-EnvVarInFile -Path $EnvFile -Name "KV_SAFETY_TEMPLATE_HUMAN_ESCALATE_NAME" -Value $SafetyTemplateHumanEscalateSecretName
Set-EnvVarInFile -Path $EnvFile -Name "KV_SAFETY_TEMPLATE_REFUSE_NAME" -Value $SafetyTemplateRefuseSecretName
Set-EnvVarInFile -Path $EnvFile -Name "SAFETY_PROVIDER" -Value "auto"

if ($ContainerAppName) {
    Write-Host "Updating Container App env vars for Content Safety: $ContainerAppName"
    az containerapp update `
        --name $ContainerAppName `
        --resource-group $ResourceGroupName `
        --set-env-vars `
            AZURE_CONTENT_SAFETY_ENDPOINT=$endpoint `
            KV_CONTENT_SAFETY_KEY_NAME=$ContentSafetyKeySecretName `
            KV_SAFETY_TEMPLATE_HUMAN_ESCALATE_NAME=$SafetyTemplateHumanEscalateSecretName `
            KV_SAFETY_TEMPLATE_REFUSE_NAME=$SafetyTemplateRefuseSecretName `
            SAFETY_PROVIDER=auto `
        --only-show-errors | Out-Null
}

Write-Host "Content Safety provisioning complete."
