$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root '.venv-mobile-api\Scripts\python.exe'
$ModelDir = Join-Path $Root 'models\bs-roformer'
if (-not (Test-Path $Python)) { throw 'Python environment not found: .venv-mobile-api' }

Write-Host 'Installing the RTX 3060 low-VRAM CUDA patch...'
& $Python -m tools.patch_bs_roformer_tail_chunk --model-dir $ModelDir --verify-only
if ($LASTEXITCODE -ne 0) { throw 'Run Install-BS-RoFormer-Tail-Fix-v337.cmd first.' }
& $Python -m tools.patch_bs_roformer_low_vram --model-dir $ModelDir
if ($LASTEXITCODE -ne 0) { throw 'Could not install the low-VRAM CUDA patch.' }

Write-Host 'Verifying patch identity, CUDA PyTorch and GPU...'
& $Python -m tools.patch_bs_roformer_low_vram --model-dir $ModelDir --verify-only
if ($LASTEXITCODE -ne 0) { throw 'The low-VRAM CUDA patch verification failed.' }
& $Python -c "import torch; assert torch.cuda.is_available(); print('PyTorch:',torch.__version__); print('GPU:',torch.cuda.get_device_name(0))"
if ($LASTEXITCODE -ne 0) { throw 'CUDA PyTorch is unavailable.' }

Write-Host ''
Write-Host 'v3.3.8 low-VRAM runner is ready. CUDA, PyTorch and the 1.37 GB model were preserved.'
Write-Host 'Full-song overlap-add now uses system RAM. CPU fallback is disabled.'
Read-Host 'Press Enter to close'
