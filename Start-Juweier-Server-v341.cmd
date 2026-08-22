@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo Stopping the old service on port 8001...
powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"
echo Stopping orphaned Juweier inference workers from the old run...
powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python' -and $_.CommandLine -match 'server\.mobile_api|separation_worker_process|bs_roformer\.inference' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo Starting Juweier Music v3.4.1 multi-disk server...
start "Juweier Music v3.4.1 Server" powershell.exe -NoExit -ExecutionPolicy Bypass -File "%~dp0Start-Juweier-Server-v341-Multi-Disk.ps1"
endlocal
