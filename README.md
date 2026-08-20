# 橘味儿音乐 v3.2.7（三端修复版）

> 本软件目前仅供学习与研究使用，不提供歌曲下载服务。

## v3.2.3 更新

- Windows 曲库改为只调用服务器 API；`G:\JuweierMusicLibrary\01_Originals\按歌手分类(MP3）` 由服务器进程扫描，客户端不再打开或回退扫描本机 G 盘。
- 服务器谱面统一输出歌词时间轴；五线谱、木吉他、电吉他、贝斯、鼓、键盘谱共用同步歌词。优先使用同名 LRC/内嵌歌词，可选 faster-whisper 转写普通话、粤语和英语，AI 结果须人工校对。
- Android / iOS 内置 AI 服务连接，不向普通用户显示服务器地址；Windows 端保留可见、可修改的配置。
- 新增 AI 歌词初稿，支持普通话/粤语、3 个方案、TXT/LRC 导出；粤语发音和押韵会明确提示人工复核。
- 新增开源软件声明、隐私政策、用户协议、帮助与反馈、关于软件。
- 美化应用内品牌图形，保留橙色主题与蓝色 AI 结点。
- 链接入口限定为用户有权使用的公开音频直链，不绕过登录、会员、付费或 DRM。

这是在稳定版 v2.1.7 上继续升级的三端完整版，包含 Windows 桌面端、Android 客户端、iOS 客户端，以及供手机调用的 Windows/GPU AI 服务。

## v3.2.1 扫描与统一歌曲源修复

- Windows 扫描器支持百度网盘同步目录常见的链接、联接和重解析目录，可进入 `按歌手分类(MP3)/字母目录/真实歌手` 的完整层级。
- 歌手分类取真实歌手文件夹，不再把“A 字母开头歌手”等字母目录误显示为歌手。
- 歌手歌曲树移到音乐库首屏，允许显示全部已下载歌曲，并提供搜索按钮和双击载入。
- 左侧新增“全局 G 盘歌曲”，一次选歌后 AI 分轨、改编/乐谱、演出谱面、演奏中心、现场演出、Setlist、AI 歌声和作品流程共用同一源文件。
- 内部转换产生的 `*_work.wav` 不再入库；升级后重新扫描会自动清除旧重复记录及其失效任务，因此导入一首只显示一首。
- 仅扫描已下载完整的音频，暂停下载产生的临时文件不会进入歌曲库。
- Windows 启用长路径支持；Android、iOS 与服务器接口使用同一歌手分类规则。

## v3.2.0 新增与修复

- 使用正式橘子音符图标，桌面端和移动端统一为橙色暗色视觉。
- Windows、Android、iOS 共用账号系统和内测群聊。
- 修复播放中拖动进度条后跳回旧位置的问题，所有分轨同步定位。
- 使用 `audio-separator` 运行 UVR 兼容的 `htdemucs_6s.yaml` 六轨；真实 Guitar stem 再执行木吉他/电吉他二阶段识别，生成独立轨道并记录诊断，不虚标七轨模型。
- Android/iOS 新增服务器歌曲库，可按歌曲、歌手、抖音流行、酷狗排行榜搜索并直接提交 AI 处理。
- 新增主旋律音高转写、MusicXML、可视五线谱和实际品位六线谱，并随播放位置滚动。
- 默认本地歌曲库为 `G:\JuweierMusicLibrary`，原曲放在 `01_Originals`，不会重复复制。
- AI 服务器同时支持局域网 `http://电脑IP:8000` 与 Cloudflare HTTPS 域名。
- 修复 `file_picker 12` API 变更导致的 Android/iOS 构建失败。
- SoundFont 未配置时保留编配 MIDI 并跳过音频渲染，不再使整条流水线失败。

- 修复批处理或自动流水线到 100% 后，`QThread` 尚未退出便被销毁导致的 Windows 硬退出。
- 修复源音频与转换后的工作 WAV 同时被扫描，造成“一首歌显示两首”。
- 修复中文标题乱码；文件名、元数据和任务 JSON 均使用 UTF-8，并兼容修复常见乱码。
- 队列与任务状态改为原子写入，异常退出后不会留下半截 JSON。
- 同名歌曲的工作文件加入内容指纹，避免互相覆盖。
- 分轨 AI 模型首次安装提供进度、校验和失败提示。
- 重型分析阶段移入后台线程，界面不再因 BPM、和弦、谱面与渲染计算而假死。
- 修复失败重试等待期间被误判为“全部完成”，成功后会清零对应重试计数。

## 三端结构

| 端 | 目录 / 入口 | 说明 |
|---|---|---|
| Windows | `app/`、`Run-Juweier-Music.bat` | 本地服务器/测试工作站，负责六轨基础分离、电吉他二次分离、分析、编配、谱面和演出 |
| Android | `mobile/` | Flutter 正式客户端；上传音频、查看进度、管理任务和谱面 |
| iOS | `mobile/` | 与 Android 共用 Flutter 代码；提供未签名包与 TestFlight 工程工作流 |
| 手机 AI 服务 | `server/mobile_api.py`、`Run-Mobile-Server.bat` | 在 Windows/GPU 电脑执行 UVR 兼容分轨与分析，向手机提供任务 API |

手机端不会在手机本机运行 UVR 大模型。手机可选择服务器歌曲库或上传音频，由 Windows/GPU 电脑完成分轨、BPM/调性/和弦分析、主旋律转写、五线谱、六线谱和新编配 MIDI。

## Windows 源码运行

1. 安装 Python 3.11 x64。
2. 双击 `Install-AI-Engine.bat`。
3. 双击 `Check-GPU.bat` 检查 CUDA。
4. 双击 `Run-Juweier-Music.bat`。

第一次分轨会由 UVR 兼容引擎下载并校验 `htdemucs_6s.yaml` 模型。Windows EXE 可通过 GitHub Actions 的 **Build Juweier Music Windows EXE** 生成；便携目录和安装程序分别直接交付，不再压缩包套压缩包。

## Android / iOS 使用

1. Windows/GPU 电脑先完成上面的 AI 环境安装。
2. 双击 `Run-Mobile-Server.bat`，默认端口为 `8000`。
3. 手机端使用应用内置的 HTTPS AI 服务；Windows 测试端可在“设置”查看或修改服务器地址。
4. 如服务器设置了 `JUWEIER_API_TOKEN`，构建/部署时需为移动端提供相同令牌。

服务器歌曲没有同名 LRC 时，可在服务器安装可选歌词识别组件：

```bash
pip install -r requirements-lyrics-server.txt
```

默认模型为 `large-v3-turbo`；可通过 `JUWEIER_LYRICS_MODEL` 修改。模型只安装在服务器，不会增加 Android、iOS 或 Windows 测试客户端安装包体积。

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
