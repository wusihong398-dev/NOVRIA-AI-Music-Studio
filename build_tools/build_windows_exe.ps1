$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
Write-Host "=== NOVRIA AI Music Studio v2.1.3 CUDA Windows EXE Build ==="

python -m pip install --upgrade pip setuptools wheel

# CUDA 12.8 PyTorch build for RTX 30/40/50 series.
# Do not run pip uninstall here: on a clean GitHub runner, pip's 'not installed' warning
# is promoted by Windows PowerShell to NativeCommandError when ErrorActionPreference=Stop.
python -m pip install --upgrade --force-reinstall torch==2.11.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
python -m pip install -r requirements-build.txt

# Verify the build environment is CUDA-enabled before PyInstaller starts.
python -c "import torch; print('Torch', torch.__version__); print('CUDA runtime', torch.version.cuda); assert torch.version.cuda is not None"

python -m PyInstaller --noconfirm --clean NOVRIA.spec

$dist = "dist\NOVRIA-AI-Music-Studio"
New-Item -ItemType Directory -Force -Path "$dist\stems","$dist\projects","$dist\exports","$dist\temp","$dist\ai_models","$dist\logs","$dist\imports" | Out-Null

# Bundle FFmpeg for universal audio import.
$ffmpegRoot = Join-Path $dist "tools\ffmpeg"
New-Item -ItemType Directory -Force -Path $ffmpegRoot | Out-Null
$ffmpegZip = Join-Path $env:RUNNER_TEMP "ffmpeg-release-essentials.zip"
$ffmpegExtract = Join-Path $env:RUNNER_TEMP "ffmpeg-extract"
Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $ffmpegZip
Expand-Archive -Path $ffmpegZip -DestinationPath $ffmpegExtract -Force
$ffmpegExe = Get-ChildItem -Path $ffmpegExtract -Filter ffmpeg.exe -Recurse | Select-Object -First 1
$ffprobeExe = Get-ChildItem -Path $ffmpegExtract -Filter ffprobe.exe -Recurse | Select-Object -First 1
if (-not $ffmpegExe) { throw "FFmpeg download/extract failed" }
Copy-Item $ffmpegExe.FullName (Join-Path $ffmpegRoot "ffmpeg.exe") -Force
if ($ffprobeExe) { Copy-Item $ffprobeExe.FullName (Join-Path $ffmpegRoot "ffprobe.exe") -Force }

if (!(Test-Path "$dist\tools\ffmpeg\ffmpeg.exe")) { throw "Bundled FFmpeg missing" }
Write-Host "EXE: $dist\NOVRIA-AI-Music-Studio.exe"
Write-Host "CUDA-enabled PyTorch and FFmpeg packaged successfully."
