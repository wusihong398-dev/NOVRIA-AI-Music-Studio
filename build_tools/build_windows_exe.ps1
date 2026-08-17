$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
Write-Host "=== Juweier Music v3.0.0 Complete Windows EXE Build ==="

python -m pip install --upgrade pip setuptools wheel

# CPU PyTorch keeps the portable build compatible with Windows computers that do
# not have an NVIDIA GPU or a matching CUDA runtime.
python -m pip install --upgrade torch torchaudio --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-build.txt

# Verify PyTorch imports before PyInstaller starts.
python -c "import torch; print('Torch', torch.__version__); print('CUDA runtime', torch.version.cuda); print('CPU compatible build ready')"

python -m PyInstaller --noconfirm --clean NOVRIA.spec

$dist = "dist\Juweier-Music"
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
Write-Host "EXE: $dist\Juweier-Music.exe"
Write-Host "CPU-compatible PyTorch and FFmpeg packaged successfully."
