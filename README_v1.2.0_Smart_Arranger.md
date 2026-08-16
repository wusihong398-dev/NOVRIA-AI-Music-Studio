# NOVRIA AI Music Studio v1.2.0 — Smart Arranger

v1.2.0 把 v1.1.0 的乐手参数真正接入 MIDI 编配引擎。

## 吉他参数现在会真正影响编配
- 难度影响力度与复杂度
- 密度决定四分/八分节奏密度
- 扫弦 / 分解 / Fingerstyle参考 / Power Chord 使用不同生成逻辑
- Capo 会参与生成音高
- 钢琴主导模式下会自动降低吉他存在感

## Bass
- 根音优先
- 根音+五度
- 根音+八度
- Walking参考
- 更旋律化
- 密度与音区真正影响生成音符

## Drums
- 8Beat / Rock / Funk 等基础 Groove
- 八分 / 十六分 Hi-Hat
- Ride
- 力度
- 段落切换前 Fill

## Piano
- 和弦 / 转位
- 分解和弦
- Pad
- Rhodes节奏型
- 织体密度

## 智能编配流程
1. 导入歌曲
2. 分析 BPM / 调性 / 和弦 / 段落
3. 在“乐手演奏中心”设置每个乐器
4. 打开“AI 改编 / 乐谱”
5. 点击“读取当前乐手设置”
6. 点击“生成智能新编配 MIDI”
7. 选择 SoundFont 渲染成新的 WAV / MP3

## 说明
智能编配生成的是新的 MIDI 演奏结构，而不是直接复制原始 MP3 的音频 Stem。
自动编配结果仍建议乐手试听并做音乐性调整。
