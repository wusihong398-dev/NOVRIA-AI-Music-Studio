# 橘味儿音乐 v2.1.7 交付说明

基线：用户提供的 v2.1.6 源码。

## 可交付目标

- Windows x64：完整桌面程序及 PyInstaller/FFmpeg/CUDA 构建流程。
- Android：Flutter release APK 构建流程。
- iOS：未签名 release 包与 TestFlight Xcode 工程构建流程。
- 跨端后端：Windows/GPU 本地服务，连接 Android/iOS 与桌面 AI 能力。

## 重要边界

- Windows 可执行文件需要 Windows 构建机。
- iOS 安装包需要 macOS、Xcode、Apple Developer Team 和签名证书。
- GitHub Actions 已分别使用 Windows、Ubuntu 和 macOS runner 处理平台构建。
- AI 分轨模型体积较大，不直接放入源码包；第一次运行时自动下载并校验。

## 建议验收场景

1. 导入一首中文名歌曲，只出现一条记录。
2. 执行完整流水线，进度到 100% 后窗口保持运行。
3. 断网启动首次模型下载，得到明确失败信息；联网重试后可继续。
4. 手机端配置 Windows 局域网地址并通过健康检查。
5. 手机上传歌曲后可恢复轮询并看到六轨、谱面、MusicXML 和 MIDI 产物。
6. 将任务移调 ±12 半音，服务端生成的调性、和弦与 MIDI 同步变化。
