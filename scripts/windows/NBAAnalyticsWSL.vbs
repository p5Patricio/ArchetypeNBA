' Windows Startup launcher for the WSL install of ArchetypeNBA (copy it to shell:startup).
' 1. Waits 15 s after logon so the network is ready.
' 2. Keeps the WSL distro alive with a hidden `sleep infinity` (WSL stops an idle distro otherwise).
' 3. Runs scripts/start_services_wsl.sh (backend 38921 + frontend 38920) and waits for it.
' 4. Opens the browser on http://localhost:38920/props.
Const DISTRO = "Ubuntu-24.04"
Const WSL_USER = "patricio"
Const START_SCRIPT = "/home/patricio/proyectos/ArchetypeNBA/scripts/start_services_wsl.sh"

WScript.Sleep 15000
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "wsl.exe -d " & DISTRO & " -u " & WSL_USER & " -- sleep infinity", 0, False
WScript.Sleep 2000
WshShell.Run "wsl.exe -d " & DISTRO & " -u " & WSL_USER & " -- bash " & START_SCRIPT, 0, True
WshShell.Run "http://localhost:38920/props", 1, False
