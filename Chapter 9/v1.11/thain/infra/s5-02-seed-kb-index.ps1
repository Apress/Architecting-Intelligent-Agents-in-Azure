param(
    [string]$EnvFile,
    [string]$DataFile = ".\\infra\\data\\s5-kb-documents.json"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "python not found. Activate your environment first."
    exit 1
}

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
    Write-Error "Seed data file not found: $DataFile"
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

Write-Host "Seeding KB index from $DataFile"
python .\infra\scripts\s5_seed_docs.py --data-file $DataFile
if ($LASTEXITCODE -ne 0) {
    Write-Error "KB index seeding failed."
    exit $LASTEXITCODE
}

Write-Host "KB index seeding complete."
