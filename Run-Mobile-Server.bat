@echo off
chcp 65001 >nul
title Juweier Music Mobile API v3.0.0
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo 未找到运行环境，请先运行 Install-AI-Engine.bat
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements-server.txt
".venv\Scripts\python.exe" -m uvicorn server.mobile_api:app --host 0.0.0.0 --port 8000
if errorlevel 1 pause
