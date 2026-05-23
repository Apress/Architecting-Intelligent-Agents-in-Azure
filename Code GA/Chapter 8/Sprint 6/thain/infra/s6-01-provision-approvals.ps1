param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$EnvFile = ".\\.env.dev",
    [string]$ApprovalsLogicAppUrl,
    [string]$KeyVaultNameOverride,
    [string]$ApprovalsGroupNameOverride,
    [string]$ApprovalsContainerNameOverride,
    [string]$ApprovalsLogicAppUrlSecretNameOverride,
    [string]$ApprovalsCallbackSecretNameOverride,
    [string]$AcsCommunicationServiceNameOverride,
    [string]$AcsEmailServiceNameOverride,
    [string]$AcsEmailDomainNameOverride,
    [string]$AcsEmailSenderUsernameOverride,
    [string]$AcsDataLocationOverride
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

$KeyVaultNameParam = if ($KeyVaultNameOverride) { $KeyVaultNameOverride } else { $KeyVaultName }
$ApprovalsGroupParam = if ($ApprovalsGroupNameOverride) { $ApprovalsGroupNameOverride } else { $ApprovalsGroupName }
$ApprovalsContainerParam = if ($ApprovalsContainerNameOverride) { $ApprovalsContainerNameOverride } else { $ApprovalsContainerName }
$ApprovalsLogicAppSecretParam = if ($ApprovalsLogicAppUrlSecretNameOverride) { $ApprovalsLogicAppUrlSecretNameOverride } else { $ApprovalsLogicAppUrlSecretName }
$ApprovalsCallbackSecretParam = if ($ApprovalsCallbackSecretNameOverride) { $ApprovalsCallbackSecretNameOverride } else { $ApprovalsCallbackSecretName }
$AcsCommunicationServiceParam = if ($AcsCommunicationServiceNameOverride) { $AcsCommunicationServiceNameOverride } else { $AcsCommunicationServiceName }
$AcsEmailServiceParam = if ($AcsEmailServiceNameOverride) { $AcsEmailServiceNameOverride } else { $AcsEmailServiceName }
$AcsEmailDomainParam = if ($AcsEmailDomainNameOverride) { $AcsEmailDomainNameOverride } else { $AcsEmailDomainName }
$AcsEmailSenderUsernameParam = if ($AcsEmailSenderUsernameOverride) { $AcsEmailSenderUsernameOverride } else { $AcsEmailSenderUsername }
$AcsDataLocationParam = if ($AcsDataLocationOverride) { $AcsDataLocationOverride } else { $AcsDataLocation }

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

function Ensure-CommunicationExtension {
    $extension = $null
    try {
        $extension = az extension show -n communication -o json 2>$null | ConvertFrom-Json
    } catch {
        $extension = $null
    }
    if (-not $extension) {
        Write-Host "Installing Azure CLI communication extension..."
        az extension add -n communication --yes | Out-Null
    }
}

function Ensure-LogicAppWorkflow {
    param(
        [string]$WorkflowName,
        [string]$TemplatePath,
        [hashtable]$TemplateParams
    )
    if (-not $WorkflowName -or -not $TemplatePath) {
        return
    }
    $existing = $null
    try {
        $existing = az resource show `
            --resource-group $ResourceGroupName `
            --resource-type "Microsoft.Logic/workflows" `
            --name $WorkflowName `
            --query "name" -o tsv 2>$null
    } catch {
        $existing = $null
    }
    if ($existing) {
        Write-Host "Updating Logic App: $WorkflowName"
    }
    if (-not (Test-Path $TemplatePath)) {
        Write-Error "Logic App template not found: $TemplatePath"
        exit 1
    }
    $paramArgs = @()
    foreach ($key in $TemplateParams.Keys) {
        $paramArgs += "$key=$($TemplateParams[$key])"
    }
    Write-Host "Deploying Logic App: $WorkflowName"
    az deployment group create `
        --resource-group $ResourceGroupName `
        --template-file $TemplatePath `
        --parameters $paramArgs `
        --only-show-errors | Out-Null
}

