param(
  [Parameter(Mandatory=$true)][string]$BundleRoot,
  [string]$TargetServerRoot = 'E:\Dongba-Music-Server',
  [string]$TargetOriginalsRoot = 'H:\juweier-music',
  [string]$TargetProcessedRoot1 = 'G:\JuweierMusicProcessed',
  [string]$TargetProcessedRoot2 = 'F:\JuweierMusicProcessed',
  [switch]$RestoreData
)
$ErrorActionPreference = 'Stop'
$core = Join-Path $BundleRoot 'core\Dongba-Music-Server'
if (-not (Test-Path $core)) { throw "Missing core folder: $core" }
New-Item -ItemType Directory -Force -Path $TargetServerRoot | Out-Null
Copy-Item (Join-Path $core '*') $TargetServerRoot -Recurse -Force
if ($RestoreData) {
  $map = @(
    @((Join-Path $BundleRoot 'data\originals'),$TargetOriginalsRoot),
    @((Join-Path $BundleRoot 'data\processed_G'),$TargetProcessedRoot1),
    @((Join-Path $BundleRoot 'data\processed_F'),$TargetProcessedRoot2)
  )
  foreach ($pair in $map) {
    if (Test-Path $pair[0]) {
      New-Item -ItemType Directory -Force -Path $pair[1] | Out-Null
      Copy-Item (Join-Path $pair[0] '*') $pair[1] -Recurse -Force
    }
  }
}
$startPath = Join-Path $TargetServerRoot 'Start-Juweier-Server-Migrated-v3511.ps1'
$lines = @(
  '$ErrorActionPreference = ''Stop''',
  "`$Root = '$TargetServerRoot'",
  'Set-Location $Root',
  '`$Python = Join-Path `$Root ''.venv-mobile-api\Scripts\python.exe''',
  'if (-not (Test-Path $Python)) { throw ''Create .venv-mobile-api and install requirements before starting.'' }',
  '`$env:PYTHONUTF8 = ''1''',
  '`$env:JUWEIER_DATA_DIR = `$Root',
  '`$env:JUWEIER_LIBRARY_DIR = `$Root',
  "`$env:JUWEIER_SERVER_LIBRARY_ROOTS = '$TargetOriginalsRoot'",
  '`$env:JUWEIER_LIBRARY_DB = Join-Path `$Root ''database\juweier_music_library.sqlite3''',
  "`$env:JUWEIER_PROCESSED_DIR = '$TargetProcessedRoot1'",
  "`$env:JUWEIER_PROCESSED_ROOTS = '$TargetProcessedRoot1;$TargetProcessedRoot2'",
  '`$env:JUWEIER_AUTO_SCAN_LIBRARY = ''0''',
  '`$env:JUWEIER_WORKERS = ''1''',
  '& $Python -m uvicorn server.mobile_api:app --host 0.0.0.0 --port 8001 --proxy-headers --forwarded-allow-ips=''*'''
)
[System.IO.File]::WriteAllLines($startPath,$lines,(New-Object System.Text.UTF8Encoding($false)))
Write-Host 'RESTORE FILES COMPLETE' -ForegroundColor Green
Write-Host "Server: $TargetServerRoot"
Write-Host "Start script: $startPath"
Write-Host 'Next: create Python venv, install requirements, then run the generated start script.'
