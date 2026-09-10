# ==============================================================================
# Script de Despliegue y Orquestacion Automatica: NBA Analytics Platform
# Puertos Aislados: Frontend (38920) | Backend API (38921)
# 100% Silencioso: Sin ventanas de terminal (ShowWindow = 0)
# ==============================================================================

param (
    [switch]$NoBrowser,
    [switch]$NoRunner
)

$ErrorActionPreference = "Continue"

$ProjectDir = (Get-Item (Split-Path -Parent $PSScriptRoot)).FullName
$ScriptsDir = Join-Path $ProjectDir "scripts"
$BackendDir = Join-Path $ProjectDir "backend"
$FrontendDir = Join-Path $ProjectDir "frontend"
$LogsDir = Join-Path $ProjectDir "logs"

if (-not (Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
}

$BackendPort = 38921
$FrontendPort = 38920

# Configuracion WMI para ejecucion 100% oculta en segundo plano (SW_HIDE = 0)
$startup = [wmiclass]'Win32_ProcessStartup'
$cfg = $startup.CreateInstance()
$cfg.ShowWindow = 0
$proc = [wmiclass]'Win32_Process'

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " INICIANDO SERVICIOS NBA ANALYTICS PLATFORM (SILENT MODE)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Backend Port:  $BackendPort (API)" -ForegroundColor White
Write-Host "Frontend Port: $FrontendPort (Web)" -ForegroundColor White
Write-Host "Logs:          $LogsDir" -ForegroundColor White

# 1. Iniciar Backend en segundo plano sin ventana
$backendConn = Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue
if (-not $backendConn) {
    Write-Host "[1/5] Iniciando Backend en puerto $BackendPort (silencioso)..." -ForegroundColor Yellow
    $backendBat = Join-Path $ScriptsDir "run_backend.bat"
    $bCmd = 'cmd.exe /c "{0}"' -f $backendBat
    $proc.Create($bCmd, $BackendDir, $cfg) | Out-Null
} else {
    Write-Host "[1/5] Backend ya esta activo en puerto $BackendPort." -ForegroundColor Green
}

# 2. Iniciar Frontend en segundo plano sin ventana
$frontendConn = Get-NetTCPConnection -LocalPort $FrontendPort -State Listen -ErrorAction SilentlyContinue
if (-not $frontendConn) {
    Write-Host "[2/5] Iniciando Frontend en puerto $FrontendPort (silencioso)..." -ForegroundColor Yellow
    $frontendBat = Join-Path $ScriptsDir "run_frontend.bat"
    $fCmd = 'cmd.exe /c "{0}"' -f $frontendBat
    $proc.Create($fCmd, $FrontendDir, $cfg) | Out-Null
} else {
    Write-Host "[2/5] Frontend ya esta activo en puerto $FrontendPort." -ForegroundColor Green
}

# 3. Lanzar pipeline diario de props e IA en segundo plano (silencioso)
if (-not $NoRunner) {
    $pipelineBat = Join-Path $ScriptsDir "run_pipeline.bat"
    if (Test-Path $pipelineBat) {
        Write-Host "[3/5] Ejecutando pipeline diario en segundo plano..." -ForegroundColor Yellow
        $pCmd = 'cmd.exe /c "{0}"' -f $pipelineBat
        $proc.Create($pCmd, $BackendDir, $cfg) | Out-Null
    }
} else {
    Write-Host "[3/5] Pipeline diario omitido por flag -NoRunner." -ForegroundColor Gray
}

# 4. Sincronizacion: Esperar a que el Backend y la Base de Datos esten 100% listos
$BackendHealthUrl = "http://127.0.0.1:$BackendPort/api/v1/health"
Write-Host "[4/5] Esperando a que el Backend y la BD respondan ($BackendHealthUrl)..." -ForegroundColor Yellow

$backendReady = $false
$attempts = 0
$maxAttempts = 40

while (-not $backendReady -and $attempts -lt $maxAttempts) {
    $attempts++
    Start-Sleep -Milliseconds 600
    try {
        $resp = Invoke-RestMethod -Uri $BackendHealthUrl -TimeoutSec 2 -ErrorAction Stop
        if ($resp.status -eq "ok" -and $resp.db_connected -eq $true) {
            $backendReady = $true
        }
    } catch {
        # Backend aun inicializando SQLAlchemy/Uvicorn
    }
}

if ($backendReady) {
    Write-Host "[OK] Backend y Base de Datos verificados y listos." -ForegroundColor Green
} else {
    Write-Host "[WARN] El Backend tardo en responder el health check." -ForegroundColor Yellow
}

# 5. Sincronizacion: Esperar a que el Frontend este listo y abrir el navegador
$TargetUrl = "http://127.0.0.1:$FrontendPort/props"
$BrowserUrl = "http://localhost:$FrontendPort/props"

if (-not $NoBrowser) {
    Write-Host "[5/5] Esperando a que el Frontend responda ($TargetUrl)..." -ForegroundColor Yellow
    $frontendReady = $false
    $attempts = 0

    while (-not $frontendReady -and $attempts -lt 30) {
        $attempts++
        Start-Sleep -Milliseconds 500
        try {
            $resp = Invoke-WebRequest -Uri $TargetUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                $frontendReady = $true
            }
        } catch {
            # Frontend levantando
        }
    }

    if ($frontendReady) {
        Write-Host "[OK] Plataforma online! Abriendo navegador en $BrowserUrl..." -ForegroundColor Green
        Start-Process $BrowserUrl
    } else {
        Write-Host "[WARN] Frontend tardo en responder. Abriendo URL de todas formas..." -ForegroundColor Yellow
        Start-Process $BrowserUrl
    }
} else {
    Write-Host "[5/5] Apertura de navegador omitida por flag -NoBrowser." -ForegroundColor Gray
}

Write-Host "==========================================================" -ForegroundColor Green
Write-Host " DESPLIEGUE SILENCIOSO COMPLETADO" -ForegroundColor Green
Write-Host " URL: $BrowserUrl" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Green
