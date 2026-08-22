@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoExit -ExecutionPolicy Bypass -File "%~dp0Install-BS-RoFormer-Mega53-v336.ps1"
endlocal
