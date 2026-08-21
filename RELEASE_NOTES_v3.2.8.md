# 橘味儿音乐 v3.2.8

本版集中修复 Windows、Android 与 iOS 实测中的阻断问题。

## 曲库

- 手机端对 `/api/v1/library/mobile/*`、`/api/v1/library/*` 接口自动兼容，不再因 Cloudflare 旧路由返回 `Not Found` 而要求用户扫描。
- 服务器继续使用持久化 SQLite 索引；默认启动不再重复扫描 14,000 多首歌曲。客户端启动先显示已缓存曲库，管理员需要更新曲库时再手动执行增量扫描。
- Windows 曲库请求移到后台线程，14,000 首以上歌曲不再阻塞主界面。
- Windows 只创建歌手节点，展开某位歌手时才生成该歌手的歌曲节点；所有歌手默认折叠。
- 修复 A–Z 按钮宽度被全局内边距占满而导致字母不可见的问题。

## 上传与流水线

- multipart 请求头只使用 ASCII 安全文件名，中文原文件名通过独立表单字段传输并在服务器恢复。
- 增加 `/api/v1/library/jobs` 等兼容入口，避免不同 Tunnel 路由造成上传、任务查询或处理接口 404。
- 健康检查明确校验 PyTorch、Demucs、audio-separator、FFmpeg 等处理环境。
- 手机端“继续任务”会重新提交失败任务，不再轮询已经永久失败的旧任务。
- 成功或失败的流水线任务均可单独删除，也可使用“清理”一次移除全部已结束记录；原歌曲和处理产物不会被删除。

## UVR 与电吉他

- 分轨引擎改为 `audio-separator` 提供的 UVR 兼容无界面运行方式，默认模型为 `htdemucs_6s.yaml`。
- 真实 UVR 六轨完成后，对 Guitar stem 进行木吉他/电吉他二阶段识别，生成独立 `guitar.wav` 与 `electric_guitar.wav`。
- 不再把旧版简单频谱处理描述为 UVR；诊断文件会记录实际引擎、模型和电吉他活跃度。
- UVR 模型配置优先使用服务器本地缓存，GitHub 连接超时时自动使用 Demucs 六轨后备方案。
- 每次重试前清理残留的半成品 stem，并对新生成的 WAV 做格式校验，修复 `guitar_combined.wav: Format not recognised`。

## 歌词

- Windows 从服务器歌曲库载入歌曲时同步下载同名 LRC；音频内嵌歌词仍可直接读取。
- 演出谱面新增“显示歌词”开关，默认开启，关闭后隐藏谱面和播放位置歌词，并保存用户选择。

## 打包

- GitHub Actions 产物不再创建压缩包内的第二层压缩包。
- iOS Simulator 产物直接包含 `Runner.app`；TestFlight 产物直接包含 Xcode 工程；Windows 便携目录与安装程序分别直接交付。
- Windows Worker 打包补齐 ONNX Runtime、Matplotlib、audio-separator 和 Demucs 动态依赖，构建时必须通过独立分轨 Worker 自检。
