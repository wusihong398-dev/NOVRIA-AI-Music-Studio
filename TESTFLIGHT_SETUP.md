# 橘味儿音乐 TestFlight 配置

当前工作流：`.github/workflows/build-ios-testflight-v3510.yml`

## GitHub Secrets

在仓库 `Settings -> Secrets and variables -> Actions` 中配置：

- `APPLE_TEAM_ID`：Apple Developer Team ID
- `IOS_BUNDLE_ID`：App Store Connect 中橘味儿音乐的 Bundle ID
- `IOS_P12_BASE64`：Apple Distribution 证书导出的 `.p12` 文件 Base64
- `IOS_P12_PASSWORD`：`.p12` 导出密码
- `IOS_PROVISIONING_PROFILE_BASE64`：App Store Distribution / App Store Connect provisioning profile 的 `.mobileprovision` Base64
- `APP_STORE_CONNECT_API_KEY_ID`：App Store Connect API Key ID
- `APP_STORE_CONNECT_ISSUER_ID`：App Store Connect Issuer ID
- `APP_STORE_CONNECT_API_KEY_P8_BASE64`：`AuthKey_XXXXXXXXXX.p8` 文件 Base64

## Windows PowerShell 生成 Base64

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes('C:\path\distribution.p12')) | Set-Clipboard
[Convert]::ToBase64String([IO.File]::ReadAllBytes('C:\path\profile.mobileprovision')) | Set-Clipboard
[Convert]::ToBase64String([IO.File]::ReadAllBytes('C:\path\AuthKey_XXXXXXXXXX.p8')) | Set-Clipboard
```

## macOS 生成 Base64

```bash
base64 -i distribution.p12 | pbcopy
base64 -i profile.mobileprovision | pbcopy
base64 -i AuthKey_XXXXXXXXXX.p8 | pbcopy
```

## 使用

进入 GitHub `Actions -> Build Juweier Music v3.5.10 TestFlight -> Run workflow`。

- `upload_to_testflight = false`：只生成签名 IPA，作为 Actions Artifact 下载。
- `upload_to_testflight = true`：生成 IPA 后自动上传 App Store Connect / TestFlight。

工作流产物：`Juweier-Music-v3.5.10-TestFlight-IPA`。

TestFlight 上传成功后，等待 Apple 处理构建，然后在 App Store Connect -> TestFlight 中添加内部测试员即可在 iPhone 上通过 TestFlight App 安装测试。
