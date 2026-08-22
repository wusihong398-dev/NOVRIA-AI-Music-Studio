# 橘味儿音乐 v3.3.2 服务器三首试跑

## 修正内容

- 不再把 `htdemucs_6s` 的合并 Guitar 轨当作独立电吉他。
- 第二阶段接入 MVSep Mega 53-Stems BS-RoFormer，读取模型原生的
  `electric-guitar` 与 `acoustic-guitar` 输出。
- RTX 3060 12GB 先尝试 CUDA；若显存不足或 CUDA 失败，三首试跑自动回退 CPU。
- 电吉他、木吉他、基础 Stem、歌词、逐音符同步乐谱未全部通过完整性检查时，
  不发布到 `G:\JuweierMusicProcessed\01_Ready`。
- 保留既有深层递归扫描、DJ/伴奏/单乐器版过滤、歌手名称归一化、同歌去重和
  原子入库规则。

## 试跑顺序

1. 关闭旧的 8001 服务器窗口。
2. 覆盖本包内容到 `E:\Dongba-Music-Server`。
3. 运行 `Install-MVSep-Electric-Guitar-v332.cmd`。
4. 运行 `Start-Juweier-Server-v332-Mega53-Pilot.ps1`。
5. 健康检查通过后运行 `Start-3-Song-Pilot-v332.cmd`。

三首试跑通过并完成人工试听前，不启动批量任务。
