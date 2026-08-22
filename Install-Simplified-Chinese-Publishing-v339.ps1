$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root '.venv-mobile-api\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'Python environment not found: .venv-mobile-api' }

Write-Host 'Stopping the server on port 8001 before the catalog migration...'
Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

$Wheel = Get-ChildItem (Join-Path $Root 'wheels\opencc_python_reimplemented-*.whl') |
    Select-Object -First 1
if (-not $Wheel) { throw 'Bundled OpenCC wheel was not found.' }

Write-Host 'Installing the bundled Traditional-to-Simplified converter...'
& $Python -m pip install --no-deps --upgrade $Wheel.FullName
if ($LASTEXITCODE -ne 0) { throw 'OpenCC installation failed.' }

# Use Unicode escapes so Windows PowerShell 5 never decodes the verification
# characters through the current ANSI code page.
& $Python -c "from opencc import OpenCC; assert OpenCC('t2s').convert('\u7121\u8cf4') == '\u65e0\u8d56'; print('OpenCC: OK')"
if ($LASTEXITCODE -ne 0) { throw 'OpenCC conversion verification failed.' }

Write-Host 'Backing up the catalog and migrating published products to Simplified Chinese...'
& $Python -m tools.migrate_ready_library_simplified `
    --database (Join-Path $Root 'database\juweier_music_library.sqlite3') `
    --processed-root 'G:\JuweierMusicProcessed' `
    --apply
if ($LASTEXITCODE -ne 0) { throw 'Published-library Simplified Chinese migration failed.' }

Write-Host ''
Write-Host 'v3.3.9 Simplified Chinese publishing is installed.'
Write-Host 'Existing published folders, catalog labels, lyrics and score text were migrated.'
Write-Host 'Original source paths on D: were preserved.'
Read-Host 'Press Enter to close'
