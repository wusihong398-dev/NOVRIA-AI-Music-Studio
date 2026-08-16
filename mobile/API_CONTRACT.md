# 橘味儿音乐 v2.1.7 移动端接口

Android 与 iOS 客户端使用以下接口：

- `GET /health`：服务器、版本与 GPU 状态。
- `POST /api/v1/jobs`：multipart 上传 `file`，并提交 `arrangement_mode`、`transpose`、`output`。
- `GET /api/v1/jobs/{job_id}`：返回 `status`、`stage`、`progress`、`key`、`artifacts`。
- `GET /api/v1/artifacts/{job_id}/{name}`：下载六轨、谱面和 MIDI。

源码已包含 `server/mobile_api.py`。在 Windows/GPU 电脑双击
`Run-Mobile-Server.bat`，默认监听 `18120` 端口。

如果设置环境变量 `JUWEIER_API_TOKEN`，手机端“设置 → 访问令牌”必须填写相同值。
公网使用时必须通过 HTTPS 反向代理，并设置令牌；不要把无鉴权的 18120 端口直接暴露到公网。
