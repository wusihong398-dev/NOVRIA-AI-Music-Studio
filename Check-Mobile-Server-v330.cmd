@echo off
setlocal
curl.exe --fail http://127.0.0.1:8001/api/v1/library/mobile/health
if errorlevel 1 (
  echo.
  echo Local server health check failed.
  exit /b 1
)
echo.
curl.exe --fail "http://127.0.0.1:8001/api/v1/library/mobile/catalog?limit=1"
if errorlevel 1 exit /b 1
echo.
echo Health and catalog checks completed.
