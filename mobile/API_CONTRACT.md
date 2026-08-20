# 橘味儿音乐 v3.2.7 三端接口

Android 与 iOS 客户端使用以下接口：

- `GET /health`：服务器、版本、GPU、服务器 G 盘根目录与歌词 ASR 状态。
- `GET /api/v1/library`：只返回服务器曲库，不读取客户端本地盘符。
- `POST /api/v1/library/scan`：在服务器进程内扫描 `JUWEIER_SERVER_LIBRARY`。
- `POST /api/v1/library/{track_id}/process`：处理服务器曲库歌曲。
- `POST /api/v1/auth/register`：注册账号并返回 30 天会话令牌。
- `POST /api/v1/auth/login`：登录并返回会话令牌。
- `GET /api/v1/account/me`：读取当前账号。
- `GET/POST /api/v1/community/messages`：读取或发送内测群消息。
- `POST /api/v1/jobs`：multipart 上传 `file`，并提交 `arrangement_mode`、`transpose`、`output`。
- `GET /api/v1/jobs/{job_id}`：返回 `status`、`stage`、`progress`、`key`、`artifacts`。
- `GET /api/v1/artifacts/{job_id}/{name}`：下载六轨、谱面和 MIDI。

谱面任务优先读取服务器歌曲旁边的同名 `.lrc` 或内嵌歌词。没有歌词时，服务器可安装
`requirements-lyrics-server.txt`，使用 faster-whisper 对分离后的人声轨生成普通话、粤语或英语
时间轴。所有乐手谱面共同读取 `lyrics_timeline.json`；AI 转写结果必须人工校对。

源码已包含 `server/mobile_api.py`。在 Windows/GPU 电脑双击
`Run-Mobile-Server.bat`，默认监听 `8000` 端口。

如果设置环境变量 `JUWEIER_API_TOKEN`，手机端“设置 → 访问令牌”必须填写相同值。
公网使用时应通过 Cloudflare 等 HTTPS 反向代理；不要把无鉴权的 8000 端口直接暴露到公网。
