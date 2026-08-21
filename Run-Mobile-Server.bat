@echo off
chcp 65001 >nul
title Juweier Music Mobile API v3.3.0
cd /d "%~dp0"

if exist "%~dp0ffmpeg\bin\ffmpeg.exe" set "PATH=%~dp0ffmpeg\bin;%PATH%"
if exist "%~dp0tools\ffmpeg\ffmpeg.exe" set "PATH=%~dp0tools\ffmpeg;%PATH%"

if not defined JUWEIER_SERVER_PORT set "JUWEIER_SERVER_PORT=8001"
if not defined JUWEIER_DATA_DIR set "JUWEIER_DATA_DIR=%~dp0"
if not defined JUWEIER_LIBRARY_DIR set "JUWEIER_LIBRARY_DIR=G:\JuweierMusicLibrary"
if not defined JUWEIER_SERVER_LIBRARY set "JUWEIER_SERVER_LIBRARY=G:\JuweierMusicLibrary\01_Originals"
if not defined JUWEIER_SERVER_LIBRARY_FLAC set "JUWEIER_SERVER_LIBRARY_FLAC=G:\JuweierMusicLibrary\01_Originals"
if not defined JUWEIER_SERVER_LIBRARY_ROOTS set "JUWEIER_SERVER_LIBRARY_ROOTS=G:\JuweierMusicLibrary\01_Originals"
if not defined JUWEIER_LIBRARY_DB set "JUWEIER_LIBRARY_DB=%~dp0database\juweier_music_library.sqlite3"
if not defined JUWEIER_PROCESSED_DIR set "JUWEIER_PROCESSED_DIR=H:\JuweierAI\03_AI_Processed"
if not defined JUWEIER_UVR_MODEL_DIR set "JUWEIER_UVR_MODEL_DIR=%~dp0models\uvr"
if not defined JUWEIER_AUTO_SCAN_LIBRARY set "JUWEIER_AUTO_SCAN_LIBRARY=1"
if not defined JUWEIER_CATALOG_WATCH_INTERVAL set "JUWEIER_CATALOG_WATCH_INTERVAL=900"

set "JUWEIER_PYTHON=.venv-mobile-api\Scripts\python.exe"
if not exist "%JUWEIER_PYTHON%" set "JUWEIER_PYTHON=.venv\Scripts\python.exe"
if not exist "%JUWEIER_PYTHON%" (
  echo 未找到运行环境，请先运行 Install-AI-Engine.bat
  pause
  exit /b 1
)

echo 正在启动 v3.3.0 Mobile API，端口 %JUWEIER_SERVER_PORT% ...
echo MP3 曲库：%JUWEIER_SERVER_LIBRARY%
echo FLAC 曲库：%JUWEIER_SERVER_LIBRARY_FLAC%
echo AI 成果：%JUWEIER_PROCESSED_DIR%
"%JUWEIER_PYTHON%" -m uvicorn server.mobile_api:app --host 0.0.0.0 --port %JUWEIER_SERVER_PORT% --proxy-headers --forwarded-allow-ips="*"
if errorlevel 1 pause
