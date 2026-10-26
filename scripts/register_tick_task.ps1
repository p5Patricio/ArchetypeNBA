# ==============================================================================
# Registro de la Tarea Programada de Windows: tick de captura de cuotas + prediccion
#   - NBA-Odds-Tick: arranca al iniciar sesion y se repite cada 15 min (sin fecha de fin)
#     mientras el usuario siga con la sesion abierta. Cada ejecucion corre
#     backend\scripts\run_tick.py, que decide que hacer a partir de marcas en la base:
#     apertura una vez por dia local, cierre cuando un partido empieza en menos de 30 min
#     y registro de predicciones. Las consultas a /events son gratis; solo se gastan
#     creditos si hay algo pendiente (ver backend/app/services/tick.py y odds_snapshot.py).
#   - Reemplaza las tareas de horario fijo NBA-Odds-Opening y NBA-Odds-Closing, que se
#     eliminan antes de registrar la nueva (la PC se enciende a horas variables).
#   - Se registra desde un XML (Register-ScheduledTask -Xml) porque asi la repeticion
#     indefinida al iniciar sesion es exacta. El tick escribe su propio log rotativo en
#     logs\tick.log, por eso la accion no redirige la salida.
#   - La repeticion empieza en el proximo inicio de sesion; -StartNow lanza un tick ya mismo.
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File .\scripts\register_tick_task.ps1 -WhatIf
#   powershell -ExecutionPolicy Bypass -File .\scripts\register_tick_task.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\register_tick_task.ps1 -Unregister
# Si Windows responde "Acceso denegado", abri PowerShell como administrador.
# ==============================================================================

[CmdletBinding(SupportsShouldProcess = $true)]
param (
    [switch]$Unregister,
    [switch]$StartNow,
    [ValidateRange(1, 59)]
    [int]$IntervalMinutes = 15,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$ProjectDir = (Get-Item (Split-Path -Parent $PSScriptRoot)).FullName
$BackendDir = Join-Path $ProjectDir "backend"
$LogFile = Join-Path $ProjectDir "logs\tick.log"
$TickScript = Join-Path $BackendDir "scripts\run_tick.py"
$PipelineBat = Join-Path $PSScriptRoot "run_pipeline.bat"

$TaskName = "NBA-Odds-Tick"
$LegacyTasks = @("NBA-Odds-Opening", "NBA-Odds-Closing")

if ($Unregister) {
    Write-Host "Eliminando la tarea programada del tick..." -ForegroundColor Yellow
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "[--] No existe: $TaskName" -ForegroundColor Gray
    }
    elseif ($PSCmdlet.ShouldProcess($TaskName, "Unregister-ScheduledTask")) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "[OK] Eliminada: $TaskName" -ForegroundColor Green
    }
    exit 0
}

# Interprete de Python, en orden: -PythonExe, el venv del backend, el de run_pipeline.bat (solo si existe en esta PC),
# y por ultimo el primer python.exe del PATH (ignorando el alias vacio de la Microsoft Store).
if (-not $PythonExe) {
    $venvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) { $PythonExe = $venvPython }
}
if (-not $PythonExe -and (Test-Path $PipelineBat)) {
    $match = Select-String -Path $PipelineBat -Pattern '"([^"]*python[^"]*\.exe)"' | Select-Object -First 1
    if ($match -and (Test-Path $match.Matches[0].Groups[1].Value)) { $PythonExe = $match.Matches[0].Groups[1].Value }
}
if (-not $PythonExe) {
    $onPath = Get-Command python.exe -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -and ($_.Source -notmatch 'WindowsApps') } | Select-Object -First 1
    if ($onPath) { $PythonExe = $onPath.Source }
}
if (-not $PythonExe) {
    Write-Host "[ERROR] No se encontro Python (ni venv en backend\.venv, ni run_pipeline.bat, ni PATH). Usa -PythonExe." -ForegroundColor Red
    exit 1
}
# pythonw.exe (subsistema GUI) no crea consola: es lo unico que evita el parpadeo de ventana que roba el foco.
# "powershell -WindowStyle Hidden" oculta la ventana DESPUES de crearla, y ese instante basta para sacarte de un juego o una reunion.
if ($PythonExe -match '(?i)python\.exe$') {
    $candidate = $PythonExe -replace '(?i)python\.exe$', 'pythonw.exe'
    if (Test-Path $candidate) { $PythonExe = $candidate }
}
if (-not (Test-Path $PythonExe)) {
    Write-Host "[ERROR] No se encontro Python en: $PythonExe (usa -PythonExe)" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $TickScript)) {
    Write-Host "[ERROR] No existe $TickScript" -ForegroundColor Red
    exit 1
}

