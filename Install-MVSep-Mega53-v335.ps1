$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root '.venv-mobile-api\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    throw 'Python environment not found: .venv-mobile-api'
}

$ModelDir = Join-Path $Root 'models\bs-roformer'
$DownloadDir = 'D:\anzhuang'
$CheckpointName = 'mvsep_mega_model_bs_roformer_53_stems_v1.ckpt'
$ConfigName = 'mvsep_mega_model_bs_roformer_53_stems.yaml'
$CheckpointUrl = 'https://github.com/ZFTurbo/Music-Source-Separation-Training/releases/download/v1.0.21/mvsep_mega_model_bs_roformer_53_stems_v1.ckpt'
$ConfigUrl = 'https://github.com/ZFTurbo/Music-Source-Separation-Training/releases/download/v1.0.21/mvsep_mega_model_bs_roformer_53_stems.yaml'
New-Item -ItemType Directory -Force -Path $ModelDir, $DownloadDir | Out-Null

function Get-Asset([string]$Name, [string]$Url, [long]$ExpectedSize) {
    $Target = Join-Path $ModelDir $Name
    if ((Test-Path $Target) -and ((Get-Item $Target).Length -eq $ExpectedSize)) {
        return $Target
    }
    $Cached = Join-Path $DownloadDir $Name
    if ((Test-Path $Cached) -and ((Get-Item $Cached).Length -gt $ExpectedSize)) {
        Remove-Item -Force $Cached
    }
    if (-not (Test-Path $Cached) -or (Get-Item $Cached).Length -ne $ExpectedSize) {
        Write-Host "Downloading official asset (resumable): $Name"
        & curl.exe -L --fail --retry 20 --retry-all-errors --continue-at - --output $Cached $Url
        if ($LASTEXITCODE -ne 0) {
            throw "Download failed. Download this URL with a browser into D:\anzhuang, then run this installer again: $Url"
        }
    }
    Copy-Item -Force $Cached $Target
    return $Target
}

Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $ModelDir 'mvsep-mega53-ready.json')
Get-Asset $CheckpointName $CheckpointUrl 1368919887 | Out-Null
Get-Asset $ConfigName $ConfigUrl 4184 | Out-Null

Write-Host 'Verifying official file sizes and SHA256. This can take several minutes...'
& $Python -m tools.verify_mvsep_mega53_assets --model-dir $ModelDir --write-marker
if ($LASTEXITCODE -ne 0) { throw 'MVSep Mega 53-Stems verification failed.' }

Write-Host ''
Write-Host 'MVSep Mega 53-Stems is verified and ready for the three-song pilot.'
Write-Host 'The old fake ready marker has been replaced by verified asset metadata.'
Read-Host 'Press Enter to close'
