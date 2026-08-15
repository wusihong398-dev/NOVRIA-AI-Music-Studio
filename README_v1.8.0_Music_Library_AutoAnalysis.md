# NOVRIA AI Music Studio v1.8.0 — Music Library & Auto Analysis

## 音乐库
统一导入后的歌曲进入 SQLite 音乐库，并按：
歌手 → 专辑 → 歌曲
显示。

## 自动读取
- 歌曲名
- 歌手
- 专辑
- 年份
- 时长
- 码率
- 采样率
- 声道
- 格式
- 内嵌封面

## 音质提示
- WAV / FLAC / AIFF / ALAC：无损/PCM
- 320 kbps+：高码率
- 192 kbps+：标准
- 更低：较低码率
- 低采样率额外提示

## 批量分析
可以对整个音乐库批量做：
- BPM
- 调性参考

## 批量六轨任务队列
未分轨歌曲可一次加入 `library/stem_queue.json`。
这一版先建立稳定队列与状态层，后续执行器可以使用：
- Windows 本地 NVIDIA GPU
- NOVRIA 云端 GPU
- 服务器批处理

## 与后续服务器曲库衔接
数据库字段已经按未来云端曲库方向设计：
歌手、专辑、歌曲、指纹、BPM、调性、六轨状态、音质、封面等。
