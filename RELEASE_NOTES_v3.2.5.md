# 橘味儿音乐 v3.2.5

本版本集中修复服务器曲库、移动端 AI 流水线、AI 歌词与三端打包问题。

## 主要更新

- 服务器歌曲进入 AI 处理前显示连接、定位歌曲、提交任务和后续处理百分比。
- 将任务查询、处理结果和健康检查统一放入 Cloudflare 曲库路由，修复歌曲能显示但处理任务出现 HTTP 404 的问题。
- 服务端在开始任务前检查 PyTorch、Demucs、FFmpeg、Librosa 与 Mido；缺失时返回可执行的中文安装提示，不再停在无意义的 3% 或 8%。
- 健康检查和 App 配置会报告 AI 分轨、同步歌词识别能力及缺失组件。
- AI 歌词继续优先读取同名 LRC 和音频内嵌歌词；没有歌词时可使用 faster-whisper 生成带时间轴的普通话、粤语和英语歌词。
- 五线谱、六线谱、电吉他谱、木吉他谱和各乐手谱面共用同一歌词时间轴，实现随播放位置同步显示。
- 手机本地音乐上传继续使用 ASCII 安全的表单参数，修复中文编曲模式导致上传失败的问题。
- Windows、Android、iOS 和源码包版本统一升级为 v3.2.5。

## 服务器升级要求

1. 使用 v3.2.5 服务端源码。
2. 在服务端虚拟环境安装完整依赖：`python -m pip install -r requirements-server.txt`。
3. 将 `JUWEIER_SERVER_LIBRARY` 指向实际服务器曲库目录；当前目录名右括号为全角字符：`G:\JuweierMusicLibrary\01_Originals\按歌手分类(MP3）`。
4. 重启 v3.2.5 Mobile API，并确认 `/api/v1/library/mobile/health` 返回 `processing_ready: true`。
5. Cloudflare Tunnel 的 `/api/v1/library...` 路由继续指向该 Mobile API 服务。

## 说明

当前软件仅用于学习和研究，不提供歌曲下载。测试曲目须由用户合法导入或由获授权的服务器曲库提供。
