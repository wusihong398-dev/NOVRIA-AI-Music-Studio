from pathlib import Path
import re

path = Path('mobile/lib/main.dart')
text = path.read_text(encoding='utf-8')
text = re.sub(r"const appVersion = '3\.5\.[0-9]+';", "const appVersion = '3.5.4';", text, count=1)

pattern = re.compile(
    r"  Future<void> loadPlayers\(PipelineJob job\) async \{.*?\n  \}\n\n  Future<void> stopPlayers\(\) async \{",
    re.S,
)
replacement = r'''  Future<void> loadPlayers(PipelineJob job) async {
    if (loadedJobId == job.id && players.isNotEmpty) return;
    await stopPlayers();
    final token = widget.store.accountToken.isNotEmpty ? widget.store.accountToken : widget.store.apiToken;
    final cacheRoot = Directory('${Directory.systemTemp.path}${Platform.pathSeparator}juweier_v354${Platform.pathSeparator}${job.libraryId > 0 ? job.libraryId : job.id}');
    await cacheRoot.create(recursive: true);
    final errors = <String>[];

    Future<String> cacheAudio(String url, String name, String extension) async {
      final target = File('${cacheRoot.path}${Platform.pathSeparator}$name.$extension');
      if (await target.exists() && await target.length() > 4096) return target.path;
      final temp = File('${target.path}.${DateTime.now().microsecondsSinceEpoch}.download');
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 15);
      try {
        final request = await client.getUrl(Uri.parse(url));
        if (token.isNotEmpty) request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
        request.headers.set(HttpHeaders.acceptHeader, 'audio/*,*/*;q=0.8');
        final response = await request.close().timeout(const Duration(seconds: 45));
        if (response.statusCode < 200 || response.statusCode >= 300) {
          throw HttpException('HTTP ${response.statusCode}', uri: Uri.parse(url));
        }
        final sink = temp.openWrite();
        await response.pipe(sink);
        if (!await temp.exists() || await temp.length() < 1024) throw const FileSystemException('音频缓存为空');
        try { if (await target.exists()) await target.delete(); } catch (_) {}
        try {
          await temp.rename(target.path);
        } catch (_) {
          await temp.copy(target.path);
          try { await temp.delete(); } catch (_) {}
        }
        return target.path;
      } finally {
        client.close(force: true);
      }
    }

    // v3.5.4: original audio is the fast first-play path.  Do not make the
    // user wait for seven large WAV stems before enabling the transport.
    if (job.libraryId > 0) {
      final preview = AudioPlayer();
      try {
        final url = '${widget.store.serverBase}/api/v1/library/mobile/catalog/${job.libraryId}/audio';
        final local = await cacheAudio(url, 'original_${job.libraryId}', 'mp3');
        await preview.setFilePath(local);
        await preview.setVolume(masterVolume);
        players['原曲'] = preview;
        loadedJobId = job.id;
        positionSub = preview.positionStream.listen((value) { if (mounted && !dragging) setState(() => position = value); });
        durationSub = preview.durationStream.listen((value) { if (mounted && value != null) setState(() => duration = value); });
        if (mounted) setState(() {});
        unawaited(preview.play());
      } catch (error) {
        errors.add('原曲: $error');
        await preview.dispose();
      }
    }

    if (players.isEmpty) {
      loadedJobId = '';
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(errors.isEmpty ? '歌曲原曲暂时无法加载，请确认服务器在线' : '歌曲播放失败：${errors.first}'),
          duration: const Duration(seconds: 8),
        ));
      }
      return;
    }

    // Download stems in the background.  Once available, atomically switch
    // from original preview to the synchronized stem mixer at the same position.
    Future<void> loadStemsInBackground() async {
      const keys = {
        '人声': 'stem_vocals', '鼓': 'stem_drums', '贝斯': 'stem_bass',
        '木吉他': 'stem_guitar', '电吉他': 'stem_electric_guitar',
        '钢琴': 'stem_piano', '其他': 'stem_other',
      };
      final stemPlayers = <String, AudioPlayer>{};
      for (final entry in keys.entries) {
        if (loadedJobId != job.id) break;
        final artifactKey = entry.value;
        final url = job.libraryId > 0
            ? '${widget.store.serverBase}/api/v1/library/mobile/catalog/${job.libraryId}/artifacts/$artifactKey'
            : (job.artifacts[artifactKey] ?? '');
        if (url.isEmpty) continue;
        final p = AudioPlayer();
        try {
          final local = await cacheAudio(url, artifactKey, 'wav');
          await p.setFilePath(local);
          await p.setVolume((levels[entry.key] ?? .8) * masterVolume);
          stemPlayers[entry.key] = p;
        } catch (_) {
          await p.dispose();
        }
      }
      if (stemPlayers.isEmpty || loadedJobId != job.id) {
        for (final p in stemPlayers.values) { await p.dispose(); }
        return;
      }
      final old = players.values.first;
      final oldPosition = old.position;
      final wasPlaying = old.playing;
      await positionSub?.cancel();
      await durationSub?.cancel();
      for (final p in players.values) { await p.pause(); await p.dispose(); }
      players
        ..clear()
        ..addAll(stemPlayers);
      for (final p in players.values) { await p.seek(oldPosition); }
      final master = players.values.first;
      positionSub = master.positionStream.listen((value) { if (mounted && !dragging) setState(() => position = value); });
      durationSub = master.durationStream.listen((value) { if (mounted && value != null) setState(() => duration = value); });
      if (wasPlaying) {
        for (final p in players.values) { unawaited(p.play()); }
      }
      if (mounted) setState(() {});
    }
    unawaited(loadStemsInBackground());
  }

  Future<void> stopPlayers() async {'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit('loadPlayers patch target not found')

# Ensure every ordinary song-row tap awaits the open operation on iOS.
text = text.replace(
    "onTap: song.isAiReady ? () => unawaited(openProduct(song)) : null,",
    "onTap: song.isAiReady ? () async { await openProduct(song); } : null,",
)

path.write_text(text, encoding='utf-8')
print('PATCH_PLAYBACK_V354_OK')
