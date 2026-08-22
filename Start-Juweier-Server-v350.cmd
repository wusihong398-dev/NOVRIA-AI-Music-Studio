@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo Stopping the old service and orphaned inference workers...
powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"
powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python' -and $_.CommandLine -match 'server\.mobile_api|separation_worker_process|bs_roformer\.inference' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
start "Juweier Music v3.5.0 Server" powershell.exe -NoExit -ExecutionPolicy Bypass -File "%~dp0Start-Juweier-Server-v350-Multi-Disk.ps1"
endlocal
