# NOVRIA v2.1.0 GitHub 在线 EXE 构建

已加入 GitHub Actions Windows 在线构建。

1. 创建一个 GitHub 空仓库。
2. 上传本工程全部文件到仓库根目录。
3. 打开 Actions → Build NOVRIA Windows EXE。
4. 构建成功后下载 Artifact：
   NOVRIA-AI-Music-Studio-v2.1.0-Windows-x64
5. 解压后即为 Windows 程序目录，包含 NOVRIA-AI-Music-Studio.exe。

说明：GitHub Runner 负责 Windows EXE 编译；RTX 3060 CUDA 环境与 Demucs AI 模型在实际运行电脑配置。
