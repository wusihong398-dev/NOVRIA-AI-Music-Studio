$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root '.venv-mobile-api\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    throw 'Python environment not found: .venv-mobile-api'
}

$PinnedCommit = 'b0f1386fcced25f559f3e61c9f08a73cd9bddf80'
$DownloadDir = 'D:\anzhuang'
$ArchiveName = "bs-roformer-infer-$PinnedCommit.zip"
$Archive = Join-Path $DownloadDir $ArchiveName
$ArchiveUrl = "https://github.com/openmirlab/bs-roformer-infer/archive/$PinnedCommit.zip"
$ModelDir = Join-Path $Root 'models\bs-roformer'
New-Item -ItemType Directory -Force -Path $DownloadDir, $ModelDir | Out-Null

if (-not (Test-Path $Archive) -or (Get-Item $Archive).Length -lt 100000) {
    Write-Host 'Downloading the small, pinned official BS-RoFormer source archive...'
    & curl.exe -L --fail --retry 20 --retry-all-errors --output $Archive $ArchiveUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Download failed. Download this URL with a browser into D:\anzhuang as $ArchiveName, then run this installer again: $ArchiveUrl"
    }
}

Write-Host 'Installing the compatible runner without replacing CUDA PyTorch...'
& $Python -m pip install --upgrade hatchling
if ($LASTEXITCODE -ne 0) { throw 'Could not install the small Hatchling build tool.' }
& $Python -m pip install --force-reinstall --no-deps --no-build-isolation $Archive
if ($LASTEXITCODE -ne 0) { throw 'Could not install the pinned BS-RoFormer runner.' }

Write-Host 'Running the Mega53 registry and mlp_expansion_factor architecture probe...'
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $ModelDir 'bs-roformer-mega53-runner-ready.json')
& $Python -m tools.verify_bs_roformer_mega53_runner --model-dir $ModelDir --write-marker
if ($LASTEXITCODE -ne 0) { throw 'BS-RoFormer Mega53 architecture probe failed.' }

Write-Host 'Confirming that CUDA PyTorch was preserved...'
& $Python -c "import torch; assert torch.cuda.is_available(); print('PyTorch:',torch.__version__); print('GPU:',torch.cuda.get_device_name(0))"
if ($LASTEXITCODE -ne 0) { throw 'CUDA PyTorch is not available after runner installation.' }

Write-Host ''
Write-Host 'BS-RoFormer Mega53 runner is compatible. Existing 1.37 GB model files were kept.'
Read-Host 'Press Enter to close'
