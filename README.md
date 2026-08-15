# NOVRIA AI Music Studio v2.1.0

本版本继续以 Windows 本地测试为主，不需要服务器。

## v2.1.0 新增
- NVIDIA GPU / CUDA 检测页面
- `Check-GPU.bat` 一键检查显卡、驱动、PyTorch CUDA 状态
- Windows 输出声卡枚举
- 音频 Blocksize 设置入口，为后续低延迟优化做准备
- 现场演出 4 拍 Count-in
- 演出模式本地 Stem / 离线优先设置
- 保留 v0.2.0 的 Demucs 六轨真实分离
- 保留真实 Mute / Solo / 音量 / Seek / WAV 混音导出
- 吉他、钢琴、鼓手、贝斯现场预设

## 推荐测试顺序
1. 先运行 `Install-AI-Engine.bat`
2. 运行 `Check-GPU.bat`
3. 运行 `Run-NOVRIA.bat`
4. 导入一首 3~5 分钟歌曲
5. 执行 AI 六轨分离
6. 分别试听 Vocal / Drums / Bass / Guitar / Piano / Other
7. 进入现场演出，测试吉他弹唱和钢琴弹唱
8. 测试 4 拍 Count-in
9. 导出关闭某件乐器后的 WAV

## 下一阶段
v2.1.0 将重点做：
- 波形时间轴
- BPM / 调性检测
- Marker（前奏/主歌/副歌/间奏/尾奏）
- 更完整的低延迟声卡设置
- 耳返/主扩双路由基础
- MIDI / USB 脚踏板
- 第二分轨模型接口，为 MDX/UVR 多模型融合准备
