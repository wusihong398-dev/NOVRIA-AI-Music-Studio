# NOVRIA AI Music Studio v0.9.0 — Render & Notation

## 新增
- 新编配 MIDI → WAV：调用 FluidSynth + 用户选择的 SoundFont。
- 新编配 MIDI → MP3：先 FluidSynth 渲染 WAV，再由 FFmpeg 编码 320 kbps MP3。
- SoundFont 选择与保存入口。
- 和弦识别扩展到：大三和弦、小三和弦、7、maj7、m7、sus4、dim。
- MusicXML 4.0 导出，包含小节、和弦、段落和基本调号/拍号。
- 主旋律参考转写：使用 pYIN 输出单声部音高时间线 CSV。
- 保留 v0.8.0 的六轨升降调、Lead Sheet、分乐手参考谱和新编配 MIDI。

## 运行时目录
- `runtime/fluidsynth/bin/fluidsynth.exe`
- `runtime/ffmpeg/bin/ffmpeg.exe`
- `soundfonts/` 可放置用户有权使用的 SoundFont

## 重要说明
1. SoundFont 的许可条件各不相同，正式发行时只能打包允许再分发的音色库。
2. MusicXML 和自动和弦/主旋律转写属于 AI/算法参考结果，正式演出前建议人工校对。
3. 新 MIDI 与新渲染音频避免直接复用原录音波形，但并不自动消除歌曲作品、旋律、歌词或编曲方面的权利问题。

## 下一步 v1.0.0
- 自带可合法再分发的基础音源或国内 CDN 音源包管理。
- Guitar TAB 实际音符/Fret 计算。
- Drum MusicXML 打击乐谱。
- Bass / Piano 独立 MusicXML 分谱。
- 自动翻谱与演出同步。
- AI 歌声转换第一版接入。
