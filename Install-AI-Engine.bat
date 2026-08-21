@echo off
chcp 65001 >nul
title 橘味儿音乐 - AI 引擎安装程序
cd /d "%~dp0"

echo ============================================================
echo 橘味儿音乐 v3.2.8 UVR AI 引擎安装
echo ============================================================

where py >nul 2>nul
if errorlevel 1 (
  echo.
  echo 没有检测到 Python Launcher。
  echo 请安装 Python 3.10 或 3.11 x64，并勾选 Add Python to PATH。
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] 创建 Python 虚拟环境...
  py -3.11 -m venv .venv 2>nul
  if errorlevel 1 py -3.10 -m venv .venv
)

if not exist ".venv\Scripts\python.exe" (
  echo 创建虚拟环境失败。建议安装 Python 3.11 x64。
  pause
  exit /b 1
)

echo [2/4] 更新 pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel

echo [3/4] 安装桌面、服务器和 UVR 音频依赖...
".venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-server.txt

echo [4/4] 检查 UVR/audio-separator 与 Demucs...

echo.
echo 检查 Demucs...
".venv\Scripts\python.exe" -m demucs.separate --help >nul 2>nul
if errorlevel 1 (
  echo.
  echo Demucs 安装检查失败。
  echo 原版 Demucs 对较新的 PyTorch/Python 组合可能存在兼容限制。
  echo 请把此窗口最后的错误截图发给我，我会按你的电脑环境生成专用修复版。
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -c "from audio_separator.separator import Separator; print('UVR audio-separator ready')"
if errorlevel 1 (
  echo UVR audio-separator 安装检查失败。
  pause
  exit /b 1
)

echo.
echo ============================================================
echo 安装完成。
echo 现在可以双击 Run-Juweier-Music.bat 启动。
echo 第一次执行分轨时会由 UVR audio-separator 自动下载 htdemucs_6s 模型。
echo ============================================================
pause
