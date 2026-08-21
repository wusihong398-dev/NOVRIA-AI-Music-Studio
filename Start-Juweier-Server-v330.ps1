$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$PythonCandidates = @(
    (Join-Path $Root '.venv-mobile-api\Scripts\python.exe'),
    (Join-Path $Root '.venv\Scripts\python.exe')
)
$Python = $PythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Python) {
    throw 'Python environment not found. Install the server requirements first.'
}

$Ffmpeg = Join-Path $Root 'ffmpeg\bin'
if (Test-Path (Join-Path $Ffmpeg 'ffmpeg.exe')) {
    $env:PATH = "$Ffmpeg;$env:PATH"
}

$env:PYTHONUTF8 = '1'
$env:JUWEIER_DATA_DIR = $Root
$env:JUWEIER_LIBRARY_DIR = 'G:\JuweierMusicLibrary'
$env:JUWEIER_SERVER_LIBRARY_ROOTS = 'G:\JuweierMusicLibrary\01_Originals'
$env:JUWEIER_LIBRARY_DB = Join-Path $Root 'database\juweier_music_library.sqlite3'
$env:JUWEIER_PROCESSED_DIR = 'H:\JuweierAI\03_AI_Processed'
$env:JUWEIER_UVR_MODEL_DIR = Join-Path $Root 'models\uvr'
$env:JUWEIER_AUTO_SCAN_LIBRARY = '1'
$env:JUWEIER_CATALOG_WATCH_INTERVAL = '900'

Write-Host 'Juweier Music v3.3.0 server starting on port 8001'
Write-Host "Originals: $env:JUWEIER_SERVER_LIBRARY_ROOTS"
Write-Host "AI results: $env:JUWEIER_PROCESSED_DIR"
Write-Host "Catalog DB: $env:JUWEIER_LIBRARY_DB"

& $Python -m uvicorn server.mobile_api:app --host 0.0.0.0 --port 8001 --proxy-headers --forwarded-allow-ips='*'