function Get-LogicAppCallbackUrl {
    param([string]$WorkflowName)
    if (-not $WorkflowName) {
        return $null
    }
    $subscriptionId = az account show --query id -o tsv
    if (-not $subscriptionId) {
        return $null
    }
    $callbackUrlEndpoint = "https://management.azure.com/subscriptions/$subscriptionId/resourceGroups/$ResourceGroupName/providers/Microsoft.Logic/workflows/$WorkflowName/triggers/manual/listCallbackUrl?api-version=2019-05-01"
    $callbackUrl = az rest `
        --method post `
        --url $callbackUrlEndpoint `
        --query "value" -o tsv 2>$null
    return $callbackUrl
}

function Ensure-KvSecret {
    param(
        [string]$SecretName,
        [string]$SecretValue,
        [bool]$Force = $false
    )
    if (-not $SecretName) {
        return
    }
    if ($SecretValue) {
        $SecretValue = $SecretValue.Trim()
        $SecretValue = $SecretValue -replace "^\uFEFF", ""
    }
    $existing = $null
    try {
        $existing = az keyvault secret show `
            --vault-name $KeyVaultNameParam `
            --name $SecretName `
            --query "id" -o tsv 2>$null
    } catch {
        $existing = $null
    }
    if ($existing -and -not $Force) {
        return
    }
    $tempFile = [System.IO.Path]::GetTempFileName()
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($tempFile, $SecretValue, $utf8NoBom)
    try {
        az keyvault secret set `
            --vault-name $KeyVaultNameParam `
            --name $SecretName `
            --file $tempFile `
            --only-show-errors | Out-Null
    } finally {
        Remove-Item $tempFile -ErrorAction SilentlyContinue
    }
}

function Ensure-CosmosRoleAssignment {
    param(
        [string]$PrincipalId,
        [string]$RoleName
    )
    if (-not $PrincipalId -or -not $RoleName) {
        return
    }
    $roleId = $null
    try {
        $roleId = az cosmosdb sql role definition list `
            --account-name $CosmosAccountName `
            --resource-group $ResourceGroupName `
            --query "[?roleName=='$RoleName'].id | [0]" -o tsv --only-show-errors 2>$null
    } catch {
        $roleId = $null
    }
    if (-not $roleId) {
        Write-Warning "Cosmos role '$RoleName' not found; skipping assignment."
        return
    }
    $assignment = $null
    try {
        $assignment = az cosmosdb sql role assignment list `
            --account-name $CosmosAccountName `
            --resource-group $ResourceGroupName `
            --query "[?principalId=='$PrincipalId' && roleDefinitionId=='$roleId'].id | [0]" -o tsv --only-show-errors 2>$null
    } catch {
        $assignment = $null
    }
    if ($assignment) {
        return
    }
    az cosmosdb sql role assignment create `
        --account-name $CosmosAccountName `
        --resource-group $ResourceGroupName `
        --role-definition-id $roleId `
        --principal-id $PrincipalId `
        --scope "/" `
        --only-show-errors 2>$null | Out-Null
}

