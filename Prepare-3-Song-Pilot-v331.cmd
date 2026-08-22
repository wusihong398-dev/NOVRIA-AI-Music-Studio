@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv-mobile-api\Scripts\python.exe" (
  echo [ERROR] Python environment not found: .venv-mobile-api
  pause
  exit /b 2
)
set "PYTHONUTF8=1"
set "JUWEIER_DATA_DIR=%CD%"
set "JUWEIER_LIBRARY_DB=%CD%\database\juweier_music_library.sqlite3"
".venv-mobile-api\Scripts\python.exe" -m tools.prepare_server_batch --source "D:\MP3" --data "%CD%" --pilot 3
if errorlevel 1 (
  echo [ERROR] Preflight failed. No AI batch was started.
  pause
  exit /b 3
)
echo.
echo Preflight finished. Only the three pilot songs are marked Pending.
pause
endlocal
