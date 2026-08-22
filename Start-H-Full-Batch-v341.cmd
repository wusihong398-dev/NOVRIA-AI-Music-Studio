@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-H-Full-Batch-v341.ps1"
if errorlevel 1 (
  echo.
  echo [ERROR] Full batch was not started. Keep this window open and send the error.
)
pause
endlocal
