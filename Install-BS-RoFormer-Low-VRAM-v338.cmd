@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-BS-RoFormer-Low-VRAM-v338.ps1"
if errorlevel 1 (
  echo.
  echo [ERROR] RTX 3060 low-VRAM patch installation failed.
  pause
  exit /b 1
)
endlocal
