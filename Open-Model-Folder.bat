@echo off
chcp 65001 >nul
title NOVRIA AI Music Studio - 模型目录
cd /d "%~dp0"
echo NOVRIA 模型缓存目录：
echo.
if exist "ai_models" (
  explorer "%cd%\ai_models"
) else (
  mkdir ai_models
  explorer "%cd%\ai_models"
)
