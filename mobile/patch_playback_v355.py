from pathlib import Path
import re

path = Path('mobile/lib/main.dart')
text = path.read_text(encoding='utf-8')
text = re.sub(r"const appVersion = '3\.5\.[0-9]+';", "const appVersion = '3.5.5';", text, count=1)

text = text.replace(
    "class _MainShellState extends State<MainShell> {\n  int index = 0;",
    "class _MainShellState extends State<MainShell> {\n  int index = 0;\n  final performanceKey = GlobalKey<_PerformancePageState>();",
    1,
)
text = text.replace("PerformancePage(store: widget.store),", "PerformancePage(key: performanceKey, store: widget.store),", 1)
text = text.replace(
    "body: SafeArea(child: pages[index]),",
    '''body: SafeArea(child: Column(children: [
              Expanded(child: IndexedStack(index: index, children: pages)),
              if (widget.store.activePerformanceJobId.isNotEmpty)
                Container(
                  margin: const EdgeInsets.fromLTRB(10, 4, 10, 6),
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(color: const Color(0xFF251824), borderRadius: BorderRadius.circular(16), border: Border.all(color: const Color(0xFF553348))),
                  child: Row(children: [
                    const Icon(Icons.graphic_eq, color: accent),
                    const SizedBox(width: 8),
                    Expanded(child: Text(performanceKey.currentState?.selected?.fileName ?? '正在播放', maxLines: 1, overflow: TextOverflow.ellipsis)),
                    IconButton(onPressed: () async { await performanceKey.currentState?.togglePlay(); if (mounted) setState(() {}); }, icon: const Icon(Icons.play_arrow)),
                    IconButton(onPressed: () async { await performanceKey.currentState?.stopPlayers(); if (mounted) setState(() {}); }, icon: const Icon(Icons.stop)),
                    IconButton(onPressed: () => setState(() => index = 2), icon: const Icon(Icons.open_in_full)),
                  ]),
                ),
            ])),''',
    1,
)

text = text.replace(
    "  final players = <String, AudioPlayer>{};\n",
    "  final players = <String, AudioPlayer>{};\n  final stemEnabled = <String, bool>{'人声': true, '鼓': true, '贝斯': true, '木吉他': true, '电吉他': true, '钢琴': true, '其他': true};\n  double loadingProgress = 0;\n  String loadingText = '';\n  bool stemsReady = false;\n",
    1,
)