function Ensure-RoleAssignment {
    param(
        [string]$PrincipalId,
        [string]$RoleName,
        [string]$Scope
    )
    if (-not $PrincipalId -or -not $RoleName -or -not $Scope) {
        return
    }
    $existing = $null
    try {
        $existing = az role assignment list `
            --assignee $PrincipalId `
            --scope $Scope `
            --query "[?roleDefinitionName=='$RoleName'].id | [0]" -o tsv --only-show-errors 2>$null
    } catch {
        $existing = $null
    }
    if ($existing) {
        return
    }
    az role assignment create `
        --assignee $PrincipalId `
        --role $RoleName `
        --scope $Scope `
        --only-show-errors 2>$null | Out-Null
}

function Invoke-GraphRequest {
    param(
        [string]$Method,
        [string]$Url,
        [hashtable]$Body
    )
    $token = az account get-access-token `
        --resource "https://graph.microsoft.com/" `
        --query "accessToken" -o tsv 2>$null
    if (-not $token) {
        throw "Unable to acquire Microsoft Graph token."
    }
    $authHeader = "Authorization=Bearer $token"
    if ($Body) {
        $payload = $Body | ConvertTo-Json -Depth 8 -Compress
        $tempFile = [System.IO.Path]::GetTempFileName()
        $payload | Set-Content -Path $tempFile -Encoding UTF8
        try {
            return az rest `
                --method $Method `
                --url $Url `
                --headers $authHeader `
                --headers "Content-Type=application/json" `
                --body "@$tempFile" `
                -o json | ConvertFrom-Json
        } finally {
            Remove-Item $tempFile -ErrorAction SilentlyContinue
        }
    }
    return az rest `
        --method $Method `
        --url $Url `
        --headers $authHeader `
        --headers "Content-Type=application/json" `
        -o json | ConvertFrom-Json
}

function New-ApprovalsGroup {
    param(
        [string]$DisplayName,
        [string]$MailNickname
    )
    if (-not $DisplayName -or -not $MailNickname) {
        return $null
    }
    $body = @{
        displayName = $DisplayName
        mailEnabled = $true
        mailNickname = $MailNickname
        securityEnabled = $false
        groupTypes = @("Unified")
        visibility = "Private"
    }
    return Invoke-GraphRequest -Method "POST" -Url "https://graph.microsoft.com/v1.0/groups" -Body $body
}

function Get-ConnectionStringValue {
    param(
        [string]$ConnectionString,
        [string]$KeyName
    )
    if (-not $ConnectionString -or -not $KeyName) {
        return $null
    }
    $parts = $ConnectionString -split ";"
    foreach ($part in $parts) {
        $trimmed = $part.Trim()
        if ($trimmed -match "^(?i)$KeyName=") {
            return $trimmed.Split("=", 2)[1]
        }
    }
    return $null
}

Import-EnvFile -Path $EnvFile
$CosmosDatabaseName = $env:COSMOS_DATABASE
if (-not $CosmosDatabaseName) {
    Write-Error "COSMOS_DATABASE not found in $EnvFile."
    exit 1
}

if (-not $KeyVaultNameParam) {
    Write-Error "KeyVaultName not provided and not found in vars file."
    exit 1
}

if (-not $ApprovalsContainerParam) {
    Write-Error "ApprovalsContainerName not provided and not found in vars file."
    exit 1
}

if (-not $CosmosAccountName) {
    Write-Error "CosmosAccountName not found in vars file."
    exit 1
}

if (-not $ApprovalsLogicAppName) {
    Write-Error "ApprovalsLogicAppName not found in vars file."
    exit 1
}

if (-not $AcsCommunicationServiceParam -or -not $AcsEmailServiceParam -or -not $AcsEmailDomainParam) {
    Write-Error "ACS configuration missing in vars file (AcsCommunicationServiceName/AcsEmailServiceName/AcsEmailDomainName)."
    exit 1
}

if (-not $AcsEmailSenderUsernameParam) {
    $AcsEmailSenderUsernameParam = "approvals"
}

if (-not $AcsDataLocationParam) {
    $AcsDataLocationParam = "unitedstates"
}

# Azure-managed domains require the fixed name "AzureManagedDomain"
if ($AcsEmailDomainParam -ne "AzureManagedDomain") {
    Write-Warning "Overriding ACS email domain name to AzureManagedDomain for AzureManaged domains."
    $AcsEmailDomainParam = "AzureManagedDomain"
}

Ensure-CommunicationExtension

Write-Host "Ensuring Cosmos DB approvals container: $ApprovalsContainerParam"
$serverlessEnabled = 0
try {
    $serverlessEnabled = az cosmosdb show `
        --name $CosmosAccountName `
        --resource-group $ResourceGroupName `
        --query "length(capabilities[?name=='EnableServerless'])" `
        -o tsv 2>$null
} catch {
    $serverlessEnabled = 0
}
$useThroughput = $true
if ($serverlessEnabled -gt 0) {
    $useThroughput = $false
}
try {
    az cosmosdb sql database create `
        --account-name $CosmosAccountName `
        --resource-group $ResourceGroupName `
        --name $CosmosDatabaseName `
        --only-show-errors | Out-Null
} catch {
    Write-Warning "Failed to create Cosmos DB database; attempting to continue."
}

$containerExists = $null
try {
    $containerExists = az cosmosdb sql container show `
        --account-name $CosmosAccountName `
        --resource-group $ResourceGroupName `
        --database-name $CosmosDatabaseName `
        --name $ApprovalsContainerParam `
        --query "id" -o tsv 2>$null
} catch {
    $containerExists = $null
}

if (-not $containerExists) {
    $createArgs = @(
        "--account-name", $CosmosAccountName,
        "--resource-group", $ResourceGroupName,
        "--database-name", $CosmosDatabaseName,
        "--name", $ApprovalsContainerParam,
        "--partition-key-path", "/approval_id",
        "--only-show-errors"
    )
    $created = $false
    az cosmosdb sql container create @createArgs *> $null
    if ($LASTEXITCODE -eq 0) {
        $created = $true
    }
    if (-not $created -and $useThroughput) {
        $createWithThroughput = $createArgs + @("--throughput", "400")
        az cosmosdb sql container create @createWithThroughput *> $null
        if ($LASTEXITCODE -eq 0) {
            $created = $true
        }
    }
    Write-Host "Approvals container created."
} else {
    Write-Host "Approvals container already exists."
}

$signedInUserId = az ad signed-in-user show --query id -o tsv 2>$null
if ($signedInUserId) {
    Ensure-CosmosRoleAssignment -PrincipalId $signedInUserId -RoleName "Cosmos DB Built-in Data Reader"
}

if ($ApprovalsGroupParam) {
    $group = az ad group list `
        --filter "displayName eq '$ApprovalsGroupParam'" `
        --query "[0]" -o json | ConvertFrom-Json
    if (-not $group) {
        Write-Host "Creating approval group: $ApprovalsGroupParam"
        try {
            $mailNickname = $ApprovalsGroupParam.ToLower()
            $mailNickname = $mailNickname -replace "[^a-z0-9-]", "-"
            $mailNickname = $mailNickname.Trim("-")
            if (-not $mailNickname) {
                $mailNickname = "approvals-group"
            }
            $created = New-ApprovalsGroup -DisplayName $ApprovalsGroupParam -MailNickname $mailNickname
            if ($created -and $created.id) {
                $group = @{
                    id = $created.id
                    mail = $created.mail
                } | ConvertTo-Json -Compress | ConvertFrom-Json
            } else {
                Write-Warning "Failed to create approval group via Microsoft Graph."
            }
        } catch {
            Write-Warning "Failed to create AAD group. Create it manually: $ApprovalsGroupParam"
        }
    } else {
        Write-Host "Approval group already exists."
    }
    if ($group -and $group.id) {
        $userId = az ad signed-in-user show --query id -o tsv 2>$null
        if ($userId) {
            $alreadyMember = az ad group member check --group $group.id --member-id $userId --query "value" -o tsv 2>$null
            if ($alreadyMember -ne "true") {
                Write-Host "Adding signed-in user to approval group."
                az ad group member add --group $group.id --member-id $userId --only-show-errors | Out-Null
            }
        }
    }
}

Write-Host "Ensuring Azure Communication Email service: $AcsEmailServiceParam"
$emailServiceExists = $null
try {
    $emailServiceExists = az communication email show `
        --name $AcsEmailServiceParam `
        --resource-group $ResourceGroupName `
        --query "name" -o tsv --only-show-errors 2>$null
} catch {
    $emailServiceExists = $null
}
if (-not $emailServiceExists) {
    az communication email create `
        --name $AcsEmailServiceParam `
        --resource-group $ResourceGroupName `
        --location global `
        --data-location $AcsDataLocationParam `
        --only-show-errors 2>$null | Out-Null
}

Write-Host "Ensuring Azure Communication Email domain: $AcsEmailDomainParam"
$domainExists = $null
try {
    $domainExists = az communication email domain show `
        --domain-name $AcsEmailDomainParam `
        --email-service-name $AcsEmailServiceParam `
        --resource-group $ResourceGroupName `
        --query "name" -o tsv --only-show-errors 2>$null
} catch {
    $domainExists = $null
}
if (-not $domainExists) {
    az communication email domain create `
        --domain-name $AcsEmailDomainParam `
        --email-service-name $AcsEmailServiceParam `
        --resource-group $ResourceGroupName `
        --location global `
        --domain-management AzureManaged `
        --user-engmnt-tracking Disabled `
        --only-show-errors 2>$null | Out-Null
}

Write-Host "Ensuring ACS sender username: $AcsEmailSenderUsernameParam"
$senderExists = $null
try {
    $senderExists = az communication email domain sender-username show `
        --domain-name $AcsEmailDomainParam `
        --email-service-name $AcsEmailServiceParam `
        --resource-group $ResourceGroupName `
        --sender-username $AcsEmailSenderUsernameParam `
        --query "name" -o tsv --only-show-errors 2>$null
} catch {
    $senderExists = $null
}
if (-not $senderExists) {
    az communication email domain sender-username create `
        --domain-name $AcsEmailDomainParam `
        --email-service-name $AcsEmailServiceParam `
        --resource-group $ResourceGroupName `
        --sender-username $AcsEmailSenderUsernameParam `
        --username $AcsEmailSenderUsernameParam `
        --display-name "Thain Approvals" `
        --only-show-errors 2>$null | Out-Null
}

$domainId = $null
try {
    $domainId = az communication email domain show `
        --domain-name $AcsEmailDomainParam `
        --email-service-name $AcsEmailServiceParam `
        --resource-group $ResourceGroupName `
        --query "id" -o tsv --only-show-errors 2>$null
} catch {
    $domainId = $null
}
if (-not $domainId) {
    Write-Error "Unable to resolve ACS email domain resource ID."
    exit 1
}

Write-Host "Ensuring Azure Communication Service: $AcsCommunicationServiceParam"
$commExists = $null
try {
    $commExists = az communication show `
        --name $AcsCommunicationServiceParam `
        --resource-group $ResourceGroupName `
        --query "name" -o tsv --only-show-errors 2>$null
} catch {
    $commExists = $null
}
if (-not $commExists) {
    $commLocation = "global"
    az communication create `
        --name $AcsCommunicationServiceParam `
        --resource-group $ResourceGroupName `
        --location $commLocation `
        --data-location $AcsDataLocationParam `
        --linked-domains $domainId `
        --only-show-errors 2>$null | Out-Null
} else {
    $linked = az communication show `
        --name $AcsCommunicationServiceParam `
        --resource-group $ResourceGroupName `
        --query "linkedDomains" -o tsv --only-show-errors 2>$null
    if (-not $linked -or $linked -notmatch [regex]::Escape($domainId)) {
        az communication update `
            --name $AcsCommunicationServiceParam `
            --resource-group $ResourceGroupName `
            --linked-domains $domainId `
            --only-show-errors 2>$null | Out-Null
    }
}

$acsConnectionString = $null
try {
    $acsConnectionString = az communication list-key `
        --name $AcsCommunicationServiceParam `
        --resource-group $ResourceGroupName `
        --query "primaryConnectionString" -o tsv --only-show-errors 2>$null
} catch {
    $acsConnectionString = $null
}
if (-not $acsConnectionString) {
    Write-Error "Unable to resolve ACS connection string."
    exit 1
}

$acsEndpoint = Get-ConnectionStringValue -ConnectionString $acsConnectionString -KeyName "endpoint"
if (-not $acsEndpoint) {
    Write-Error "Unable to parse ACS endpoint."
    exit 1
}
$acsEndpoint = $acsEndpoint.TrimEnd("/")

$senderDomain = $null
try {
    $senderDomain = az communication email domain show `
        --domain-name $AcsEmailDomainParam `
        --email-service-name $AcsEmailServiceParam `
        --resource-group $ResourceGroupName `
        --query "mailFromSenderDomain" -o tsv --only-show-errors 2>$null
} catch {
    $senderDomain = $null
}
if (-not $senderDomain) {
    try {
        $senderDomain = az communication email domain show `
            --domain-name $AcsEmailDomainParam `
            --email-service-name $AcsEmailServiceParam `
            --resource-group $ResourceGroupName `
            --query "fromSenderDomain" -o tsv --only-show-errors 2>$null
    } catch {
        $senderDomain = $null
    }
}
if (-not $senderDomain) {
    try {
        $senderDomain = az communication email domain show `
            --domain-name $AcsEmailDomainParam `
            --email-service-name $AcsEmailServiceParam `
            --resource-group $ResourceGroupName `
            --query "properties.mailFromSenderDomain" -o tsv --only-show-errors 2>$null
    } catch {
        $senderDomain = $null
    }
}
if (-not $senderDomain) {
    try {
        $senderDomain = az communication email domain show `
            --domain-name $AcsEmailDomainParam `
            --email-service-name $AcsEmailServiceParam `
            --resource-group $ResourceGroupName `
            --query "properties.domainName" -o tsv --only-show-errors 2>$null
    } catch {
        $senderDomain = $null
    }
}
if (-not $senderDomain) {
    Write-Error "Unable to resolve ACS sender domain."
    exit 1
}

$acsSenderAddress = "$AcsEmailSenderUsernameParam@$senderDomain"

$approvalsTemplate = ".\\infra\\templates\\logicapp-approvals.json"

if (-not $ApprovalsLogicAppUrl -and $ApprovalsLogicAppName) {
    $approvalsParams = @{
        workflowName = $ApprovalsLogicAppName
        location = $Location
        acsEndpoint = $acsEndpoint
        acsSenderAddress = $acsSenderAddress
    }
    Ensure-LogicAppWorkflow -WorkflowName $ApprovalsLogicAppName -TemplatePath $approvalsTemplate -TemplateParams $approvalsParams
    $ApprovalsLogicAppUrl = Get-LogicAppCallbackUrl -WorkflowName $ApprovalsLogicAppName
    if ($ApprovalsLogicAppUrl) {
        Write-Host "Resolved approvals Logic App trigger URL."
    } else {
        Write-Warning "Failed to resolve approvals Logic App trigger URL."
    }
}

$logicAppPrincipalId = $null
try {
    $logicAppPrincipalId = az resource show `
        --resource-group $ResourceGroupName `
        --resource-type "Microsoft.Logic/workflows" `
        --name $ApprovalsLogicAppName `
        --query "identity.principalId" -o tsv --only-show-errors 2>$null
} catch {
    $logicAppPrincipalId = $null
}

$acsId = $null
try {
    $acsId = az communication show `
        --name $AcsCommunicationServiceParam `
        --resource-group $ResourceGroupName `
        --query "id" -o tsv --only-show-errors 2>$null
} catch {
    $acsId = $null
}

if ($logicAppPrincipalId -and $acsId) {
    Ensure-RoleAssignment -PrincipalId $logicAppPrincipalId -RoleName "Communication and Email Service Owner" -Scope $acsId
} elseif (-not $logicAppPrincipalId) {
    Write-Warning "Logic App managed identity not found; ACS role assignment skipped."
}

if ($ApprovalsCallbackSecretParam) {
    $callbackSecretValue = [System.Guid]::NewGuid().ToString("N")
    Ensure-KvSecret -SecretName $ApprovalsCallbackSecretParam -SecretValue $callbackSecretValue
    Write-Host "Approval callback secret ensured in Key Vault."
}

if ($ApprovalsLogicAppUrl -and $ApprovalsLogicAppSecretParam) {
    Ensure-KvSecret -SecretName $ApprovalsLogicAppSecretParam -SecretValue $ApprovalsLogicAppUrl -Force $true
    Write-Host "Stored approvals Logic App URL in Key Vault."
} elseif ($ApprovalsLogicAppSecretParam) {
    Write-Warning "Approvals Logic App URL not provided. Add it to Key Vault secret: $ApprovalsLogicAppSecretParam"
}

Write-Host "Sprint 6 provisioning complete."
