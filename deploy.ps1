# deploy.ps1 — Pull, build, and deploy zs-config on a Windows Docker host.
#
# Works in two modes:
#   1. Standalone (fresh machine) — run the script directly; it will clone
#      the repo into .\zs-config next to the script, then deploy from there.
#   2. Inside the repo — run from an existing clone; it will pull and redeploy.
#
# Usage:
#   .\deploy.ps1 [branch]
#
# Single-command deploy on a fresh machine (run in PowerShell as Administrator):
#   Invoke-WebRequest -Uri https://raw.githubusercontent.com/mpreissner/zs-config/main/deploy.ps1 -OutFile deploy.ps1; .\deploy.ps1

param(
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/mpreissner/zs-config.git"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── Preflight ─────────────────────────────────────────────────────────────────

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "ERROR: docker is not installed or not in PATH."
    exit 1
}

try {
    docker compose version | Out-Null
} catch {
    Write-Error "ERROR: docker compose (v2) is required."
    exit 1
}

# ── docker-compose.yml diff check ────────────────────────────────────────────

$script:DcBackup = $null

function Invoke-ComposeDiff {
    param([string]$Branch)
    $dcFile = Join-Path $RepoDir "docker-compose.yml"
    if (-not (Test-Path $dcFile)) { return }

    $tmpRemote = [System.IO.Path]::GetTempFileName()
    try {
        $content = & git show "origin/${Branch}:docker-compose.yml" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $content) {
            Remove-Item $tmpRemote -ErrorAction SilentlyContinue; return
        }
        [System.IO.File]::WriteAllLines($tmpRemote, $content)
    } catch {
        Remove-Item $tmpRemote -ErrorAction SilentlyContinue; return
    }

    $savedPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & git diff --no-index --quiet $dcFile $tmpRemote 2>$null
    $hasDiff = ($LASTEXITCODE -ne 0)
    $ErrorActionPreference = $savedPref

    if (-not $hasDiff) {
        Remove-Item $tmpRemote -ErrorAction SilentlyContinue; return
    }

    Write-Host ""
    Write-Host "docker-compose.yml differs from upstream (origin/$Branch):"
    Write-Host "────────────────────────────────────────────────────────────"
    $ErrorActionPreference = "Continue"
    & git diff --no-index --src-prefix="local/" --dst-prefix="upstream/" $dcFile $tmpRemote
    $ErrorActionPreference = $savedPref
    Write-Host "────────────────────────────────────────────────────────────"
    Write-Host ""
    Remove-Item $tmpRemote -ErrorAction SilentlyContinue

    if (-not [Console]::IsInputRedirected) {
        Write-Host "  [1] Use upstream version (recommended)"
        Write-Host "  [2] Keep my local version"
        $dcChoice = Read-Host "Choice [1/2, default 1]"
        if ($dcChoice -eq "2") {
            $script:DcBackup = [System.IO.Path]::GetTempFileName()
            Copy-Item $dcFile $script:DcBackup
            Write-Host "Local docker-compose.yml saved; will be restored after pull."
        }
    } else {
        Write-Host "Non-interactive — using upstream docker-compose.yml."
    }
    Write-Host ""
}

function Restore-Compose {
    if ($script:DcBackup -and (Test-Path $script:DcBackup)) {
        Copy-Item $script:DcBackup (Join-Path $RepoDir "docker-compose.yml") -Force
        Remove-Item $script:DcBackup -ErrorAction SilentlyContinue
        $script:DcBackup = $null
        Write-Host "Restored local docker-compose.yml."
    }
}

# ── Clone if not already inside the repo ─────────────────────────────────────

$IsRepo = $false
try {
    $null = git -C $ScriptDir rev-parse --git-dir 2>$null
    $IsRepo = $true
} catch {}

