# ==============================================================================
# Registro de Tareas Programadas de Windows: snapshots de cuotas (odds_history)
#   - NBA-Odds-Opening: 1 vez al dia (11:00 local), 1 llamada /odds (3 creditos)
#   - NBA-Odds-Closing: cada 30 min entre 17:00 y 23:30 local; solo gasta creditos
#     si hay un partido que empieza dentro de la ventana y sin snapshot de cierre
# Presupuesto The Odds API (500 creditos/mes): ~15 creditos/dia con -PropsEvents 1
# (ver backend/app/services/odds_snapshot.py).
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File .\scripts\register_odds_snapshot_tasks.ps1 -WhatIf
#   powershell -ExecutionPolicy Bypass -File .\scripts\register_odds_snapshot_tasks.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\register_odds_snapshot_tasks.ps1 -Unregister
# ==============================================================================

[CmdletBinding(SupportsShouldProcess = $true)]
param (
    [switch]$Unregister,
    [string]$PythonExe = "",
    [string]$OpeningTime = "11:00",
    [string]$ClosingStart = "17:00",
    [int]$ClosingDurationMinutes = 390,
    [int]$ClosingIntervalMinutes = 30,
    [int]$PropsEvents = 1
)

$ErrorActionPreference = "Stop"

$ProjectDir = (Get-Item (Split-Path -Parent $PSScriptRoot)).FullName
$BackendDir = Join-Path $ProjectDir "backend"
$LogsDir = Join-Path $ProjectDir "logs"
$LogFile = Join-Path $LogsDir "odds_snapshot.log"
$CaptureScript = Join-Path $BackendDir "scripts\capture_odds_snapshot.py"
$PipelineBat = Join-Path $PSScriptRoot "run_pipeline.bat"

$OpeningTask = "NBA-Odds-Opening"
$ClosingTask = "NBA-Odds-Closing"

if ($Unregister) {
    Write-Host "Eliminando tareas programadas de snapshots de cuotas..." -ForegroundColor Yellow
    foreach ($name in @($OpeningTask, $ClosingTask)) {
        $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if (-not $existing) {
            Write-Host "[--] No existe: $name" -ForegroundColor Gray
            continue
        }
        if ($PSCmdlet.ShouldProcess($name, "Unregister-ScheduledTask")) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "[OK] Eliminada: $name" -ForegroundColor Green
        }
    }
    exit 0
}

# Python: el mismo interprete que usa run_pipeline.bat (si no se indica -PythonExe)
if (-not $PythonExe -and (Test-Path $PipelineBat)) {
    $match = Select-String -Path $PipelineBat -Pattern '"([^"]*python[^"]*\.exe)"' | Select-Object -First 1
    if ($match) { $PythonExe = $match.Matches[0].Groups[1].Value }
}
if (-not $PythonExe) { $PythonExe = "python" }
if (($PythonExe -ne "python") -and -not (Test-Path $PythonExe)) {
    Write-Host "[ERROR] No se encontro Python en: $PythonExe (usa -PythonExe)" -ForegroundColor Red
    exit 1
}

function New-SnapshotAction([string]$Phase, [string]$ExtraArgs) {
    $inner = "& '$PythonExe' -u '$CaptureScript' --phase $Phase $ExtraArgs *>> '$LogFile'"
    $arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$inner`""
    return New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $BackendDir
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

$openingTrigger = New-ScheduledTaskTrigger -Daily -At $OpeningTime
$openingAction = New-SnapshotAction "opening" ""

# Disparador diario con repeticion (la sintaxis -Daily no admite -RepetitionInterval directamente)
$closingTrigger = New-ScheduledTaskTrigger -Daily -At $ClosingStart
$repeat = New-ScheduledTaskTrigger -Once -At $ClosingStart `
    -RepetitionInterval (New-TimeSpan -Minutes $ClosingIntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Minutes $ClosingDurationMinutes)
$closingTrigger.Repetition = $repeat.Repetition
$closingAction = New-SnapshotAction "closing" "--props-events $PropsEvents"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " TAREAS PROGRAMADAS: SNAPSHOTS DE CUOTAS (THE ODDS API)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Python:    $PythonExe" -ForegroundColor White
Write-Host "Script:    $CaptureScript" -ForegroundColor White
Write-Host "Log:       $LogFile" -ForegroundColor White
Write-Host "Apertura:  $OpeningTask diaria a las $OpeningTime" -ForegroundColor White
Write-Host "Cierre:    $ClosingTask desde las $ClosingStart cada $ClosingIntervalMinutes min durante $ClosingDurationMinutes min (props: $PropsEvents evento/s)" -ForegroundColor White
Write-Host "Presupuesto estimado: ~15 creditos/dia con -PropsEvents 1 (limite 500/mes)." -ForegroundColor Gray

if (-not (Test-Path $CaptureScript)) {
    Write-Host "[ERROR] No existe $CaptureScript" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $LogsDir) -and $PSCmdlet.ShouldProcess($LogsDir, "Crear directorio de logs")) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
}

$tasks = @(
    @{ Name = $OpeningTask; Action = $openingAction; Trigger = $openingTrigger; Description = "Snapshot de apertura de cuotas NBA (1 llamada /odds)" },
    @{ Name = $ClosingTask; Action = $closingAction; Trigger = $closingTrigger; Description = "Snapshot de cierre de cuotas NBA (solo si hay partidos por comenzar)" }
)

foreach ($task in $tasks) {
    if ($PSCmdlet.ShouldProcess($task.Name, "Register-ScheduledTask")) {
        Register-ScheduledTask -TaskName $task.Name -Action $task.Action -Trigger $task.Trigger `
            -Settings $settings -Description $task.Description -Force | Out-Null
        Write-Host "[OK] Registrada: $($task.Name)" -ForegroundColor Green
    }
}

if (-not $WhatIfPreference) {
    Write-Host ""
    Write-Host "Para quitarlas: powershell -ExecutionPolicy Bypass -File .\scripts\register_odds_snapshot_tasks.ps1 -Unregister" -ForegroundColor Gray
}
