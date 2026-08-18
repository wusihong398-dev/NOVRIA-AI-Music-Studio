# 橘味儿音乐 v3.0.0 交付说明

基线：稳定版 v2.1.7。此次版本延续原有 Windows AI 音乐工作站全部能力，并把 2.1.7 之后确认的需求合并为 Windows、Android、iOS 三端完整版。

## 完整功能

- AI 六轨分离：人声、鼓、贝斯、吉他、钢琴、其他。
- BPM、调性、和弦与段落分析；新 MIDI 编配、A/B 方案与音源渲染。
- 吉他六线谱、五线谱、钢琴谱、贝斯谱、鼓谱、演唱参考及 MusicXML。
- 六轨混音、升降调、吉他 Capo、节拍器、MIDI 脚踏控制、现场锁定与 Setlist 自动下一首。
- 三端账号注册登录、30 天本地会话与内测群聊。
- Android/iOS 端导入、任务恢复、完整流水线状态、六轨/谱面结果、演出页面与 Setlist。

## 兼容性与构建

- 移动端已迁移至 `file_picker 12` API。
- iOS CI 使用模拟器完成无签名验证；TestFlight 工作流提供可在 Mac 上签名归档的完整 Xcode 工程。
- 手机同一 Wi-Fi 使用 `http://电脑局域网IP:8000`，外网使用 Cloudflare HTTPS API 域名，不能填写 `127.0.0.1` 或 `localhost`。
- 未设置 SoundFont 时，AI 流水线保留新编配 MIDI 并跳过 WAV/MP3 渲染，不再整体失败。

## GitHub Actions 产物顺序

1. `Juweier-Music-v3.0.0-Complete-Source`
2. `Juweier-Music-v3.0.0-Windows-x64`
3. `Juweier-Music-v3.0.0-Android-APK`
4. `Juweier-Music-v3.0.0-iOS-TestFlight-Xcode-Project`

iOS 上架仍需项目所有者自己的 Apple Developer Team 和签名证书。
