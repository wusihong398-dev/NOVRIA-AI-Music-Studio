@echo off
chcp 65001 >nul
title Juweier Music Mobile API v3.2.6
cd /d "%~dp0"

if not defined JUWEIER_SERVER_PORT set "JUWEIER_SERVER_PORT=8001"
if not defined JUWEIER_SERVER_LIBRARY set "JUWEIER_SERVER_LIBRARY=G:\JuweierMusicLibrary\01_Originals\按歌手分类(MP3）"
if not defined JUWEIER_SERVER_LIBRARY_FLAC set "JUWEIER_SERVER_LIBRARY_FLAC=G:\JuweierMusicLibrary\008.按歌手分类"
if not defined JUWEIER_AUTO_SCAN_LIBRARY set "JUWEIER_AUTO_SCAN_LIBRARY=1"

if not exist ".venv\Scripts\python.exe" (
  echo 未找到运行环境，请先运行 Install-AI-Engine.bat
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements-server.txt
echo 正在启动 v3.2.6 Mobile API，端口 %JUWEIER_SERVER_PORT% ...
echo MP3 曲库：%JUWEIER_SERVER_LIBRARY%
echo FLAC 曲库：%JUWEIER_SERVER_LIBRARY_FLAC%
".venv\Scripts\python.exe" -m uvicorn server.mobile_api:app --host 0.0.0.0 --port %JUWEIER_SERVER_PORT% --proxy-headers --forwarded-allow-ips="*"
if errorlevel 1 pause
