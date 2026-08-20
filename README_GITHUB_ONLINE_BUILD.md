# 橘味儿音乐 v3.2.6 GitHub 在线三端构建

已加入 GitHub Actions Windows 在线构建。

1. 创建一个 GitHub 空仓库。
2. 上传本工程全部文件到仓库根目录。
3. 打开 Actions，根据目标端选择 **Build Juweier Music Windows EXE**、**Build Juweier Music Android and iOS** 或 **Build Juweier Music iOS TestFlight Package**。
4. 构建成功后下载 Artifact：
   Juweier-Music-v3.2.6-Windows-x64
5. 解压后即为 Windows 程序目录，包含 Juweier-Music.exe。Android 工作流产出 release APK；iOS 工作流产出未签名包或 TestFlight Xcode 工程。

说明：GitHub Runner 负责 Windows EXE 编译；RTX 3060 CUDA 环境与 Demucs AI 模型在实际运行电脑配置。
