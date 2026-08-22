$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Python = Join-Path $Root '.venv-mobile-api\Scripts\python.exe'
$Source = 'H:\juweier-music'
$ManifestFolder = Join-Path $Root 'manifests'
$Log = Join-Path $ManifestFolder ("H-full-preflight-v350-{0}.txt" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

if (-not (Test-Path $Python)) { throw 'Python environment not found: .venv-mobile-api' }
if (-not (Test-Path $Source)) { throw "Original song folder not found: $Source" }
$health = Invoke-RestMethod 'http://127.0.0.1:8001/api/v1/library/mobile/health'
if ($health.version -ne '3.5.0') { throw "Start v3.5.0 server first. Current version: $($health.version)" }
if (-not $health.processing_ready) { throw "AI runtime is not ready: $($health.runtime.issues -join '; ')" }
if (@($health.processed_library_roots).Count -lt 2) { throw 'G/F multi-disk product roots are not active.' }
$status = Invoke-RestMethod 'http://127.0.0.1:8001/api/v1/library/batch/status'
if ($status.running) { throw 'A batch is already running.' }

New-Item -ItemType Directory -Force -Path $ManifestFolder | Out-Null
$env:PYTHONUTF8 = '1'
Write-Host 'Recursively checking every audio file under H:\juweier-music...'
& $Python -m tools.prepare_server_batch --source $Source --data $Root --pilot 100000 2>&1 |
    Tee-Object -FilePath $Log
if ($LASTEXITCODE -ne 0) { throw "Preflight failed. See: $Log" }

$started = Invoke-RestMethod -Method Post 'http://127.0.0.1:8001/api/v1/library/batch/start?limit=0'
Write-Host "Full batch started. Pending: $($started.counts.pending)"
Write-Host 'G is used first, then F. Processing pauses safely when both reach the reserve line.'
Write-Host "Preflight log: $Log"
