# 橘味儿音乐 v3.2.1 三端接口

Android 与 iOS 客户端使用以下接口：

- `GET /health`：服务器、版本与 GPU 状态。
- `POST /api/v1/auth/register`：注册账号并返回 30 天会话令牌。
- `POST /api/v1/auth/login`：登录并返回会话令牌。
- `GET /api/v1/account/me`：读取当前账号。
- `GET/POST /api/v1/community/messages`：读取或发送内测群消息。
- `POST /api/v1/jobs`：multipart 上传 `file`，并提交 `arrangement_mode`、`transpose`、`output`。
- `GET /api/v1/jobs/{job_id}`：返回 `status`、`stage`、`progress`、`key`、`artifacts`。
- `GET /api/v1/artifacts/{job_id}/{name}`：下载六轨、谱面和 MIDI。

源码已包含 `server/mobile_api.py`。在 Windows/GPU 电脑双击
`Run-Mobile-Server.bat`，默认监听 `8000` 端口。

如果设置环境变量 `JUWEIER_API_TOKEN`，手机端“设置 → 访问令牌”必须填写相同值。
公网使用时应通过 Cloudflare 等 HTTPS 反向代理；不要把无鉴权的 8000 端口直接暴露到公网。
