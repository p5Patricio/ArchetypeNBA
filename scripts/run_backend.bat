@echo off
cd /d "%~dp0..\backend"
"C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe" -u -m uvicorn app.main:app --host 127.0.0.1 --port 38921 > "..\logs\backend.log" 2>&1
