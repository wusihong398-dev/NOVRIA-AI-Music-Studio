@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

for /l %%I in (1,1,30) do (
  curl.exe -fsS "http://127.0.0.1:8001/api/v1/library/mobile/health" >nul 2>nul && goto :ready
  timeout /t 2 /nobreak >nul
)

echo [ERROR] Server on port 8001 is not ready.
echo Run Start-Juweier-Server-v338-Low-VRAM-Pilot.ps1 first.
pause
exit /b 2

:ready
curl.exe -fsS -X POST "http://127.0.0.1:8001/api/v1/library/batch/start?retry_failed=true&limit=1"
echo.
echo One pilot song was started. The remaining two songs will stay pending.
echo Keep the v3.3.8 server window open until this one job finishes.
pause
endlocal