if ($IsRepo) {
    $RepoDir = git -C $ScriptDir rev-parse --show-toplevel
    Set-Location $RepoDir
    Write-Host "Fetching latest code..."
    git fetch origin
    Invoke-ComposeDiff $Branch
    git checkout $Branch
    git pull origin $Branch
    Restore-Compose
} else {
    $RepoDir = Join-Path $ScriptDir "zs-config"
    if (Test-Path $RepoDir) {
        Write-Host "Found existing clone at $RepoDir, pulling latest..."
        Set-Location $RepoDir
        git fetch origin
        Invoke-ComposeDiff $Branch
        git checkout $Branch
        git pull origin $Branch
        Restore-Compose
    } else {
        Write-Host "Cloning $RepoUrl into $RepoDir..."
        git clone --branch $Branch $RepoUrl $RepoDir
        Set-Location $RepoDir
    }
}

# ── Ensure JWT_SECRET is set ──────────────────────────────────────────────────

$EnvFile = Join-Path $RepoDir ".env"
$JwtSecret = $null

if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match "^JWT_SECRET=(.+)$") {
            $JwtSecret = $Matches[1]
        }
    }
}

if (-not $JwtSecret) {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $JwtSecret = ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
    Add-Content -Path $EnvFile -Value "JWT_SECRET=$JwtSecret"
    Write-Host "Generated JWT_SECRET and saved to $EnvFile — keep this file safe."
}

$env:JWT_SECRET = $JwtSecret

# ── Ensure persistent Docker volumes exist ────────────────────────────────────

foreach ($vol in @("zs-config_zs-db", "zs-config_zs-plugins")) {
    $exists = docker volume inspect $vol 2>$null
    if (-not $exists) {
        Write-Host "Creating Docker volume: $vol"
        docker volume create $vol
    }
}

# ── Inject host trust store ───────────────────────────────────────────────────
# Exports trusted root certs into docker/ca-bundle.pem so the image includes
# any corporate SSL-inspection CAs present on this machine.  Cleared in the
# finally block so the file is never committed with real cert content.

$Bundle = Join-Path $RepoDir "docker\ca-bundle.pem"
Set-Content -Path $Bundle -Value ""

try {
    Write-Host "Exporting Windows certificate store -> docker\ca-bundle.pem"
    foreach ($storePath in @("Cert:\LocalMachine\Root", "Cert:\CurrentUser\Root")) {
        foreach ($cert in (Get-ChildItem $storePath -ErrorAction SilentlyContinue)) {
            $pem = "-----BEGIN CERTIFICATE-----`n" +
                   [Convert]::ToBase64String($cert.RawData, 'InsertLineBreaks') +
                   "`n-----END CERTIFICATE-----`n"
            Add-Content -Path $Bundle -Value $pem
        }
    }
    $certCount = (Select-String -Path $Bundle -Pattern "BEGIN CERTIFICATE" -ErrorAction SilentlyContinue).Count
    Write-Host "  Exported $certCount certificates"

    # ── Build ─────────────────────────────────────────────────────────────────

    Write-Host "Building image..."
    docker compose build

    # ── Deploy ────────────────────────────────────────────────────────────────

    Write-Host "Stopping existing container..."
    docker compose down

    Write-Host "Starting container..."
    docker compose up -d

    # ── Health check ──────────────────────────────────────────────────────────

    Write-Host "Waiting for health check..."
    $ready = $false
    for ($i = 1; $i -le 15; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {}
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 1
    }

    Write-Host ""
    if ($ready) {
        Write-Host ""
        Write-Host "zs-config is running at http://localhost:8000"
        Write-Host ""
        docker compose logs --tail=5
    } else {
        Write-Warning "Health check did not pass within 15 seconds. Check logs:"
        Write-Host "  docker compose logs"
        exit 1
    }
} finally {
    Set-Content -Path $Bundle -Value ""
    if ($script:DcBackup -and (Test-Path $script:DcBackup)) {
        Remove-Item $script:DcBackup -ErrorAction SilentlyContinue
    }
}
