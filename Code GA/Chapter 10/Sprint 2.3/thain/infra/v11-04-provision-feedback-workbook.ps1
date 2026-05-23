param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$TemplatePath = ".\\infra\\templates\\workbook-feedback.json",
    [string]$DisplayName = "Thain Feedback Metrics",
    [string]$WorkbookId
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

if (-not (Test-Path $TemplatePath)) {
    Write-Error "Workbook template not found: $TemplatePath"
    exit 1
}

. $VarsFile

$appInsightsId = az resource show `
    --resource-group $ResourceGroupName `
    --name $AppInsightsName `
    --resource-type "Microsoft.Insights/components" `
    --query id -o tsv

if (-not $appInsightsId) {
    Write-Error "Unable to resolve Application Insights resource ID."
    exit 1
}

try {
    az extension show --name application-insights --only-show-errors | Out-Null
} catch {
    Write-Host "Installing Azure CLI extension: application-insights"
    az extension add --name application-insights --only-show-errors | Out-Null
}

$existingId = $null
try {
    $existing = az monitor app-insights workbook list `
        --resource-group $ResourceGroupName `
        --category workbook `
        --query "[?displayName=='$DisplayName'] | sort_by(@, &timeModified) | [-1]" -o json `
        --only-show-errors | ConvertFrom-Json
    if ($existing) {
        $existingId = $existing.id
    }
} catch {
    $existingId = $null
}

$resolvedJson = (Get-Content $TemplatePath -Raw).Replace("__APPINSIGHTS_RESOURCE_ID__", $appInsightsId)
$serializedData = $resolvedJson
$body = @{
    location = $Location
    kind = "shared"
    properties = @{
        displayName = $DisplayName
        category = "workbook"
        sourceId = $appInsightsId
        serializedData = $serializedData
        version = "Notebook/1.0"
    }
}
$bodyJson = $body | ConvertTo-Json -Depth 20 -Compress
$tempFile = [System.IO.Path]::GetTempFileName()
Set-Content -Path $tempFile -Value $bodyJson -Encoding ASCII

if (-not $WorkbookId) {
    $WorkbookId = [guid]::NewGuid().ToString()
}

if ($existingId) {
    Write-Host "Workbook already exists: $existingId"
    Write-Host "Updating workbook content..."
    $workbookId = $existingId
} else {
    Write-Host "Creating workbook: $DisplayName"
    $workbookId = "/subscriptions/$((az account show --query id -o tsv))/resourceGroups/$ResourceGroupName/providers/Microsoft.Insights/workbooks/$WorkbookId"
}

Write-Host "Applying workbook definition..."
$normalizedId = if ($workbookId.StartsWith("/")) { $workbookId } else { "/$workbookId" }
$apiVersion = "2021-08-01"
$restUri = "https://management.azure.com${normalizedId}?api-version=$apiVersion"
az rest `
    --method put `
    --uri $restUri `
    --body "@$tempFile" `
    --headers "Content-Type=application/json" `
    --only-show-errors | Out-Null

Remove-Item $tempFile -ErrorAction SilentlyContinue

$workbook = az resource show --ids $normalizedId -o json | ConvertFrom-Json

Write-Host "Workbook created: $($workbook.id)"
$resourceId = ($workbook.id).TrimStart("/")
$tenantId = az account show --query tenantId -o tsv
$workbookUrl = "https://portal.azure.com/#@$tenantId/resource/$resourceId/workbook"
$portalUrl = "https://portal.azure.com/#@/resource/$resourceId"
Write-Host "Opening workbook: $workbookUrl"
Write-Host "Fallback link: $portalUrl"
Start-Process $workbookUrl
