# AI System Debugger - Local Startup Script
# Run from project root: .\start.ps1

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI System Debugger - Local Startup"     -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Check prerequisites ──────────────────────────────────────────
Write-Host "[1/8] Checking prerequisites..." -ForegroundColor Yellow

$missing = @()
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { $missing += "Python 3.11+" }
if (-not (Get-Command node -ErrorAction SilentlyContinue))   { $missing += "Node 20+" }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { $missing += "Docker Desktop" }

if ($missing.Count -gt 0) {
    Write-Host "  ERROR: Missing prerequisites: $($missing -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "  Python, Node, Docker found." -ForegroundColor Green

# ── 2. Ensure .env exists with correct DB credentials ───────────────
Write-Host "[2/8] Checking .env..." -ForegroundColor Yellow

if (-not (Test-Path "$ProjectRoot\.env")) {
    Copy-Item "$ProjectRoot\.env.example" "$ProjectRoot\.env"
    Write-Host "  Created .env from .env.example." -ForegroundColor Green
    Write-Host "  IMPORTANT: Edit .env and set ASD_OPENAI_API_KEY before using the full pipeline." -ForegroundColor Magenta
}

# Ensure DATABASE_URL has credentials (fix for common setup issue)
$envContent = Get-Content "$ProjectRoot\.env" -Raw
if ($envContent -match "ASD_DATABASE_URL=postgresql\+asyncpg://localhost") {
    $envContent = $envContent -replace "ASD_DATABASE_URL=postgresql\+asyncpg://localhost", "ASD_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost"
    Set-Content "$ProjectRoot\.env" -Value $envContent.TrimEnd()
    Write-Host "  Fixed DATABASE_URL credentials." -ForegroundColor Green
}
Write-Host "  .env ready." -ForegroundColor Green

# ── 3. Activate venv and install Python deps ────────────────────────
Write-Host "[3/8] Setting up Python environment..." -ForegroundColor Yellow

if (-not (Test-Path "$ProjectRoot\venv")) {
    Write-Host "  Creating virtual environment..."
    python -m venv "$ProjectRoot\venv"
}

$env:VIRTUAL_ENV = "$ProjectRoot\venv"
$env:PATH = "$ProjectRoot\venv\Scripts;$env:PATH"

Write-Host "  Installing Python dependencies (this may take a minute on first run)..."
pip install -r "$ProjectRoot\requirements.txt" --quiet 2>&1 | Out-Null
Write-Host "  Python dependencies installed." -ForegroundColor Green

# ── 4. Start Postgres + Redis via Docker ─────────────────────────────
Write-Host "[4/8] Starting PostgreSQL and Redis..." -ForegroundColor Yellow

docker-compose -f "$ProjectRoot\docker-compose.yml" up postgres redis -d 2>&1 | Out-Null

# Wait for Postgres
$retries = 0
while ($retries -lt 30) {
    docker-compose -f "$ProjectRoot\docker-compose.yml" exec -T postgres pg_isready -U postgres -d ai_debugger 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 1
    $retries++
}
if ($retries -ge 30) { Write-Host "  ERROR: PostgreSQL did not start." -ForegroundColor Red; exit 1 }

# Wait for Redis
$retries = 0
while ($retries -lt 30) {
    $ping = docker-compose -f "$ProjectRoot\docker-compose.yml" exec -T redis redis-cli ping 2>&1
    if ($ping -match "PONG") { break }
    Start-Sleep -Seconds 1
    $retries++
}
if ($retries -ge 30) { Write-Host "  ERROR: Redis did not start." -ForegroundColor Red; exit 1 }

Write-Host "  PostgreSQL and Redis are running." -ForegroundColor Green

# ── 5. Ensure database exists ────────────────────────────────────────
Write-Host "[5/8] Ensuring database exists..." -ForegroundColor Yellow

$dbCheck = docker-compose -f "$ProjectRoot\docker-compose.yml" exec -T postgres psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='ai_debugger'" 2>&1
if ($dbCheck -notmatch "1") {
    docker-compose -f "$ProjectRoot\docker-compose.yml" exec -T postgres psql -U postgres -c "CREATE DATABASE ai_debugger;" 2>&1 | Out-Null
    Write-Host "  Created ai_debugger database." -ForegroundColor Green
} else {
    Write-Host "  Database ai_debugger exists." -ForegroundColor Green
}

# ── 6. Run database migrations ───────────────────────────────────────
Write-Host "[6/8] Running database migrations..." -ForegroundColor Yellow

$migrationOutput = & "$ProjectRoot\venv\Scripts\alembic.exe" upgrade head 2>&1
if ($LASTEXITCODE -ne 0) {
    # If migrations fail due to dirty state, reset and retry
    Write-Host "  Migration failed, resetting database..." -ForegroundColor Yellow
    docker-compose -f "$ProjectRoot\docker-compose.yml" exec -T postgres psql -U postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='ai_debugger' AND pid <> pg_backend_pid();" 2>&1 | Out-Null
    docker-compose -f "$ProjectRoot\docker-compose.yml" exec -T postgres psql -U postgres -c "DROP DATABASE IF EXISTS ai_debugger;" 2>&1 | Out-Null
    docker-compose -f "$ProjectRoot\docker-compose.yml" exec -T postgres psql -U postgres -c "CREATE DATABASE ai_debugger;" 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    & "$ProjectRoot\venv\Scripts\alembic.exe" upgrade head 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: Migrations failed after reset. Check alembic output." -ForegroundColor Red
        exit 1
    }
}
Write-Host "  Migrations complete." -ForegroundColor Green

