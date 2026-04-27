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
    git checkout $Branch
    git pull origin $Branch
} else {
    $RepoDir = Join-Path $ScriptDir "zs-config"
    if (Test-Path $RepoDir) {
        Write-Host "Found existing clone at $RepoDir, pulling latest..."
        Set-Location $RepoDir
        git fetch origin
        git checkout $Branch
        git pull origin $Branch
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

# ── Build ─────────────────────────────────────────────────────────────────────

Write-Host "Building image..."
docker compose build

# ── Deploy ────────────────────────────────────────────────────────────────────

Write-Host "Stopping existing container..."
docker compose down

Write-Host "Starting container..."
docker compose up -d

# ── Health check ──────────────────────────────────────────────────────────────

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
