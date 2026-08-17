# 橘味儿音乐 v3.0.0 — Windows EXE 发布工程

这个版本已经针对“冻结成 EXE”修正 Demucs 调用方式，不再使用 `sys.executable -m demucs`。

## 最省事的构建方式：GitHub Actions

1. 新建一个 GitHub 仓库。
2. 把这个压缩包里的全部文件上传到仓库根目录，包括隐藏目录 `.github`。
3. 打开仓库的 **Actions**。
4. 选择 **Build Juweier Music Windows EXE**。
5. 点击 **Run workflow**。
6. 构建完成后，在该次 Actions 页面底部下载 Artifact：
   `Juweier-Music-v3.0.0-Windows-x64`
7. 解压 Artifact 后得到便携版 ZIP，其中包含：
   `Juweier-Music.exe`

用户电脑不需要安装 Python。

## 当前构建策略

当前 CI 先使用 CPU 版 PyTorch，目的是让 Windows 测试 EXE 能在没有 NVIDIA 的机器上启动运行，并减少 CUDA 运行库造成的兼容问题。

下一步再提供 NVIDIA CUDA 专用构建，面向正式 AI 分轨速度测试。

## 安装程序

工程里同时包含 `installer/NOVRIA.iss`。Windows 构建完成后可以用 Inno Setup 6 编译为标准安装程序：
`Juweier_Music_v3.0.0_Setup_x64.exe`

## 注意

第一次进行 AI 六轨分离仍会下载 Demucs `htdemucs_6s` 模型。模型不直接塞进主 EXE，是为了避免每次模型升级都重新下载整个程序。
