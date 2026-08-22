# 橘味儿音乐 v3.3.4 MVSep CLI兼容热修复

- v3.3.3 已验证基础Demucs六轨能够生成有效PCM WAV。
- 失败发生在53.4%，原因是服务器所装 `bs-roformer-infer` CLI 不接受
  `--output_format` 参数，CUDA和CPU均在参数解析阶段退出。
- v3.3.4 删除该不兼容参数，沿用运行器默认WAV输出。
- 三首重试脚本会自动重置失败记录，无需重新扫描或重新安装模型。
