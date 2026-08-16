# NOVRIA AI Music Studio v0.3.2 修复说明

## 修复的错误
Windows GUI EXE 使用 PyInstaller `console=False` 时，`sys.stdout` / `sys.stderr` 可能为 `None`。
Demucs 第一次调用 `torch.hub.load_state_dict_from_url()` 下载模型时会输出下载进度，旧版因此可能报：

`AttributeError: 'NoneType' object has no attribute 'write'`

v0.3.2 已不再依赖 PyTorch 的终端下载进度，而是由 NOVRIA GUI 自己管理模型下载。

## 新增进度显示
- 独立“AI 模型”下载进度条：0%~100%，显示已下载 MB / 总 MB。
- 下载完成后执行 SHA-256 校验。
- 模型缓存后再次使用直接显示 100%，不会重复下载。
- 独立“六轨分离进度”进度条。
- 使用 Demucs Separator callback 读取真实 segment_offset / audio_length 计算分离进度。
- 推理完成后继续显示 6 个 WAV Stem 的保存进度。

## 模型
`htdemucs_6s` 对应 Demucs 官方 experimental 6-source model：
`5c90dfd2-34c22ccb.th`

输出：vocals / drums / bass / guitar / piano / other。