pattern = re.compile(r"  Future<void> loadPlayers\(PipelineJob job\) async \{.*?\n  \}\n\n  Future<void> stopPlayers\(\) async \{", re.S)
replacement = r'''  Future<void> loadPlayers(PipelineJob job) async {
    if (loadedJobId == job.id && players.isNotEmpty) return;
    await stopPlayers();
    stemsReady = false;
    loadingProgress = .02;
    loadingText = '正在连接歌曲服务器…';
    if (mounted) setState(() {});
    final token = widget.store.accountToken.isNotEmpty ? widget.store.accountToken : widget.store.apiToken;
    final cacheRoot = Directory('${Directory.systemTemp.path}${Platform.pathSeparator}juweier_v355${Platform.pathSeparator}${job.libraryId > 0 ? job.libraryId : job.id}');
    await cacheRoot.create(recursive: true);

    Future<String> cacheAudio(String url, String name, String extension, {void Function(double)? onProgress}) async {
      final target = File('${cacheRoot.path}${Platform.pathSeparator}$name.$extension');
      if (await target.exists() && await target.length() > 4096) { onProgress?.call(1); return target.path; }
      final temp = File('${target.path}.${DateTime.now().microsecondsSinceEpoch}.download');
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 15);
      try {
        final request = await client.getUrl(Uri.parse(url));
        if (token.isNotEmpty) request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
        final response = await request.close().timeout(const Duration(seconds: 45));
        if (response.statusCode < 200 || response.statusCode >= 300) throw HttpException('HTTP ${response.statusCode}');
        final total = response.contentLength > 0 ? response.contentLength : 0;
        var received = 0;
        final sink = temp.openWrite();
        await for (final chunk in response) {
          sink.add(chunk);
          received += chunk.length;
          if (total > 0) onProgress?.call((received / total).clamp(0, 1));
        }
        await sink.close();
        if (!await temp.exists() || await temp.length() < 1024) throw const FileSystemException('音频缓存为空');
        try { if (await target.exists()) await target.delete(); } catch (_) {}
        try { await temp.rename(target.path); } catch (_) { await temp.copy(target.path); try { await temp.delete(); } catch (_) {} }
        onProgress?.call(1);
        return target.path;
      } finally { client.close(force: true); }
    }

    if (job.libraryId > 0) {
      final preview = AudioPlayer();
      try {
        loadingText = '正在加载原曲…';
        if (mounted) setState(() {});
        final url = '${widget.store.serverBase}/api/v1/library/mobile/catalog/${job.libraryId}/audio';
        final local = await cacheAudio(url, 'original_${job.libraryId}', 'mp3', onProgress: (p) { loadingProgress = .05 + p * .35; if (mounted) setState(() {}); });
        await preview.setFilePath(local);
        await preview.setVolume(masterVolume);
        players['原曲'] = preview;
        loadedJobId = job.id;
        positionSub = preview.positionStream.listen((value) { if (mounted && !dragging) setState(() => position = value); });
        durationSub = preview.durationStream.listen((value) { if (mounted && value != null) setState(() => duration = value); });
        loadingProgress = .4;
        loadingText = '原曲已就绪，后台加载分轨…';
        if (mounted) setState(() {});
        unawaited(preview.play());
      } catch (error) {
        await preview.dispose();
        loadingText = '原曲加载失败：$error';
        if (mounted) setState(() {});
        return;
      }
    }

    Future<void> loadStemsInBackground() async {
      const keys = {'人声':'stem_vocals','鼓':'stem_drums','贝斯':'stem_bass','木吉他':'stem_guitar','电吉他':'stem_electric_guitar','钢琴':'stem_piano','其他':'stem_other'};
      final stemPlayers = <String, AudioPlayer>{};
      var done = 0;
      for (final entry in keys.entries) {
        if (loadedJobId != job.id) break;
        loadingText = '正在加载${entry.key}分轨 ${done + 1}/7';
        if (mounted) setState(() {});
        final url = '${widget.store.serverBase}/api/v1/library/mobile/catalog/${job.libraryId}/artifacts/${entry.value}';
        final p = AudioPlayer();
        try {
          final local = await cacheAudio(url, entry.value, 'wav', onProgress: (x) { loadingProgress = .4 + ((done + x) / 7) * .6; if (mounted) setState(() {}); });
          await p.setFilePath(local);
          await p.setVolume((stemEnabled[entry.key] ?? true) ? (levels[entry.key] ?? .8) * masterVolume : 0);
          stemPlayers[entry.key] = p;
        } catch (_) { await p.dispose(); }
        done++;
      }
      if (stemPlayers.isEmpty || loadedJobId != job.id) return;
      final old = players.values.first;
      final oldPosition = old.position;
      final wasPlaying = old.playing;
      await positionSub?.cancel(); await durationSub?.cancel();
      for (final p in players.values) { await p.pause(); await p.dispose(); }
      players..clear()..addAll(stemPlayers);
      for (final p in players.values) { await p.seek(oldPosition); }
      final master = players.values.first;
      positionSub = master.positionStream.listen((value) { if (mounted && !dragging) setState(() => position = value); });
      durationSub = master.durationStream.listen((value) { if (mounted && value != null) setState(() => duration = value); });
      stemsReady = true; loadingProgress = 1; loadingText = '七轨混音已就绪';
      if (wasPlaying) for (final p in players.values) { unawaited(p.play()); }
      if (mounted) setState(() {});
    }
    unawaited(loadStemsInBackground());
  }

  Future<void> stopPlayers() async {'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit('loadPlayers target not found')

text = text.replace(
    "  Future<void> seekAll(double seconds) async {",
    "  Future<void> setStemEnabled(String name, bool enabled) async {\n    stemEnabled[name] = enabled;\n    final player = players[name];\n    if (player != null) await player.setVolume(enabled ? (levels[name] ?? .8) * masterVolume : 0);\n    if (mounted) setState(() {});\n  }\n\n  Future<void> seekAll(double seconds) async {",
    1,
)

text = text.replace(
    "        Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(children: [\n          Row(children: [",
    "        Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(children: [\n          if (loadingProgress < 1 || loadingText.isNotEmpty) ...[\n            Row(children: [Expanded(child: Text(loadingText.isEmpty ? '准备播放…' : loadingText, style: const TextStyle(color: Color(0xFFBDAAB5)))), Text('${(loadingProgress * 100).round()}%')]),\n            const SizedBox(height: 6),\n            LinearProgressIndicator(value: loadingProgress <= 0 ? null : loadingProgress.clamp(0, 1)),\n            const SizedBox(height: 8),\n          ],\n          Row(children: [",
    1,
)

old = '''              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                Text('${(entry.value * 100).round()}%'),
                if (job.artifacts[trackKeys[entry.key]] != null)
                  IconButton(
                    onPressed: () => Clipboard.setData(ClipboardData(text: job.artifacts[trackKeys[entry.key]]!)),
                    icon: const Icon(Icons.download_for_offline_outlined),
                    tooltip: '复制音轨下载地址',
                  ),
              ]),'''
new = '''              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                Text('${(entry.value * 100).round()}%'),
                Switch(value: stemEnabled[entry.key] ?? true, onChanged: stemsReady ? (value) => setStemEnabled(entry.key, value) : null),
              ]),'''
text = text.replace(old, new, 1)

text = text.replace(
    "          Text(scoreType, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),",
    "          Row(children: [Expanded(child: Text(scoreType, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800))), OutlinedButton.icon(onPressed: () async { final prefs = await SharedPreferences.getInstance(); final key = 'juweier_lyrics_fix_${job.libraryId}'; final c = TextEditingController(text: prefs.getString(key) ?? ''); final value = await showDialog<String>(context: context, builder: (context) => AlertDialog(title: const Text('歌词校正'), content: SizedBox(width: 520, child: TextField(controller: c, maxLines: 14, decoration: const InputDecoration(hintText: '把错别字歌词粘贴/修正后保存在本机，后续播放继续使用。'))), actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('取消')), FilledButton(onPressed: () => Navigator.pop(context, c.text), child: const Text('保存校正'))])); if (value != null) { await prefs.setString(key, value); if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('歌词校正已保存到本机'))); } }, icon: const Icon(Icons.edit_note), label: const Text('歌词校正'))]),",
    1,
)

path.write_text(text, encoding='utf-8')
print('PATCH_PLAYBACK_V355_OK')
