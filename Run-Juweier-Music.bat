@echo off
chcp 65001 >nul
title Juweier Music v3.2.7
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo 未找到运行环境。
  echo 请先双击 Install-AI-Engine.bat
  pause
  exit /b 1
)

".venv\Scripts\python.exe" app\launcher.py
if errorlevel 1 pause
