$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root '.venv-mobile-api\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'Python environment not found: .venv-mobile-api' }
$Ffmpeg = Join-Path $Root 'ffmpeg\bin'
if (Test-Path (Join-Path $Ffmpeg 'ffmpeg.exe')) { $env:PATH = "$Ffmpeg;$env:PATH" }

$env:PYTHONUTF8 = '1'
$env:JUWEIER_DATA_DIR = $Root
$env:JUWEIER_LIBRARY_DIR = $Root
$env:JUWEIER_SERVER_LIBRARY_ROOTS = 'D:\MP3'
$env:JUWEIER_LIBRARY_DB = Join-Path $Root 'database\juweier_music_library.sqlite3'
$env:JUWEIER_PROCESSED_DIR = 'G:\JuweierMusicProcessed'
$env:JUWEIER_UVR_MODEL_DIR = Join-Path $Root 'models\uvr'
$env:JUWEIER_BS_ROFORMER_MODEL_DIR = Join-Path $Root 'models\bs-roformer'
$env:JUWEIER_BS_ROFORMER_MODEL_PATH = Join-Path $env:JUWEIER_BS_ROFORMER_MODEL_DIR 'mvsep_mega_model_bs_roformer_53_stems_v1.ckpt'
$env:JUWEIER_BS_ROFORMER_CONFIG_PATH = Join-Path $env:JUWEIER_BS_ROFORMER_MODEL_DIR 'mvsep_mega_model_bs_roformer_53_stems.yaml'
$env:JUWEIER_AUTO_SCAN_LIBRARY = '0'
$env:JUWEIER_MIN_FREE_RATIO = '0.15'
$env:JUWEIER_WORKERS = '1'
$env:JUWEIER_BASE_SIX_STEM_ENGINE = 'demucs-direct'
$env:JUWEIER_ELECTRIC_GUITAR_ENGINE = 'mvsep-mega53'
$env:JUWEIER_ELECTRIC_GUITAR_MODEL = 'roformer-model-bs-roformer-mvsep-mega-53-stems'

& $Python -m tools.verify_mvsep_mega53_assets --model-dir $env:JUWEIER_BS_ROFORMER_MODEL_DIR --quick
if ($LASTEXITCODE -ne 0) {
    throw 'MVSep Mega 53-Stems assets are not verified. Run Install-MVSep-Mega53-v335.cmd.'
}

Write-Host 'Juweier Music v3.3.5 server pilot starting on port 8001'
Write-Host 'Base six stems: direct Demucs htdemucs_6s with validated PCM WAV'
Write-Host 'Dedicated guitars: MVSep Mega 53-Stems via explicit verified checkpoint/config paths'
Write-Host "Pilot originals: $env:JUWEIER_SERVER_LIBRARY_ROOTS"
Write-Host "Published products: $env:JUWEIER_PROCESSED_DIR\01_Ready"

& $Python -m uvicorn server.mobile_api:app --host 0.0.0.0 --port 8001 --proxy-headers --forwarded-allow-ips='*'
