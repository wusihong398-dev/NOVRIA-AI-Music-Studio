@echo off
chcp 65001 >nul
title 橘味儿音乐 GPU 检测
cd /d "%~dp0"
echo ============================================================
echo 橘味儿音乐 - NVIDIA GPU / CUDA 检测
echo ============================================================
echo.
where nvidia-smi >nul 2>nul
if errorlevel 1 (
  echo [未检测到] nvidia-smi
  echo 如果电脑没有 NVIDIA 显卡，可以继续使用 CPU 测试。
  echo 如果有 NVIDIA 显卡，请先安装官方 NVIDIA 驱动。
) else (
  echo [检测到 NVIDIA GPU]
  nvidia-smi
)
echo.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import torch; print('PyTorch:',torch.__version__); print('CUDA available:',torch.cuda.is_available()); print('GPU:',torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU mode')"
) else (
  echo 尚未安装橘味儿音乐 AI 引擎，请先运行 Install-AI-Engine.bat
)
echo.
pause
