@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-BS-RoFormer-Tail-Fix-v337.ps1"
if errorlevel 1 pause
