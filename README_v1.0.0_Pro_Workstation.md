# NOVRIA AI Music Studio v1.0.0 — Pro Workstation

## v1.0.0 核心升级
- 演出谱面页面：Lead Sheet / 吉他 TAB / Bass / 鼓 / 键盘。
- 谱面跟随播放头自动滚动到当前小节。
- 演出大字模式。
- 吉他和弦把位参考。
- 吉他 / Bass / 鼓 / 键盘独立 MusicXML 分谱。
- 每首歌曲独立保存 Mute / Solo / 音量 / 升降调 / 演出参数预设。
- 重新打开歌曲时自动恢复该歌曲演出预设。
- AI 歌声转换独立工作流：
  - 参考人声
  - Vocal Stem
  - Seed-VC / RVC / 云端 GPU 接口选择
  - 音色强度
  - 生成任务 JSON
- 歌声转换引擎与现场播放器解耦，避免模型故障影响演出稳定性。

## 关于 AI 歌声转换
v1.0.0 没有把未经充分测试的大型歌声模型直接塞进 EXE。
当前版建立稳定的任务层，后续可分别接：
1. Windows 本地 NVIDIA GPU 推理
2. NOVRIA 云端 GPU
3. Android/iOS 云任务

使用真实人物声音时应确认拥有必要的授权或同意。

## 分谱定位
自动生成的 TAB / Drum / Bass / Piano 谱属于排练和演出参考。
它们不是对原录音逐音符的出版级转写；正式表演前建议乐手人工校对。

## 下一阶段
- AI 歌声转换本地 GPU 真正推理
- NOVRIA 云端任务服务器
- 曲库/歌手/专辑管理
- Android / iOS 客户端共享工程与谱面
