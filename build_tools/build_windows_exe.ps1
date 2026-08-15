$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
Write-Host "=== NOVRIA AI Music Studio Windows EXE Build ==="
python -m pip install --upgrade pip setuptools wheel
# CPU PyTorch keeps the portable test package smaller and works on machines without NVIDIA.
python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean NOVRIA.spec
New-Item -ItemType Directory -Force -Path "dist\NOVRIA-AI-Music-Studio\stems","dist\NOVRIA-AI-Music-Studio\projects","dist\NOVRIA-AI-Music-Studio\exports","dist\NOVRIA-AI-Music-Studio\temp","dist\NOVRIA-AI-Music-Studio\ai_models" | Out-Null
Write-Host "EXE: dist\NOVRIA-AI-Music-Studio\NOVRIA-AI-Music-Studio.exe"
