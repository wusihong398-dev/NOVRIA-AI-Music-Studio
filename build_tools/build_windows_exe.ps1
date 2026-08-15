$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
Write-Host "=== NOVRIA AI Music Studio Windows EXE Build ==="
python -m pip install --upgrade pip setuptools wheel
# CPU PyTorch keeps the portable test package smaller and works on machines without NVIDIA.
python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-build.txt
# imageio-ffmpeg provides a redistributable Windows ffmpeg binary for the portable package.
python -m pip install imageio-ffmpeg
python -m PyInstaller --noconfirm --clean NOVRIA.spec

$dist = "dist\NOVRIA-AI-Music-Studio"
New-Item -ItemType Directory -Force -Path "$dist\stems","$dist\projects","$dist\exports","$dist\temp","$dist\ai_models","$dist\tools\ffmpeg" | Out-Null

$ffmpegExe = (python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())").Trim()
if (!(Test-Path $ffmpegExe)) { throw "Bundled FFmpeg source not found: $ffmpegExe" }
Copy-Item -Force $ffmpegExe "$dist\tools\ffmpeg\ffmpeg.exe"
if (!(Test-Path "$dist\tools\ffmpeg\ffmpeg.exe")) { throw "FFmpeg was not copied into the Windows package" }

Write-Host "EXE: $dist\NOVRIA-AI-Music-Studio.exe"
Write-Host "FFmpeg: $dist\tools\ffmpeg\ffmpeg.exe"
