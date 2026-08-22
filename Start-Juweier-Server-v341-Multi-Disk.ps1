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
$env:JUWEIER_SERVER_LIBRARY_ROOTS = 'H:\juweier-music'
$env:JUWEIER_LIBRARY_DB = Join-Path $Root 'database\juweier_music_library.sqlite3'
$env:JUWEIER_PROCESSED_DIR = 'G:\JuweierMusicProcessed'
$env:JUWEIER_PROCESSED_ROOTS = 'G:\JuweierMusicProcessed;F:\JuweierMusicProcessed'
$env:JUWEIER_MIN_FREE_RATIO = '0.15'
$env:JUWEIER_MIN_FREE_GB = '30'
$env:JUWEIER_PUBLISH_HEADROOM_GB = '3'
$env:JUWEIER_UVR_MODEL_DIR = Join-Path $Root 'models\uvr'
$env:JUWEIER_BS_ROFORMER_MODEL_DIR = Join-Path $Root 'models\bs-roformer'
$env:JUWEIER_BS_ROFORMER_MODEL_PATH = Join-Path $env:JUWEIER_BS_ROFORMER_MODEL_DIR 'mvsep_mega_model_bs_roformer_53_stems_v1.ckpt'
$env:JUWEIER_BS_ROFORMER_CONFIG_PATH = Join-Path $env:JUWEIER_BS_ROFORMER_MODEL_DIR 'mvsep_mega_model_bs_roformer_53_stems.yaml'
$env:JUWEIER_AUTO_SCAN_LIBRARY = '0'
$env:JUWEIER_CATALOG_WATCH_INTERVAL = '900'
$env:JUWEIER_WORKERS = '1'
$env:JUWEIER_BASE_SIX_STEM_ENGINE = 'demucs-direct'
$env:JUWEIER_ELECTRIC_GUITAR_ENGINE = 'mvsep-mega53'
$env:JUWEIER_ELECTRIC_GUITAR_MODEL = 'roformer-model-bs-roformer-mvsep-mega-53-stems'
$env:JUWEIER_MEGA53_TIMEOUT_SECONDS = '7200'

& $Python -c "from opencc import OpenCC; assert OpenCC('t2s').convert('\u7121\u8cf4') == '\u65e0\u8d56'"
if ($LASTEXITCODE -ne 0) { throw 'Run Install-Simplified-Chinese-Publishing-v339.cmd first.' }
& $Python -m tools.verify_mvsep_mega53_assets --model-dir $env:JUWEIER_BS_ROFORMER_MODEL_DIR --quick
if ($LASTEXITCODE -ne 0) { throw 'MVSep Mega53 model assets are not verified.' }
& $Python -m tools.verify_bs_roformer_mega53_runner --model-dir $env:JUWEIER_BS_ROFORMER_MODEL_DIR --quick
if ($LASTEXITCODE -ne 0) { throw 'Run Install-BS-RoFormer-Mega53-v336.cmd first.' }
& $Python -m tools.patch_bs_roformer_tail_chunk --model-dir $env:JUWEIER_BS_ROFORMER_MODEL_DIR --verify-only
if ($LASTEXITCODE -ne 0) { throw 'Run Install-BS-RoFormer-Tail-Fix-v337.cmd first.' }
& $Python -m tools.patch_bs_roformer_low_vram --model-dir $env:JUWEIER_BS_ROFORMER_MODEL_DIR --verify-only
if ($LASTEXITCODE -ne 0) { throw 'Run Install-BS-RoFormer-Low-VRAM-v338.cmd first.' }

Write-Host 'Juweier Music v3.4.1 multi-disk product server starting on port 8001'
Write-Host 'Originals: H:\juweier-music'
Write-Host 'Products: G first, F second; each disk keeps at least 15% and 30 GB free.'
Write-Host 'If both disks reach the reserve line, pending jobs pause; published songs stay online.'

& $Python -m uvicorn server.mobile_api:app --host 0.0.0.0 --port 8001 --proxy-headers --forwarded-allow-ips='*'
