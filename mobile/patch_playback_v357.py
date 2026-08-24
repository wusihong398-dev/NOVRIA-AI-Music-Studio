from pathlib import Path
import re

path = Path('mobile/lib/main.dart')
text = path.read_text(encoding='utf-8')
text = re.sub(r"const appVersion = '3\.5\.[0-9]+';", "const appVersion = '3.5.7';", text, count=1)

# One loading transaction at a time. Rebuilds used to call loadPlayers repeatedly
# before loadedJobId was set, creating multiple original players that all auto-played.
state_anchor = "  bool stemsReady = false;"
if state_anchor not in text:
    raise SystemExit('stemsReady field missing')
text = text.replace(
    state_anchor,
    state_anchor + "\n  String loadingJobId = '';\n  int loadGeneration = 0;",
    1,
)

pattern = re.compile(
    r"  Future<void> loadPlayers\(PipelineJob job\) async \{.*?\n  \}\n\n  Future<void> stopPlayers\(\) async \{",
    re.S,
)
replacement = r'''  Future<void> loadPlayers(PipelineJob job) async {
    if (loadedJobId == job.id && players.isNotEmpty) return;
    // Critical v3.5.7 guard: while ANY song is loading, rebuilds or repeated taps
    // may not start another AudioPlayer/download transaction.
    if (loadingJobId.isNotEmpty) return;
    loadingJobId = job.id;
    final generation = ++loadGeneration;

    // Reset the previous transport without invalidating this generation.
    await positionSub?.cancel();
    await durationSub?.cancel();
    positionSub = null;
    durationSub = null;
    for (final player in players.values.toList()) {
      try { await player.pause(); } catch (_) {}
      try { await player.dispose(); } catch (_) {}
    }
    players.clear();
    loadedJobId = '';
    position = Duration.zero;
    duration = Duration.zero;
    stemsReady = false;
    loadingProgress = 0;
    _advanceLoading(.02, '正在连接歌曲服务器…');

    final token = widget.store.accountToken.isNotEmpty ? widget.store.accountToken : widget.store.apiToken;
    final cacheRoot = Directory('${Directory.systemTemp.path}${Platform.pathSeparator}juweier_v357${Platform.pathSeparator}${job.libraryId > 0 ? job.libraryId : job.id}');
    await cacheRoot.create(recursive: true);

    bool current() => mounted && generation == loadGeneration && loadingJobId == job.id;

    Future<String> cacheAudio(String url, String name, String extension, {void Function(double)? onProgress}) async {
      final target = File('${cacheRoot.path}${Platform.pathSeparator}$name.$extension');
      if (await target.exists() && await target.length() > 4096) {
        onProgress?.call(1);
        return target.path;
      }
      final temp = File('${target.path}.${DateTime.now().microsecondsSinceEpoch}.download');
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 15);
      try {
        final request = await client.getUrl(Uri.parse(url));
        if (token.isNotEmpty) request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
        request.headers.set(HttpHeaders.acceptHeader, 'audio/*,*/*;q=0.8');
        final response = await request.close().timeout(const Duration(seconds: 45));
        if (response.statusCode < 200 || response.statusCode >= 300) throw HttpException('HTTP ${response.statusCode}');
        final total = response.contentLength > 0 ? response.contentLength : 0;
        var received = 0;
        final sink = temp.openWrite();
        await for (final chunk in response) {
          if (generation != loadGeneration) break;
          sink.add(chunk);
          received += chunk.length;
          if (total > 0) onProgress?.call((received / total).clamp(0, 1));
        }
        await sink.close();
        if (generation != loadGeneration) throw const FileSystemException('加载任务已取消');
        if (!await temp.exists() || await temp.length() < 1024) throw const FileSystemException('音频缓存为空');
        try { if (await target.exists()) await target.delete(); } catch (_) {}
        try {
          await temp.rename(target.path);
        } catch (_) {
          await temp.copy(target.path);
          try { await temp.delete(); } catch (_) {}
        }
        onProgress?.call(1);
        return target.path;
      } finally {
        client.close(force: true);
        if (generation != loadGeneration) {
          try { if (await temp.exists()) await temp.delete(); } catch (_) {}
        }
      }
    }

    final preview = AudioPlayer();
    try {
      if (job.libraryId <= 0) throw const FormatException('歌曲缺少服务器曲库 ID');
      _advanceLoading(loadingProgress, '正在加载原曲…');
      final url = '${widget.store.serverBase}/api/v1/library/mobile/catalog/${job.libraryId}/audio';
      final local = await cacheAudio(
        url, 'original_${job.libraryId}', 'mp3',
        onProgress: (p) { if (current()) _advanceLoading(.05 + p * .35, '正在加载原曲…'); },
      );
      if (!current()) { await preview.dispose(); return; }
      await preview.setFilePath(local);
      if (!current()) { await preview.dispose(); return; }
      await preview.setVolume(masterVolume);
      players['原曲'] = preview;
      loadedJobId = job.id;
      positionSub = preview.positionStream.listen((value) {
        if (current() && !dragging) setState(() => position = value);
      });
      durationSub = preview.durationStream.listen((value) {
        if (current() && value != null) setState(() => duration = value);
      });
      _advanceLoading(.4, '原曲已就绪，后台加载分轨…');
      // Exactly one auto-play call exists in the whole load transaction.
      if (current()) unawaited(preview.play());
    } catch (error) {
      try { await preview.dispose(); } catch (_) {}
      if (current()) {
        _advanceLoading(loadingProgress, '原曲加载失败：$error');
        loadingJobId = '';
        if (mounted) setState(() {});
      }
      return;
    }

    const keys = {
      '人声':'stem_vocals','鼓':'stem_drums','贝斯':'stem_bass',
      '木吉他':'stem_guitar','电吉他':'stem_electric_guitar',
      '钢琴':'stem_piano','其他':'stem_other',
    };
    final stemPlayers = <String, AudioPlayer>{};
    var done = 0;
    for (final entry in keys.entries) {
      if (!current()) break;
      _advanceLoading(loadingProgress, '正在加载${entry.key}分轨 ${done + 1}/7');
      final url = '${widget.store.serverBase}/api/v1/library/mobile/catalog/${job.libraryId}/artifacts/${entry.value}';
      final player = AudioPlayer();
      try {
        final local = await cacheAudio(
          url, entry.value, 'wav',
          onProgress: (x) {
            if (current()) _advanceLoading(.4 + ((done + x) / 7) * .6, '正在加载${entry.key}分轨 ${done + 1}/7');
          },
        );
        if (!current()) { await player.dispose(); break; }
        await player.setFilePath(local);
        if (!current()) { await player.dispose(); break; }
        await player.setVolume((stemEnabled[entry.key] ?? true) ? (levels[entry.key] ?? .8) * masterVolume : 0);
        stemPlayers[entry.key] = player;
      } catch (_) {
        try { await player.dispose(); } catch (_) {}
      }
      done++;
    }

    if (!current()) {
      for (final p in stemPlayers.values) { try { await p.dispose(); } catch (_) {} }
      return;
    }

    // If the user selected another song while this one was downloading, do not
    // let the old transaction take over the player when it finishes.
    if (widget.store.activePerformanceJobId != job.id) {
      for (final p in stemPlayers.values) { try { await p.dispose(); } catch (_) {} }
      loadingJobId = '';
      if (mounted) setState(() {});
      return;
    }

    if (stemPlayers.isNotEmpty) {
      final old = players.values.first;
      final oldPosition = old.position;
      final wasPlaying = old.playing;
      await positionSub?.cancel();
      await durationSub?.cancel();
      for (final p in players.values.toList()) {
        try { await p.pause(); } catch (_) {}
        try { await p.dispose(); } catch (_) {}
      }
      players..clear()..addAll(stemPlayers);
      for (final p in players.values) { await p.seek(oldPosition); }
      final master = players.values.first;
      positionSub = master.positionStream.listen((value) {
        if (mounted && generation == loadGeneration && !dragging) setState(() => position = value);
      });
      durationSub = master.durationStream.listen((value) {
        if (mounted && generation == loadGeneration && value != null) setState(() => duration = value);
      });
      stemsReady = true;
      _advanceLoading(1, '七轨混音已就绪');
      if (wasPlaying && generation == loadGeneration) {
        for (final p in players.values) { unawaited(p.play()); }
      }
    } else {
      _advanceLoading(1, '原曲播放中，分轨暂未加载');
    }

    if (generation == loadGeneration) {
      loadingJobId = '';
      if (mounted) setState(() {});
    }
  }

  Future<void> stopPlayers() async {'''

