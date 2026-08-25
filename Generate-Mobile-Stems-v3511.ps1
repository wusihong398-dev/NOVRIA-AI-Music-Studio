$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host '===== Juweier Music v3.5.11 Mobile Stem Generator =====' -ForegroundColor Cyan
Write-Host 'Keeps original WAV stems. Adds mobile_streams/*.m4a and updates product artifacts.'

$pythonCandidates = @(
  "$root\.venv-mobile-api\Scripts\python.exe",
  "$root\.venv\Scripts\python.exe",
  'python'
)

$python = $null
foreach ($candidate in $pythonCandidates) {
  if ($candidate -eq 'python') {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
      $python = $cmd.Source
      break
    }
  }
  elseif (Test-Path $candidate) {
    $python = $candidate
    break
  }
}

if (-not $python) {
  throw 'Python runtime not found.'
}

$env:PYTHONUTF8 = '1'
if (-not $env:JUWEIER_DATA_DIR) {
  $env:JUWEIER_DATA_DIR = $root
}

Write-Host "Python: $python"
Write-Host "Server root: $root"

& $python "$root\tools\generate_mobile_stems_v3511.py"
if ($LASTEXITCODE -ne 0) {
  throw "Mobile stem generation failed. Exit code: $LASTEXITCODE"
}

Write-Host ''
Write-Host 'DONE. v3.5.11 mobile clients can now prefer lightweight M4A stems.' -ForegroundColor Green
