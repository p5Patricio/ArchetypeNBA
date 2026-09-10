# ==============================================================================
# Script para Detener los Servicios: NBA Analytics Platform
# Libera los puertos aislados: 38920 (Frontend) y 38921 (Backend)
# Cierra todos los procesos asociados en árbol (sin procesos huérfanos)
# ==============================================================================

$Ports = @(38920, 38921)

Write-Host "==========================================================" -ForegroundColor Yellow
Write-Host " DETENIENDO SERVICIOS NBA ANALYTICS PLATFORM" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Yellow

foreach ($port in $Ports) {
    $connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($connections) {
        $procIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($procId in $procIds) {
            try {
                $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Host "Finalizando proceso $($proc.ProcessName) (PID: $procId) y arbol de procesos..." -ForegroundColor Cyan
                    & taskkill.exe /F /T /PID $procId 2>&1 | Out-Null
                }
            } catch {
                Write-Host "No se pudo detener PID ${procId}." -ForegroundColor Red
            }
        }
        Write-Host "[OK] Puerto $port liberado." -ForegroundColor Green
    } else {
        Write-Host "Puerto $port ya esta libre." -ForegroundColor Gray
    }
}

Write-Host "==========================================================" -ForegroundColor Green
Write-Host " SERVICIOS DETENIDOS Y PUERTOS LIBERADOS" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
