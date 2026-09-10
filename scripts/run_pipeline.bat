@echo off
cd /d "%~dp0..\backend"
"C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe" -u daily_runner.py > "..\logs\daily_runner.log" 2>&1
