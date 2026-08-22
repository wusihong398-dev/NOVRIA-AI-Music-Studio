# 橘味儿音乐服务器 v3.4.1

本版只更新 Windows 服务器，三端 v3.4.0 客户端无需重新安装。

- 成品优先发布到 `G:\JuweierMusicProcessed\01_Ready`。
- G 盘达到安全保留线后，新成品自动发布到 `F:\JuweierMusicProcessed\01_Ready`。
- 每个成品盘至少保留 15% 且不少于 30 GB；每首开始前另预留 3 GB 工作余量。
- G、F 都达到保留线时，批处理自动暂停，未开始的歌曲继续保持待处理状态，不会标记失败。
- 已经发布在 G 或 F 的歌曲继续通过统一数据库/API 提供给 Windows、Android 和 iOS。
- 健康检查和批处理状态会返回两块成品盘的总容量、剩余容量及保留线。
- 新增 `Start-H-Full-Batch-v341.cmd`：递归扫描 `H:\juweier-music` 全部层级，应用 DJ、伴奏、单乐器版、重复歌曲过滤规则后启动全量批处理。

覆盖升级包后先双击 `Start-Juweier-Server-v341.cmd`，确认服务窗口正常，再双击 `Start-H-Full-Batch-v341.cmd`。
