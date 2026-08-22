# 橘味儿音乐 v3.3.3 服务器三首试跑热修复

## 故障根因

v3.3.2 在目标 Windows 10 服务器中通过 `audio-separator` 写出的六个基础
WAV 全部无法被 libsndfile 读取。因此任务在基础六轨完整性检查处失败，尚未进入
MVSep 独立电吉他阶段。

## 修复

- 基础六轨改为直接调用官方 Demucs `htdemucs_6s` API。
- 每一轨通过 SoundFile 写为 PCM 24-bit 临时 WAV，验证帧数、声道和采样率后再
  原子改名，禁止半成品进入后续流水线。
- 独立木吉他/电吉他仍由 MVSep Mega 53-Stems 的原生
  `acoustic-guitar` / `electric-guitar` 输出生成。
- 三首重试脚本会重置此前的失败状态和本轮计数，不需要重新执行预扫描。

## 使用顺序

1. 停止 v3.3.2 服务器。
2. 将本包覆盖到 `E:\Dongba-Music-Server`。
3. 启动 `Start-Juweier-Server-v333-Demucs-Mega53-Pilot.ps1`。
4. 健康检查确认 `version=3.3.3` 且 GPU 为 RTX 3060。
5. 运行 `Start-3-Song-Pilot-v333.cmd`。

不要重新运行 `Prepare-3-Song-Pilot-v331.cmd`，数据库中的三首失败记录会被安全重置。
