# Wait 1.5 seconds so FastAPI has time to flush the HTTP response to the browser
Start-Sleep -Milliseconds 1500

$stopScript = Join-Path $PSScriptRoot "stop_services.ps1"
if (Test-Path $stopScript) {
    & $stopScript
}