text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit('v3.5.7 loadPlayers target not found')

# Explicit stop/page disposal invalidates every outstanding async callback.
text = text.replace(
    "  Future<void> stopPlayers() async {\n    await positionSub?.cancel();",
    "  Future<void> stopPlayers() async {\n    loadGeneration++;\n    loadingJobId = '';\n    await positionSub?.cancel();",
    1,
)

# Rebuild scheduling must also consider an in-flight load; otherwise every
# frame may enqueue another post-frame callback before the first load finishes.
text = text.replace(
    "if (loadedJobId != job.id && job.isDone) {\n      WidgetsBinding.instance.addPostFrameCallback((_) => loadPlayers(job));\n    }",
    "if (loadedJobId != job.id && loadingJobId.isEmpty && job.isDone) {\n      WidgetsBinding.instance.addPostFrameCallback((_) { if (mounted && loadingJobId.isEmpty) unawaited(loadPlayers(job)); });\n    }",
    1,
)

if "String loadingJobId = '';" not in text or "int loadGeneration = 0;" not in text:
    raise SystemExit('v3.5.7 concurrency fields missing')
if "if (loadingJobId.isNotEmpty) return;" not in text:
    raise SystemExit('v3.5.7 duplicate-load guard missing')
if "loadingJobId.isEmpty && job.isDone" not in text:
    raise SystemExit('v3.5.7 rebuild guard missing')

path.write_text(text, encoding='utf-8')
print('PATCH_PLAYBACK_V357_OK')
