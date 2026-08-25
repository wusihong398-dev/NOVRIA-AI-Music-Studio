$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host '===== 橘味儿音乐 v3.5.11 手机轻量分轨生成 =====' -ForegroundColor Cyan
Write-Host '不会删除 WAV 原分轨，只新增 mobile_streams/*.m4a 并登记到成品库。'

$pythonCandidates = @(
  "$root\.venv-mobile-api\Scripts\python.exe",
  "$root\.venv\Scripts\python.exe",
  "python"
)
$python = $null
foreach ($candidate in $pythonCandidates) {
  if ($candidate -eq 'python') {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $python = $cmd.Source; break }
  } elseif (Test-Path $candidate) {
    $python = $candidate; break
  }
}
if (-not $python) { throw '没有找到 Python 运行环境。' }

$env:PYTHONUTF8 = '1'
if (-not $env:JUWEIER_DATA_DIR) { $env:JUWEIER_DATA_DIR = $root }

& $python "$root\tools\generate_mobile_stems_v3511.py"
if ($LASTEXITCODE -ne 0) {
  throw "手机轻量分轨生成未完全成功，退出码：$LASTEXITCODE"
}

Write-Host ''
Write-Host '完成。现在 v3.5.11 手机客户端会优先使用体积更小的 M4A 分轨。' -ForegroundColor Green
