@echo off
cd /d "%~dp0..\frontend"
node node_modules\next\dist\bin\next start -p 38920 -H 127.0.0.1 > "..\logs\frontend.log" 2>&1
