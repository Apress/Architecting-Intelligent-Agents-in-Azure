param(
    [string]$VarsFile = ".\\infra\\infra_config.ps1",
    [string]$EnvFile = ".\\.env.dev",
    [string]$ModelName,
    [string]$Region,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $VarsFile)) {
    Write-Error "Vars file not found: $VarsFile"
    exit 1
}

if (-not (Test-Path $EnvFile)) {
    Write-Error "Env file not found: $EnvFile"
    exit 1
}

. $VarsFile

function Get-EnvValue {
    param(
        [string]$Path,
        [string]$Name
    )
    $pattern = "^\s*$([regex]::Escape($Name))=(.*)$"
    $line = Get-Content $Path | Where-Object { $_ -match $pattern } | Select-Object -First 1
    if (-not $line) {
        return $null
    }
    $matches = [regex]::Match($line, $pattern)
    if ($matches.Success) {
        return $matches.Groups[1].Value.Trim()
    }
    return $null
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

function Normalize-Text {
    param([string]$Text)
    if (-not $Text) { return "" }
    return (($Text.ToLowerInvariant()) -replace "[^a-z0-9]", "")
}

function Build-ModelRegex {
    param([string]$Model)
    $parts = ($Model.ToLowerInvariant() -split "[^a-z0-9]+" | Where-Object { $_ })
    if (-not $parts -or $parts.Count -eq 0) {
        return "^$"
    }
    $joined = [string]::Join("[-\s_]*", $parts)
    return "(?i)(^|[^a-z0-9])$joined([^a-z0-9]|$)"
}

function Get-MeterScore {
    param([string]$Text)
    $score = 0
    if ($Text -match "(?i)\b(regional|regnl|rgnl)\b") { $score += 3 }
    if ($Text -match "(?i)\b(global|glbl)\b") { $score += 2 }
    if ($Text -match "(?i)\b(dzone|data\s*zone|dz)\b") { $score -= 3 }
    if ($Text -match "(?i)\b(realtime|rt|audio|img|image|transcrib|speech)\b") { $score -= 4 }
    if ($Text -match "(?i)\b(cached|batch|finetune|fine\s*tune|grader|grdr)\b") { $score -= 4 }
    return $score
}

function Convert-ToPer1K {
    param(
        [double]$RetailPrice,
        [string]$UnitOfMeasure
    )
    if ($RetailPrice -lt 0) {
        throw "Retail price cannot be negative."
    }

    $unit = ($UnitOfMeasure | ForEach-Object { $_.Trim().ToLowerInvariant() })
    if (-not $unit) {
        throw "Missing unit of measure."
    }

    $tokens = 1000.0
    if ($unit -match "([0-9]+(?:\.[0-9]+)?)\s*(m|million)\s*(token)?") {
        $tokens = [double]$matches[1] * 1000000.0
    } elseif ($unit -match "([0-9]+(?:\.[0-9]+)?)\s*k\s*(token)?") {
        $tokens = [double]$matches[1] * 1000.0
    } elseif ($unit -match "([0-9]+(?:\.[0-9]+)?)\s*token") {
        $tokens = [double]$matches[1]
    } elseif ($unit -notmatch "token") {
        throw "Unexpected unit of measure: $UnitOfMeasure"
    }

    if ($tokens -le 0) {
        throw "Invalid token quantity parsed from unit: $UnitOfMeasure"
    }

    return [math]::Round($RetailPrice / ($tokens / 1000.0), 8)
}

if (-not $ModelName) {
    $ModelName = (Get-EnvValue -Path $EnvFile -Name "AZURE_AI_MODEL_DEPLOYMENT_NAME")
}
if (-not $ModelName) {
    Write-Error "Model name not provided. Pass -ModelName or set AZURE_AI_MODEL_DEPLOYMENT_NAME in $EnvFile."
    exit 1
}

if (-not $Region) {
    $Region = $Location
}
if (-not $Region) {
    Write-Error "Region not provided. Pass -Region or set Location in $VarsFile."
    exit 1
}

$regionNormalized = $Region.Trim().ToLowerInvariant()
$modelNormalized = Normalize-Text -Text $ModelName

$modelRegex = Build-ModelRegex -Model $ModelName

$filter = [uri]::EscapeDataString("contains(productName,'Azure OpenAI') and armRegionName eq '$regionNormalized'")
$url = "https://prices.azure.com/api/retail/prices?`$filter=$filter"
$records = @()

Write-Host "Querying Azure Retail Prices API for model '$ModelName' in region '$regionNormalized'..."
while ($url) {
    $response = Invoke-RestMethod -Method Get -Uri $url -TimeoutSec 60
    if ($response.Items) {
        $records += $response.Items
    }
    $url = $response.NextPageLink
}

if (-not $records -or $records.Count -eq 0) {
    Write-Error "No pricing records found for Azure OpenAI Service in region $regionNormalized."
    exit 1
}

$filtered = $records | Where-Object {
    $meter = [string]($_.meterName)
    $product = [string]($_.productName)
    $sku = [string]($_.skuName)
    $text = "$meter $product $sku"
    $textNorm = Normalize-Text -Text $text

    $matchesModel = ($text -match $modelRegex) -or $textNorm.Contains($modelNormalized)
    $isTokenMeter = ($meter -match "(?i)token")
    $notExcluded = ($meter -notmatch "(?i)(batch|cached|realtime|rt|audio|img|image|transcrib|speech|finetune|grader|grdr)")
    $notMedia = ($product -notmatch "(?i)media")
    $isConsumption = ([string]$_.type -eq "Consumption")
    $hasPrice = ([double]$_.retailPrice -gt 0)

    return $matchesModel -and $isTokenMeter -and $notExcluded -and $notMedia -and $isConsumption -and $hasPrice
}

if (-not $filtered -or $filtered.Count -eq 0) {
    Write-Error "No token pricing meters matched model '$ModelName' in region '$regionNormalized'. Set rates manually."
    exit 1
}

$inputCandidates = $filtered | Where-Object { [string]$_.meterName -match "(?i)\binput\b" }
$outputCandidates = $filtered | Where-Object { [string]$_.meterName -match "(?i)\boutput\b" }

if (-not $inputCandidates -or $inputCandidates.Count -eq 0) {
    Write-Error "Input token meter not found for model '$ModelName'."
    exit 1
}
if (-not $outputCandidates -or $outputCandidates.Count -eq 0) {
    Write-Error "Output token meter not found for model '$ModelName'."
    exit 1
}

$inputMeter = $inputCandidates `
    | Select-Object *, @{Name="score";Expression={ Get-MeterScore -Text ([string]$_.meterName) }} `
    | Sort-Object -Property @{Expression="score";Descending=$true}, @{Expression="effectiveStartDate";Descending=$true} `
    | Select-Object -First 1
$outputMeter = $outputCandidates `
    | Select-Object *, @{Name="score";Expression={ Get-MeterScore -Text ([string]$_.meterName) }} `
    | Sort-Object -Property @{Expression="score";Descending=$true}, @{Expression="effectiveStartDate";Descending=$true} `
    | Select-Object -First 1

$inputPer1K = Convert-ToPer1K -RetailPrice ([double]$inputMeter.retailPrice) -UnitOfMeasure ([string]$inputMeter.unitOfMeasure)
$outputPer1K = Convert-ToPer1K -RetailPrice ([double]$outputMeter.retailPrice) -UnitOfMeasure ([string]$outputMeter.unitOfMeasure)

Write-Host ("Selected input meter: {0} | price={1} {2}" -f $inputMeter.meterName, $inputMeter.retailPrice, $inputMeter.unitOfMeasure)
Write-Host ("Selected output meter: {0} | price={1} {2}" -f $outputMeter.meterName, $outputMeter.retailPrice, $outputMeter.unitOfMeasure)
Write-Host ("Computed THAIN_COST_INPUT_PER_1K_USD={0}" -f $inputPer1K)
Write-Host ("Computed THAIN_COST_OUTPUT_PER_1K_USD={0}" -f $outputPer1K)

if ($DryRun) {
    Write-Host "DryRun enabled. No changes written to $EnvFile."
    exit 0
}

Set-EnvVarInFile -Path $EnvFile -Name "THAIN_COST_INPUT_PER_1K_USD" -Value ([string]$inputPer1K)
Set-EnvVarInFile -Path $EnvFile -Name "THAIN_COST_OUTPUT_PER_1K_USD" -Value ([string]$outputPer1K)

Write-Host "Updated pricing variables in $EnvFile"
