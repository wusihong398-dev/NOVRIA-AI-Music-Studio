@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

for /l %%I in (1,1,30) do (
  curl.exe -fsS "http://127.0.0.1:8001/api/v1/library/mobile/health" >nul 2>nul && goto :ready
  timeout /t 2 /nobreak >nul
)

echo [ERROR] Server on port 8001 is not ready.
echo Run Start-Juweier-Server-v332-Mega53-Pilot.ps1 first.
pause
exit /b 2

:ready
curl.exe -fsS -X POST "http://127.0.0.1:8001/api/v1/library/batch/start"
echo.
echo Three-song MVSep Mega 53-Stems pilot queue started.
echo Keep the server window open until all three jobs finish.
pause
endlocal
