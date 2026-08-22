$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root '.venv-mobile-api\Scripts\python.exe'
$ModelDir = Join-Path $Root 'models\bs-roformer'
if (-not (Test-Path $Python)) { throw 'Python environment not found: .venv-mobile-api' }

Write-Host 'Installing the verified Mega53 882000-to-881664 tail-chunk fix...'
& $Python -m tools.patch_bs_roformer_tail_chunk --model-dir $ModelDir
if ($LASTEXITCODE -ne 0) { throw 'Could not patch the BS-RoFormer tail-chunk overlap-add logic.' }

Write-Host 'Verifying the compatible runner, patch identity, CUDA PyTorch and GPU...'
& $Python -m tools.verify_bs_roformer_mega53_runner --model-dir $ModelDir --quick
if ($LASTEXITCODE -ne 0) { throw 'The Mega53 runner compatibility marker is missing.' }
& $Python -m tools.patch_bs_roformer_tail_chunk --model-dir $ModelDir --verify-only
if ($LASTEXITCODE -ne 0) { throw 'The Mega53 tail-chunk patch verification failed.' }
& $Python -c "import torch; assert torch.cuda.is_available(); print('PyTorch:',torch.__version__); print('GPU:',torch.cuda.get_device_name(0))"
if ($LASTEXITCODE -ne 0) { throw 'CUDA PyTorch is unavailable.' }

Write-Host ''
Write-Host 'Mega53 tail-chunk fix v3.3.7 is ready. CUDA, PyTorch and the 1.37 GB model were preserved.'
Read-Host 'Press Enter to close'
