param(
  [string]$ServerRoot = 'E:\Dongba-Music-Server',
  [string]$OriginalsRoot = 'H:\juweier-music',
  [string]$ProcessedRoot1 = 'G:\JuweierMusicProcessed',
  [string]$ProcessedRoot2 = 'F:\JuweierMusicProcessed',
  [string]$OutputRoot = 'D:\Juweier-Migration',
  [switch]$IncludeOriginals,
  [switch]$IncludeProcessed
)

$ErrorActionPreference = 'Stop'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$bundle = Join-Path $OutputRoot "Juweier-Music-Server-v3.5.11-Full-Migration-$stamp"
$core = Join-Path $bundle 'core'
$data = Join-Path $bundle 'data'
New-Item -ItemType Directory -Force -Path $core,$data | Out-Null

Write-Host '=== Juweier Music v3.5.11 full migration pack ===' -ForegroundColor Cyan
Write-Host "Bundle: $bundle"

if (-not (Test-Path $ServerRoot)) { throw "Server root missing: $ServerRoot" }

# Stop only the API listener if present so SQLite and product files are copied consistently.
$listener = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
$pid8001 = $null
if ($listener) { $pid8001 = $listener.OwningProcess }
if ($pid8001) {
  Write-Host "Stopping port 8001 process PID $pid8001"
  Stop-Process -Id $pid8001 -Force
  Start-Sleep -Seconds 2
}

# Copy the complete server tree except caches and virtualenvs that should be rebuilt on a new host.
$serverDst = Join-Path $core 'Dongba-Music-Server'
New-Item -ItemType Directory -Force -Path $serverDst | Out-Null
$excludeDirs = @('.venv','.venv-mobile-api','__pycache__','.git','build','dist','release','.pytest_cache')
$excludeFiles = @('*.pyc','*.pyo','*.tmp','*.part','*.log')
$xd = @()
foreach ($dir in $excludeDirs) {
  $xd += '/XD'
  $xd += (Join-Path $ServerRoot $dir)
}
$xf = @()
foreach ($f in $excludeFiles) {
  $xf += '/XF'
  $xf += $f
}
$roboArgs = @($ServerRoot,$serverDst,'/E','/COPY:DAT','/DCOPY:DAT','/R:2','/W:2','/XJ','/NFL','/NDL','/NP') + $xd + $xf
& robocopy @roboArgs | Out-Host
if ($LASTEXITCODE -ge 8) { throw "robocopy core failed with code $LASTEXITCODE" }

# Copy SQLite database plus WAL/SHM if present.
$dbDir = Join-Path $ServerRoot 'database'
if (Test-Path $dbDir) {
  $dbDst = Join-Path $serverDst 'database'
  New-Item -ItemType Directory -Force -Path $dbDst | Out-Null
  Get-ChildItem $dbDir -File -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -like '*.sqlite3' -or $_.Name -like '*.sqlite3-wal' -or $_.Name -like '*.sqlite3-shm' -or $_.Name -like '*.db'
  } | Copy-Item -Destination $dbDst -Force
}

function Get-TreeSummary([string]$Path) {
  if (-not (Test-Path $Path)) {
    return [pscustomobject]@{Path=$Path;Exists=$false;Files=[int64]0;Bytes=[int64]0}
  }
  $m = Get-ChildItem $Path -File -Recurse -ErrorAction SilentlyContinue | Measure-Object Length -Sum
  $sumBytes = [int64]0
  if ($null -ne $m.Sum) { $sumBytes = [int64]$m.Sum }
  return [pscustomobject]@{
    Path = $Path
    Exists = $true
    Files = [int64]$m.Count
    Bytes = $sumBytes
  }
}

$summary = @(
  Get-TreeSummary $ServerRoot
  Get-TreeSummary $OriginalsRoot
  Get-TreeSummary $ProcessedRoot1
  Get-TreeSummary $ProcessedRoot2
)
$summary | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $bundle 'migration_inventory.json')
$summary | ForEach-Object { "{0}`t{1}`t{2}`t{3:N2} GB" -f $_.Path,$_.Exists,$_.Files,($_.Bytes/1GB) } | Set-Content -Encoding UTF8 (Join-Path $bundle 'migration_inventory.txt')

# Save a portable environment map for the restore script.
@{
  version = '3.5.11'
  source_server_root = $ServerRoot
  source_originals_root = $OriginalsRoot
  source_processed_roots = @($ProcessedRoot1,$ProcessedRoot2)
  api_port = 8001
  public_api = 'https://api.db0888.com'
  created_at = (Get-Date).ToString('o')
} | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $bundle 'migration_config.json')

if ($IncludeOriginals -and (Test-Path $OriginalsRoot)) {
  $dst = Join-Path $data 'originals'
  New-Item -ItemType Directory -Force -Path $dst | Out-Null
  & robocopy $OriginalsRoot $dst /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /XJ /NFL /NDL /NP | Out-Host
  if ($LASTEXITCODE -ge 8) { throw "robocopy originals failed with code $LASTEXITCODE" }
}

if ($IncludeProcessed) {
  foreach ($entry in @(@($ProcessedRoot1,'processed_G'),@($ProcessedRoot2,'processed_F'))) {
    $src = $entry[0]
    $name = $entry[1]
    if (Test-Path $src) {
      $dst = Join-Path $data $name
      New-Item -ItemType Directory -Force -Path $dst | Out-Null
      & robocopy $src $dst /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /XJ /NFL /NDL /NP | Out-Host
      if ($LASTEXITCODE -ge 8) { throw "robocopy $src failed with code $LASTEXITCODE" }
    }
  }
}

# Hash important migration files.
$hashTargets = Get-ChildItem $core -File -Recurse -ErrorAction SilentlyContinue | Where-Object {
  $_.Extension -in '.ps1','.py','.json','.yaml','.yml','.toml','.txt','.sqlite3','.db'
}
if ($hashTargets) {
  $hashTargets | Get-FileHash -Algorithm SHA256 | Select-Object Path,Hash | Export-Csv -NoTypeInformation -Encoding UTF8 (Join-Path $bundle 'SHA256SUMS.csv')
}

Write-Host ''
Write-Host 'MIGRATION PACK READY' -ForegroundColor Green
Write-Host $bundle
Write-Host 'Copy this whole folder to the new Windows server. Then run Restore-Full-Migration-v3511.ps1 from the restored server root.'
