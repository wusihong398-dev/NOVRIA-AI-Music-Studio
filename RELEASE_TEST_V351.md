# 橘味儿音乐 v3.5.1 三端联调测试版

## 测试范围

- Windows x64 客户端
- Android APK / AAB
- iOS Simulator

## 服务端

客户端继续自动连接：

`https://api.db0888.com`

移动端曲库优先接口：

`/api/v1/library/mobile/catalog`

Windows 客户端继续使用已发布成品加载逻辑，不要求客户端本地重新执行 AI 分轨。

## 本轮数据

本轮只验证服务器此前已经完成 AI 处理并发布的 4 首歌曲。

测试要求：

1. 三端打开后能直接看到 4 首已发布歌曲。
2. 点击歌曲可直接播放服务器成品音频。
3. 已完成歌曲可以读取已有歌词、分轨、乐谱等服务器成果；不存在的成果应明确显示不可用，不触发客户端重新 AI 处理。
4. 三端曲库数量、歌曲标题/歌手、处理状态应保持一致。
5. Android/iOS 启动时自动刷新服务器曲库，同时保留已有本地缓存。
6. Windows 客户端继续使用 published product loader 和 lyrics timeline loader。

## v3.5.1 构建产物

- `Juweier-Music-v3.5.1-Windows-x64-Portable`
- `Juweier-Music-v3.5.1-Windows-Setup`
- `Juweier-Music-v3.5.1-Android-APK`
- `Juweier-Music-v3.5.1-Android-AAB`
- `Juweier-Music-v3.5.1-iOS-Simulator`

## 说明

v3.5.1 是基于 v3.5.0 最新源码建立的三端联调分支。移动客户端构建时将运行版本标记为 3.5.1，并保持 `https://api.db0888.com` 为固定产品服务器地址。服务器数据库中的四首既有 AI 成品不需要重新处理。
