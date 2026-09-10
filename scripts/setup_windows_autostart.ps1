# ==============================================================================
# Script de Configuracion de Auto-Inicio en Windows (shell:startup)
# Despliegue automatico de Frontend (38920) y Backend (38921) al iniciar sesion
# ==============================================================================

param (
    [switch]$Unregister,
    [switch]$TestNow
)

$ProjectDir = (Get-Item (Split-Path -Parent $PSScriptRoot)).FullName
$StartScriptPath = Join-Path $ProjectDir "scripts\start_services.ps1"
$StartupFolder = [System.Environment]::GetFolderPath('Startup')
$VbsLauncherPath = Join-Path $StartupFolder "NBAAnalyticsStartup.vbs"
$OldVbsPath = Join-Path $StartupFolder "NBAPlayerPropsDailyRunner.vbs"

if ($Unregister) {
    Write-Host "Eliminando configuracion de auto-inicio de Windows..." -ForegroundColor Yellow
    if (Test-Path $VbsLauncherPath) {
        Remove-Item $VbsLauncherPath -Force
        Write-Host "[OK] Eliminado: $VbsLauncherPath" -ForegroundColor Green
    }
    if (Test-Path $OldVbsPath) {
        Remove-Item $OldVbsPath -Force
        Write-Host "[OK] Eliminado lanzador anterior: $OldVbsPath" -ForegroundColor Green
    }
    Write-Host "[OK] Desinstalacion de auto-inicio completada." -ForegroundColor Green
    exit 0
}

if ($TestNow) {
    Write-Host "[TEST] Probando despliegue completo ahora mismo..." -ForegroundColor Cyan
    & powershell.exe -ExecutionPolicy Bypass -File $StartScriptPath
    exit 0
}

# Limpiar lanzador anterior si existe
if (Test-Path $OldVbsPath) {
    Remove-Item $OldVbsPath -Force -ErrorAction SilentlyContinue
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " CONFIGURANDO AUTO-INICIO EN WINDOWS (STARTUP)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Proyecto:  $ProjectDir" -ForegroundColor White
Write-Host "Script:    $StartScriptPath" -ForegroundColor White
Write-Host "Destino:   $VbsLauncherPath" -ForegroundColor White

# Creamos el lanzador VBScript
# Retardo de 15 segundos para estabilizacion de adaptadores de red y DNS
$VbsContent = @"
WScript.Sleep 15000
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "$ProjectDir"
WshShell.Run "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File ""$StartScriptPath""", 0, False
"@

try {
    Set-Content -Path $VbsLauncherPath -Value $VbsContent -Encoding ASCII
    Write-Host ""
    Write-Host "[EXITO] Auto-inicio configurado correctamente en Windows!" -ForegroundColor Green
    Write-Host "Lanzador: $VbsLauncherPath" -ForegroundColor White
    Write-Host "Comportamiento al encender la PC:" -ForegroundColor Cyan
    Write-Host "  1. Espera 15s tras iniciar sesion para que la conexion a internet este lista."
    Write-Host "  2. Levanta en segundo plano el Backend en http://localhost:38921."
    Write-Host "  3. Levanta en segundo plano el Frontend en http://localhost:38920."
    Write-Host "  4. Ejecuta el pipeline diario con proyecciones y reporte a Telegram."
    Write-Host "  5. Abre automaticamente el navegador en http://localhost:38920/props."
    Write-Host ""
    Write-Host "Para probarlo ahora mismo podes ejecutar:" -ForegroundColor Gray
    Write-Host "powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows_autostart.ps1 -TestNow" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Para detener los servicios cuando quieras:" -ForegroundColor Gray
    Write-Host "powershell -ExecutionPolicy Bypass -File .\scripts\stop_services.ps1" -ForegroundColor Yellow
} catch {
    Write-Host "[ERROR] Error al crear el archivo VBS: $_" -ForegroundColor Red
}
