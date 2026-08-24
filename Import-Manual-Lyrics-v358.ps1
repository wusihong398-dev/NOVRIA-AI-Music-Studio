param(
    [Parameter(Mandatory=$true)][int]$TrackId,
    [Parameter(Mandatory=$true)][string]$File,
    [Parameter(Mandatory=$true)][string]$AdminKey,
    [string]$ServerUrl = "http://127.0.0.1:8001"
)

$ErrorActionPreference = 'Stop'
if (!(Test-Path -LiteralPath $File -PathType Leaf)) {
    throw "歌词文件不存在：$File"
}
$curl = (Get-Command curl.exe -ErrorAction Stop).Source
$url = "$($ServerUrl.TrimEnd('/'))/api/v1/library/mobile/catalog/$TrackId/manual-lyrics"
Write-Host "正在导入人工歌词：TrackId=$TrackId" -ForegroundColor Cyan
& $curl -fS -X POST $url `
  -H "X-Admin-Key: $AdminKey" `
  -F "file=@$File"
if ($LASTEXITCODE -ne 0) {
    throw "人工歌词导入失败，curl exit=$LASTEXITCODE"
}
Write-Host "人工歌词导入完成。重新打开客户端歌曲即可读取新歌词。" -ForegroundColor Green
