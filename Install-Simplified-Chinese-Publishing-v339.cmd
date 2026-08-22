@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Simplified-Chinese-Publishing-v339.ps1"
if errorlevel 1 (
  echo.
  echo [ERROR] v3.3.9 installation failed. Keep this window open and send the error.
  pause
  exit /b 1
)
endlocal
