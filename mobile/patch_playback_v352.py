from pathlib import Path
import re

path = Path('mobile/lib/main.dart')
text = path.read_text(encoding='utf-8')
text = text.replace("const appVersion = '3.5.0';", "const appVersion = '3.5.2';")
text = text.replace("const appVersion = '3.5.1';", "const appVersion = '3.5.2';")

pattern = re.compile(
    r"  Future<void> loadPlayers\(PipelineJob job\) async \{.*?\n  \}\n\n  Future<void> stopPlayers\(\) async \{",
    re.S,
)
replacement = r'''  Future<void> loadPlayers(PipelineJob job) async {
    if (loadedJobId == job.id && players.isNotEmpty) return;
    await stopPlayers();
    const keys = {
      '人声': 'stem_vocals', '鼓': 'stem_drums', '贝斯': 'stem_bass',
      '木吉他': 'stem_guitar', '电吉他': 'stem_electric_guitar',
      '钢琴': 'stem_piano', '其他': 'stem_other',
    };
    final token = widget.store.accountToken.isNotEmpty ? widget.store.accountToken : widget.store.apiToken;
    final cacheRoot = await Directory.systemTemp.createTemp('juweier_${job.libraryId}_');
    final errors = <String>[];

    Future<String> cacheAudio(String url, String name, String extension) async {
      final target = File('${cacheRoot.path}${Platform.pathSeparator}$name.$extension');
      final client = HttpClient();
      try {
        final request = await client.getUrl(Uri.parse(url));
        if (token.isNotEmpty) request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
        request.headers.set(HttpHeaders.acceptHeader, 'audio/*,*/*;q=0.8');
        final response = await request.close();
        if (response.statusCode < 200 || response.statusCode >= 300) {
          throw HttpException('HTTP ${response.statusCode}', uri: Uri.parse(url));
        }
        final sink = target.openWrite();
        await response.pipe(sink);
        if (!await target.exists() || await target.length() == 0) throw const FileSystemException('音频缓存为空');
        return target.path;
      } finally {
        client.close(force: true);
      }
    }

    for (final entry in keys.entries) {
      final url = job.artifacts[entry.value];
      if (url == null || url.isEmpty) continue;
      final player = AudioPlayer();
      try {
        final local = await cacheAudio(url, entry.value, 'wav');
        await player.setFilePath(local);
        await player.setVolume((levels[entry.key] ?? .8) * masterVolume);
        players[entry.key] = player;
      } catch (error) {
        errors.add('${entry.key}: $error');
        await player.dispose();
      }
    }

    // Fallback: even when a stem decoder fails, keep the published original
    // playable so the product page never presents a permanently disabled button.
    if (players.isEmpty && job.libraryId > 0) {
      final fallback = AudioPlayer();
      try {
        final url = '${widget.store.serverBase}/api/v1/library/mobile/catalog/${job.libraryId}/audio';
        final local = await cacheAudio(url, 'original_${job.libraryId}', 'mp3');
        await fallback.setFilePath(local);
        await fallback.setVolume(masterVolume);
        players['原曲'] = fallback;
      } catch (error) {
        errors.add('原曲: $error');
        await fallback.dispose();
      }
    }

    loadedJobId = job.id;
    if (players.isNotEmpty) {
      final master = players.values.first;
      positionSub = master.positionStream.listen((value) { if (mounted && !dragging) setState(() => position = value); });
      durationSub = master.durationStream.listen((value) { if (mounted && value != null) setState(() => duration = value); });
    } else if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(errors.isEmpty ? '歌曲音频暂时无法加载，请确认服务器在线' : '歌曲音频加载失败：${errors.first}'),
        duration: const Duration(seconds: 6),
      ));
    }
    if (mounted) setState(() {});
  }

  Future<void> stopPlayers() async {'''

text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit('loadPlayers patch target not found')

# Make a failed asynchronous open visible instead of appearing as a dead tap.
text = text.replace(
    "onTap: song.isAiReady ? () => unawaited(openProduct(song)) : null,",
    "onTap: song.isAiReady ? () async { try { await openProduct(song); } catch (e) { if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('打开歌曲失败：$e'))); } } : null,",
)

path.write_text(text, encoding='utf-8')
print('PATCH_PLAYBACK_V352_OK')
