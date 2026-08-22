$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
Write-Host "=== Juweier Music v3.5.0 Performance Library Windows Build ==="

python -m pip install --upgrade pip setuptools wheel

# CPU PyTorch keeps the portable build compatible with Windows computers that do
# not have an NVIDIA GPU or a matching CUDA runtime.
python -m pip install --upgrade torch torchaudio --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-build.txt
python -m pip install imageio-ffmpeg

# Verify every module used by the isolated worker before PyInstaller starts.
python -c "import torch, soundfile, librosa; import demucs.api; from audio_separator.separator import Separator; print('Torch', torch.__version__); print('CUDA runtime', torch.version.cuda); print('UVR worker imports ready')"

python -m PyInstaller --noconfirm --clean NOVRIA.spec

$dist = "dist\Juweier-Music"
New-Item -ItemType Directory -Force -Path "$dist\stems","$dist\projects","$dist\exports","$dist\temp","$dist\ai_models","$dist\logs","$dist\imports" | Out-Null

# Bundle the imageio-ffmpeg binary. This avoids relying on the intermittent
# third-party Gyan ZIP endpoint during a release build.
$ffmpegRoot = Join-Path $dist "tools\ffmpeg"
New-Item -ItemType Directory -Force -Path $ffmpegRoot | Out-Null
python -c "import imageio_ffmpeg, pathlib, shutil; target=pathlib.Path(r'$ffmpegRoot')/'ffmpeg.exe'; shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), target); print('Bundled FFmpeg:', target)"

if (!(Test-Path "$dist\tools\ffmpeg\ffmpeg.exe")) { throw "Bundled FFmpeg missing" }
Write-Host "EXE: $dist\Juweier-Music.exe"
Write-Host "CPU-compatible PyTorch and FFmpeg packaged successfully."
