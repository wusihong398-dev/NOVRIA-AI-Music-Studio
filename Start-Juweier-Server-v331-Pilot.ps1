$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root '.venv-mobile-api\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    throw 'Python environment not found: .venv-mobile-api'
}
$Ffmpeg = Join-Path $Root 'ffmpeg\bin'
if (Test-Path (Join-Path $Ffmpeg 'ffmpeg.exe')) {
    $env:PATH = "$Ffmpeg;$env:PATH"
}

$env:PYTHONUTF8 = '1'
$env:JUWEIER_DATA_DIR = $Root
$env:JUWEIER_LIBRARY_DIR = $Root
$env:JUWEIER_SERVER_LIBRARY_ROOTS = 'D:\MP3'
$env:JUWEIER_LIBRARY_DB = Join-Path $Root 'database\juweier_music_library.sqlite3'
$env:JUWEIER_PROCESSED_DIR = 'G:\JuweierMusicProcessed'
$env:JUWEIER_UVR_MODEL_DIR = Join-Path $Root 'models\uvr'
$env:JUWEIER_AUTO_SCAN_LIBRARY = '0'
$env:JUWEIER_MIN_FREE_RATIO = '0.15'
$env:JUWEIER_WORKERS = '1'

$ModelMarker = Join-Path $env:JUWEIER_UVR_MODEL_DIR 'electric-guitar-model.json'
if (Test-Path $ModelMarker) {
    $ModelInfo = Get-Content $ModelMarker -Raw -Encoding UTF8 | ConvertFrom-Json
    $env:JUWEIER_ELECTRIC_GUITAR_MODEL = [string]$ModelInfo.filename
    $env:JUWEIER_ELECTRIC_GUITAR_PRIMARY_STEM = if ($ModelInfo.target_stem) { [string]$ModelInfo.target_stem } else { 'Guitar' }
    $env:JUWEIER_ELECTRIC_GUITAR_COMPLEMENT_STEM = 'Instrumental'
} else {
    Remove-Item Env:JUWEIER_ELECTRIC_GUITAR_MODEL -ErrorAction SilentlyContinue
    Write-Warning 'Electric-guitar UVR model is not prepared. Batch processing will remain blocked.'
}

Write-Host 'Juweier Music server pilot starting on port 8001'
Write-Host "Pilot originals: $env:JUWEIER_SERVER_LIBRARY_ROOTS"
Write-Host "Published products: $env:JUWEIER_PROCESSED_DIR\01_Ready"
Write-Host "Catalog DB: $env:JUWEIER_LIBRARY_DB"
Write-Host "Electric Guitar UVR: $env:JUWEIER_ELECTRIC_GUITAR_MODEL"

& $Python -m uvicorn server.mobile_api:app --host 0.0.0.0 --port 8001 --proxy-headers --forwarded-allow-ips='*'
