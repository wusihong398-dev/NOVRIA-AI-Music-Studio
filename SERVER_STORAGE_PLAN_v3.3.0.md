# 橘味儿音乐服务器磁盘规划（v3.3.0）

按当前四块 SSD 建议这样分工：

- `E:`：服务器程序、Python 环境、UVR 模型、SQLite 索引、日志。这里保留小而关键、需要快速随机读写的文件。
- 合并后的 `G:`：原版歌曲，只保存 `G:\JuweierMusicLibrary\01_Originals` 及人工整理的歌手/分类目录。
- `H:`：AI 成果，保存 `H:\JuweierAI\03_AI_Processed`，包括七轨 WAV、歌词时间轴、MusicXML、六线谱、各乐器谱和编配文件。
- `C:/D:`：Windows 和普通软件；不安排长期批量音频写入，避免影响系统盘。

服务端支持多个原版歌曲根目录，使用英文分号分隔：

```bat
set "JUWEIER_SERVER_LIBRARY_ROOTS=G:\JuweierMusicLibrary\01_Originals;H:\AdditionalOriginals"
```

默认启动脚本已经配置：

```bat
set "JUWEIER_LIBRARY_DB=E:\Dongba-Music-Server\database\juweier_music_library.sqlite3"
set "JUWEIER_PROCESSED_DIR=H:\JuweierAI\03_AI_Processed"
set "JUWEIER_AUTO_SCAN_LIBRARY=1"
set "JUWEIER_CATALOG_WATCH_INTERVAL=900"
```

“自动同步”只发生在服务器后台，与打开 Windows、Android 或 iOS App 无关。客户端永远不会扫描 G/H 盘。
