from pathlib import Path
import re

path = Path('mobile/lib/main.dart')
text = path.read_text(encoding='utf-8')
text = re.sub(r"const appVersion = '3\.5\.[0-9]+';", "const appVersion = '3.5.3';", text, count=1)

# Be tolerant of older cached catalog rows: a published audio URL or recovered
# artifacts are enough to let the user open the finished product.  This fixes
# iOS appearing to ignore taps when stems_status in SharedPreferences is stale.
text = text.replace(
    "bool get isAiReady => publishStatus == '已发布' && processingStatus == '已完成' && stemsStatus == '完成';",
    "bool get isAiReady => (processingStatus == '已完成' || artifacts.isNotEmpty) && (publishStatus == '已发布' || audioUrl.isNotEmpty);",
)

# Replace the player loader.  Do not trust artifact URLs cached by older clients;
# construct the canonical mobile endpoint from libraryId, download through Dart's
# HTTPS stack, and play local files.  This avoids Android/iOS decoder issues with
# extension-less network endpoints and gives an original-audio fallback.
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
    final cacheRoot = Directory('${Directory.systemTemp.path}${Platform.pathSeparator}juweier_v353${Platform.pathSeparator}${job.libraryId > 0 ? job.libraryId : job.id}');
    await cacheRoot.create(recursive: true);
    final errors = <String>[];

    Future<String> cacheAudio(String url, String name, String extension) async {
      final target = File('${cacheRoot.path}${Platform.pathSeparator}$name.$extension');
      if (await target.exists() && await target.length() > 4096) return target.path;
      final temp = File('${target.path}.download');
      try { if (await temp.exists()) await temp.delete(); } catch (_) {}
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 20);
      try {
        var request = await client.getUrl(Uri.parse(url));
        if (token.isNotEmpty) request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
        request.headers.set(HttpHeaders.acceptHeader, 'audio/*,*/*;q=0.8');
        final response = await request.close().timeout(const Duration(seconds: 60));
        if (response.statusCode < 200 || response.statusCode >= 300) {
          throw HttpException('HTTP ${response.statusCode}', uri: Uri.parse(url));
        }
        final sink = temp.openWrite();
        await response.pipe(sink);
        if (!await temp.exists() || await temp.length() < 1024) throw const FileSystemException('音频缓存为空');
        if (await target.exists()) await target.delete();
        await temp.rename(target.path);
        return target.path;
      } finally {
        client.close(force: true);
      }
    }

    for (final entry in keys.entries) {
      final artifactKey = entry.value;
      var url = job.artifacts[artifactKey] ?? '';
      if (job.libraryId > 0) {
        url = '${widget.store.serverBase}/api/v1/library/mobile/catalog/${job.libraryId}/artifacts/$artifactKey';
      }
      if (url.isEmpty) continue;
      final player = AudioPlayer();
      try {
        final local = await cacheAudio(url, artifactKey, 'wav');
        await player.setFilePath(local);
        await player.setVolume((levels[entry.key] ?? .8) * masterVolume);
        players[entry.key] = player;
      } catch (error) {
        errors.add('${entry.key}: $error');
        await player.dispose();
      }
    }

    // Always provide a playable product when the server's original audio exists.
    // If no stem loaded, this keeps the play button enabled instead of grey.
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

    if (players.isNotEmpty) {
      loadedJobId = job.id;
      final master = players.values.first;
      positionSub = master.positionStream.listen((value) { if (mounted && !dragging) setState(() => position = value); });
      durationSub = master.durationStream.listen((value) { if (mounted && value != null) setState(() => duration = value); });
    } else {
      loadedJobId = '';
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(errors.isEmpty ? '歌曲音频暂时无法加载，请确认服务器在线后重试' : '歌曲音频加载失败：${errors.first}'),
          duration: const Duration(seconds: 8),
        ));
      }
    }
    if (mounted) setState(() {});
  }

  Future<void> stopPlayers() async {'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit('loadPlayers patch target not found')

# Replace the whole openProduct implementation so taps can never fail silently.
start = text.find('  Future<void> openProduct(LibrarySong song) async {')
end = text.find('  Future<void> createAlbum() async {', start)
if start < 0 or end < 0:
    raise SystemExit('openProduct patch target not found')
open_product = r'''  Future<void> openProduct(LibrarySong song) async {
    try {
      if (!song.isAiReady || song.artifacts.isEmpty) {
        await refresh();
        final refreshed = widget.store.catalog.where((item) => item.id == song.id);
        if (refreshed.isNotEmpty) song = refreshed.first;
      }
      if (song.audioUrl.isEmpty && song.artifacts.isEmpty) {
        if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('这首歌曲的服务器成果暂未恢复，请稍后刷新重试')));
        return;
      }
      await widget.store.addLibrarySong(song);
      if (!mounted) return;
      widget.onOpenProduct();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('打开歌曲失败：$error'), duration: const Duration(seconds: 6)));
      }
    }
  }

'''
text = text[:start] + open_product + text[end:]

# Any remaining strict tap guards should use the tolerant isAiReady getter and
# execute an awaited callback so iOS UI exceptions are surfaced.
text = text.replace(
    "onTap: song.isAiReady ? () => unawaited(openProduct(song)) : null,",
    "onTap: song.isAiReady ? () async { await openProduct(song); } : null,",
)
text = text.replace(
    "onTap: song.isAiReady ? () { Navigator.pop(context); unawaited(openProduct(song)); } : null,",
    "onTap: song.isAiReady ? () async { Navigator.pop(context); await openProduct(song); } : null,",
)

path.write_text(text, encoding='utf-8')
print('PATCH_PLAYBACK_V353_OK')
