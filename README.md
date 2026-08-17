# 橘味儿音乐 v3.0.0（三端完整版）

这是在稳定版 v2.1.7 上继续升级的三端完整版，包含 Windows 桌面端、Android 客户端、iOS 客户端，以及供手机调用的 Windows/GPU AI 服务。

## v3.0.0 新增与修复

- 使用正式橘子音符图标，桌面端和移动端统一为橙色暗色视觉。
- Windows、Android、iOS 共用账号系统和内测群聊。
- 手机端完整提供导入、音乐库、自动流水线、六轨、演出调/Capo、六类谱面、Setlist 与结果下载入口。
- AI 服务器同时支持局域网 `http://电脑IP:8000` 与 Cloudflare HTTPS 域名。
- 修复 `file_picker 12` API 变更导致的 Android/iOS 构建失败。
- SoundFont 未配置时保留编配 MIDI 并跳过音频渲染，不再使整条流水线失败。

- 修复批处理或自动流水线到 100% 后，`QThread` 尚未退出便被销毁导致的 Windows 硬退出。
- 修复源音频与转换后的工作 WAV 同时被扫描，造成“一首歌显示两首”。
- 修复中文标题乱码；文件名、元数据和任务 JSON 均使用 UTF-8，并兼容修复常见乱码。
- 队列与任务状态改为原子写入，异常退出后不会留下半截 JSON。
- 同名歌曲的工作文件加入内容指纹，避免互相覆盖。
- 分轨模型首次下载提供进度、校验和失败提示。
- 重型分析阶段移入后台线程，界面不再因 BPM、和弦、谱面与渲染计算而假死。
- 修复失败重试等待期间被误判为“全部完成”，成功后会清零对应重试计数。

## 三端结构

| 端 | 目录 / 入口 | 说明 |
|---|---|---|
| Windows | `app/`、`Run-Juweier-Music.bat` | 完整 AI 音乐工作站，负责六轨、分析、编配、谱面和演出 |
| Android | `mobile/` | Flutter 正式客户端；上传音频、查看进度、管理任务和谱面 |
| iOS | `mobile/` | 与 Android 共用 Flutter 代码；提供未签名包与 TestFlight 工程工作流 |
| 手机 AI 服务 | `server/mobile_api.py`、`Run-Mobile-Server.bat` | 在 Windows/GPU 电脑执行 Demucs 与分析，向手机提供任务 API |

手机端不会在手机本机运行 Demucs 大模型。手机上传音频后，由 Windows/GPU 电脑完成六轨分离、BPM/调性/和弦分析、乐手参考谱、MusicXML 和新编配 MIDI。

## Windows 源码运行

1. 安装 Python 3.11 x64。
2. 双击 `Install-AI-Engine.bat`。
3. 双击 `Check-GPU.bat` 检查 CUDA。
4. 双击 `Run-Juweier-Music.bat`。

第一次六轨分离会下载并校验 `htdemucs_6s` 模型。Windows EXE 可通过 GitHub Actions 的 **Build Juweier Music Windows EXE** 生成；产物名为 `Juweier-Music-v3.0.0-Windows-x64`。

## Android / iOS 使用

1. Windows/GPU 电脑先完成上面的 AI 环境安装。
2. 双击 `Run-Mobile-Server.bat`，默认端口为 `8000`。
3. 手机与电脑处于同一局域网；在 App 设置中填入 `http://电脑局域网IP:8000`；外网填写 Cloudflare HTTPS API 域名。
4. 如设置了环境变量 `JUWEIER_API_TOKEN`，手机端同时填写相同令牌。

GitHub Actions：

- **Package Juweier Music v3 Source**：首先生成完整源码 ZIP。
- **Build Juweier Music Android and iOS**：生成 Android release APK 与 iOS 模拟器验证包。
- **Build Juweier Music iOS TestFlight Package**：生成可在 Mac/Xcode 中签名、归档和上传 TestFlight 的完整工程。

iOS App Store/TestFlight 必须使用你自己的 Apple Developer Team 与签名证书；仓库不会也不应包含私钥。

## 移动 API

- `GET /health`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `GET /api/v1/account/me`
- `GET/POST /api/v1/community/messages`
- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/artifacts/{job_id}/{name}`

公网部署必须加 HTTPS 和访问令牌。局域网 HTTP 仅用于受信任网络调试。

## 验证

```bash
python -m unittest discover -s tests -v
python -m py_compile app/*.py server/mobile_api.py
```

当前回归测试覆盖 Windows 100% 退出问题、重复导入、中文文件名安全化、UTF-8 乱码修复、原子 JSON 与版本/品牌一致性。
