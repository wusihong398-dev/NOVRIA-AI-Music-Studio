@echo off
chcp 65001 >nul
setlocal
if not defined JUWEIER_SERVER_PORT set "JUWEIER_SERVER_PORT=8001"
echo ===== 橘味儿音乐 v3.2.6 Mobile API 检查 =====
echo.
curl.exe --fail --show-error --connect-timeout 5 "http://127.0.0.1:%JUWEIER_SERVER_PORT%/api/v1/library/mobile/health"
if errorlevel 1 (
  echo.
  echo 检查失败：请先双击 Run-Mobile-Server.bat，并确认端口未被防火墙拦截。
  pause
  exit /b 1
)
echo.
echo.
echo ===== 读取已缓存歌曲目录 =====
curl.exe --fail --show-error --connect-timeout 10 "http://127.0.0.1:%JUWEIER_SERVER_PORT%/api/v1/library/mobile/catalog"
echo.
echo.
echo 检查完成。health 应显示 version 3.2.6，catalog_count 应大于 0。
pause
