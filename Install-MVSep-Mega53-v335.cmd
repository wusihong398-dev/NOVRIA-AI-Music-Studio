@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -ExecutionPolicy Bypass -File "%~dp0Install-MVSep-Mega53-v335.ps1"
set "INSTALL_EXIT=%ERRORLEVEL%"
if not "%INSTALL_EXIT%"=="0" (
  echo.
  echo [ERROR] Installation stopped with code %INSTALL_EXIT%.
  echo Send a screenshot of the error above.
  pause
)
endlocal