# ── 7. Install frontend dependencies ────────────────────────────────
Write-Host "[7/9] Installing frontend dependencies..." -ForegroundColor Yellow

Set-Location "$ProjectRoot\frontend"
if (-not (Test-Path "node_modules")) {
    npm install --silent 2>&1 | Out-Null
}
Set-Location $ProjectRoot
Write-Host "  Frontend dependencies installed." -ForegroundColor Green

# ── 8. Launch backend + frontend ─────────────────────────────────────
Write-Host "[8/9] Starting services..." -ForegroundColor Yellow

# Start backend
$backend = Start-Process -FilePath "$ProjectRoot\venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "backend.main:app", "--reload", "--port", "8000" `
    -WorkingDirectory $ProjectRoot `
    -PassThru -NoNewWindow

# Start frontend
$frontend = Start-Process -FilePath "npm" `
    -ArgumentList "run", "dev" `
    -WorkingDirectory "$ProjectRoot\frontend" `
    -PassThru -NoNewWindow

# Wait for backend to respond
$retries = 0
while ($retries -lt 20) {
    Start-Sleep -Seconds 1
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($health.status -eq "healthy") { break }
    } catch {}
    $retries++
}

if ($retries -ge 20) {
    Write-Host "  WARNING: Backend did not respond to health check, continuing anyway..." -ForegroundColor Yellow
} else {
    Write-Host "  Backend is healthy." -ForegroundColor Green
}

# ── 9. Seed demo data if database is empty ───────────────────────────
Write-Host "[9/9] Checking if demo data needs seeding..." -ForegroundColor Yellow

try {
    $metrics = Invoke-RestMethod -Uri "http://localhost:8000/metrics" -TimeoutSec 5 -ErrorAction SilentlyContinue
    if ($metrics.total_traces -eq 0) {
        Write-Host "  Database is empty, seeding 15 sample traces (this takes ~2 minutes)..." -ForegroundColor Yellow
        & "$ProjectRoot\venv\Scripts\python.exe" "$ProjectRoot\scripts\load_sample_data.py" --base-url http://localhost:8000 --skip-fix 2>&1 | ForEach-Object {
            if ($_ -match "^\[" -or $_ -match "^Done") { Write-Host "  $_" -ForegroundColor DarkGray }
        }
        Write-Host "  Demo data seeded." -ForegroundColor Green
    } else {
        Write-Host "  Database already has $($metrics.total_traces) traces, skipping seed." -ForegroundColor Green
    }
} catch {
    Write-Host "  WARNING: Could not check metrics, skipping seed. Run manually:" -ForegroundColor Yellow
    Write-Host "    python scripts\load_sample_data.py --base-url http://localhost:8000 --skip-fix"
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  All services running!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Dashboard:  http://localhost:3000"      -ForegroundColor Cyan
Write-Host "  API docs:   http://localhost:8000/docs"  -ForegroundColor Cyan
Write-Host ""
Write-Host "  Press Ctrl+C to stop all services." -ForegroundColor Yellow
Write-Host ""

# Keep alive and clean up on Ctrl+C
try {
    while ($true) {
        if ($backend.HasExited -or $frontend.HasExited) {
            Write-Host "A service exited unexpectedly." -ForegroundColor Red
            break
        }
        Start-Sleep -Seconds 2
    }
} finally {
    Write-Host ""
    Write-Host "Shutting down..." -ForegroundColor Yellow

    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
    if (-not $frontend.HasExited) { Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue }

    docker-compose -f "$ProjectRoot\docker-compose.yml" stop postgres redis 2>&1 | Out-Null

    Write-Host "All services stopped." -ForegroundColor Green
}