function ConvertTo-XmlText([string]$Text) {
    return [System.Security.SecurityElement]::Escape($Text)
}

function New-TickTaskXml([string]$UserName) {
    # Las comillas simples de las rutas se duplican para el literal de PowerShell; luego todo se escapa para XML.
    # Sin envoltorio de PowerShell: el propio tick escribe logs/tick.log y Task Scheduler guarda el codigo de salida de Python.
    $arguments = "-u `"$TickScript`""
    $xmlCommand = ConvertTo-XmlText $PythonExe

    $user = ConvertTo-XmlText $UserName
    $xmlArguments = ConvertTo-XmlText $arguments
    $workDir = ConvertTo-XmlText $BackendDir
    # TimeTrigger: la repeticion arranca ya (sin esperar al proximo login) y sigue entre sesiones; el LogonTrigger dispara un tick apenas inicias sesion.
    $startBoundary = (Get-Date).AddMinutes(1).ToString("yyyy-MM-ddTHH:mm:ss")
    $description = ConvertTo-XmlText "Tick de cuotas NBA: captura apertura/cierre y registra predicciones cada $IntervalMinutes min mientras la sesion este abierta."

    return @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>$description</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Repetition>
        <Interval>PT${IntervalMinutes}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <Enabled>true</Enabled>
      <UserId>$user</UserId>
    </LogonTrigger>
    <TimeTrigger>
      <Repetition>
        <Interval>PT${IntervalMinutes}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>$startBoundary</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$user</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$xmlCommand</Command>
      <Arguments>$xmlArguments</Arguments>
      <WorkingDirectory>$workDir</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
}

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskXml = New-TickTaskXml $currentUser

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " TAREA PROGRAMADA: TICK DE CUOTAS Y PREDICCIONES" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Tarea:     $TaskName (inicio de sesion de $currentUser, cada $IntervalMinutes min, sin fecha de fin)" -ForegroundColor White
Write-Host "Python:    $PythonExe" -ForegroundColor White
Write-Host "Script:    $TickScript" -ForegroundColor White
Write-Host "Log:       $LogFile (rotativo, lo escribe el propio tick)" -ForegroundColor White
Write-Host "Reemplaza: $($LegacyTasks -join ', ')" -ForegroundColor White
Write-Host "Presupuesto: ~3 creditos/dia de apertura + 3-4 por grupo de partidos (limite 500/mes; ver odds_snapshot.py)." -ForegroundColor Gray

if ($WhatIfPreference) {
    Write-Host ""
    Write-Host "----- TASK XML BEGIN -----"
    Write-Host $taskXml
    Write-Host "----- TASK XML END -----"
    Write-Host ""
}

# 1) Tareas anteriores de horario fijo
foreach ($legacy in $LegacyTasks) {
    $existing = Get-ScheduledTask -TaskName $legacy -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "[--] No existe (ya eliminada): $legacy" -ForegroundColor Gray
        continue
    }
    if ($PSCmdlet.ShouldProcess($legacy, "Unregister-ScheduledTask (tarea anterior de horario fijo)")) {
        Unregister-ScheduledTask -TaskName $legacy -Confirm:$false
        Write-Host "[OK] Eliminada tarea anterior: $legacy" -ForegroundColor Green
    }
}

# 2) Tarea nueva
if ($PSCmdlet.ShouldProcess($TaskName, "Register-ScheduledTask -Xml (inicio de sesion + repeticion cada $IntervalMinutes min)")) {
    try {
        Register-ScheduledTask -TaskName $TaskName -Xml $taskXml -Force | Out-Null
    }
    catch {
        Write-Host "[ERROR] No se pudo registrar ${TaskName}: $_" -ForegroundColor Red
        Write-Host "        Si dice 'Acceso denegado', abri PowerShell como administrador y repeti." -ForegroundColor Yellow
        exit 1
    }
    $registered = Get-ScheduledTask -TaskName $TaskName
    Write-Host "[OK] Registrada: $TaskName (estado: $($registered.State))" -ForegroundColor Green
    Write-Host "     Un tick al iniciar sesion y luego cada $IntervalMinutes min mientras la sesion este abierta (primer disparo en ~1 min)." -ForegroundColor Gray
}

if ($StartNow -and $PSCmdlet.ShouldProcess($TaskName, "Start-ScheduledTask (un tick ahora)")) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "[OK] Tick lanzado ahora; seguimiento en $LogFile" -ForegroundColor Green
}

if (-not $WhatIfPreference) {
    Write-Host ""
    Write-Host "Para quitarla: powershell -ExecutionPolicy Bypass -File .\scripts\register_tick_task.ps1 -Unregister" -ForegroundColor Gray
}
