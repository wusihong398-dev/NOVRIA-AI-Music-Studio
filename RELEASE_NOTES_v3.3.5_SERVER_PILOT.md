# 橘味儿音乐 v3.3.5 Mega 53 官方模型路径热修复

- v3.3.4 三首均在 53.4% 失败，原因是 PyPI 旧版 `bs-roformer-infer`
  的模型登记表没有 MVSep Mega 53 slug。
- v3.3.5 不再通过旧模型表查找，改为把官方 checkpoint 和 YAML 的
  绝对路径直接传入推理 CLI。
- 安装器会核对官方文件大小及 SHA-256；不完整下载和此前的假就绪标记
  都不能通过。
- 基础六轨继续使用已经验证能生成有效 PCM WAV 的 Demucs htdemucs_6s。
- 独立木吉他、电吉他仍只接受 Mega 53 原生 `acoustic-guitar` 和
  `electric-guitar` 输出。

官方资产：ZFTurbo/Music-Source-Separation-Training v1.0.21。
