from pathlib import Path
import re

path = Path('mobile/lib/main.dart')
text = path.read_text(encoding='utf-8')
text = re.sub(r"const appVersion = '3\.5\.[0-9]+';", "const appVersion = '3.5.9';", text, count=1)

if "package:path_provider/path_provider.dart" not in text:
    text = text.replace(
        "import 'package:just_audio/just_audio.dart';",
        "import 'package:just_audio/just_audio.dart';\nimport 'package:path_provider/path_provider.dart';",
        1,
    )

anchor = "  bool stemMixerActive = false;"
if anchor not in text:
    raise SystemExit('stemMixerActive field missing')
if "offlineDownloadProgress" not in text:
    text = text.replace(
        anchor,
        anchor + "\n  final Set<int> offlineReady = <int>{};\n  final Map<int, double> offlineDownloadProgress = <int, double>{};",
        1,
    )

# Persist playback cache in application support storage.
old_cache = re.compile(
    r"final cacheRoot = Directory\('\$\{Directory\.systemTemp\.path\}\$\{Platform\.pathSeparator\}juweier_v357\$\{Platform\.pathSeparator\}\$\{job\.libraryId > 0 \? job\.libraryId : job\.id\}'\);\n\s*await cacheRoot\.create\(recursive: true\);"
)
new_cache = (
    "final supportRoot = await getApplicationSupportDirectory();\n"
    "    final cacheRoot = Directory('${supportRoot.path}${Platform.pathSeparator}offline_products${Platform.pathSeparator}${job.libraryId > 0 ? job.libraryId : job.id}');\n"
    "    await cacheRoot.create(recursive: true);"
)
text, cache_count = old_cache.subn(new_cache, text, count=1)
if cache_count != 1 and "offline_products" not in text:
    raise SystemExit('persistent cache target missing')

method_anchor = "  Future<void> setStemEnabled(String name, bool enabled) async {"
if method_anchor not in text:
    raise SystemExit('setStemEnabled anchor missing')
if "Future<void> downloadProductOffline" not in text:
    methods = r'''  Future<Directory> _offlineDir(PipelineJob job) async {
    final root = await getApplicationSupportDirectory();
    final dir = Directory('${root.path}${Platform.pathSeparator}offline_products${Platform.pathSeparator}${job.libraryId > 0 ? job.libraryId : job.id}');
    await dir.create(recursive: true);
    return dir;
  }

  Future<bool> _hasOfflineProduct(PipelineJob job) async {
    final dir = await _offlineDir(job);
    const required = ['original.mp3','stem_vocals.wav','stem_drums.wav','stem_bass.wav','stem_guitar.wav','stem_electric_guitar.wav','stem_piano.wav','stem_other.wav'];
    for (final name in required) {
      final file = File('${dir.path}${Platform.pathSeparator}$name');
      if (!await file.exists() || await file.length() < 1024) return false;
    }
    return true;
  }

  Future<void> _downloadToFile(String url, File target, String token, void Function(double) onProgress) async {
    if (await target.exists() && await target.length() > 1024) { onProgress(1); return; }
    final temp = File('${target.path}.download');
    try { if (await temp.exists()) await temp.delete(); } catch (_) {}
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 20);
    try {
      final request = await client.getUrl(Uri.parse(url));
      if (token.isNotEmpty) request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
      final response = await request.close().timeout(const Duration(seconds: 90));
      if (response.statusCode < 200 || response.statusCode >= 300) throw HttpException('HTTP ${response.statusCode}');
      final total = response.contentLength > 0 ? response.contentLength : 0;
      var received = 0;
      final sink = temp.openWrite();
      await for (final chunk in response) {
        sink.add(chunk);
        received += chunk.length;
        if (total > 0) onProgress((received / total).clamp(0, 1).toDouble());
      }
      await sink.close();
      if (!await temp.exists() || await temp.length() < 1024) throw const FileSystemException('下载文件为空');
      try { if (await target.exists()) await target.delete(); } catch (_) {}
      try {
        await temp.rename(target.path);
      } catch (_) {
        await temp.copy(target.path);
        try { await temp.delete(); } catch (_) {}
      }
      onProgress(1);
    } finally {
      client.close(force: true);
    }
  }

  Future<void> downloadProductOffline(PipelineJob job) async {
    if (job.libraryId <= 0 || offlineDownloadProgress.containsKey(job.libraryId)) return;
    final dir = await _offlineDir(job);
    final token = widget.store.accountToken.isNotEmpty ? widget.store.accountToken : widget.store.apiToken;
    const assets = <String, String>{
      'original.mp3':'audio',
      'stem_vocals.wav':'artifacts/stem_vocals',
      'stem_drums.wav':'artifacts/stem_drums',
      'stem_bass.wav':'artifacts/stem_bass',
      'stem_guitar.wav':'artifacts/stem_guitar',
      'stem_electric_guitar.wav':'artifacts/stem_electric_guitar',
      'stem_piano.wav':'artifacts/stem_piano',
      'stem_other.wav':'artifacts/stem_other',
      'lyrics_timeline.json':'artifacts/lyrics_timeline',
      'score_data.json':'artifacts/score_data',
    };
    offlineDownloadProgress[job.libraryId] = 0;
    if (mounted) setState(() {});
    var done = 0;
    try {
      for (final entry in assets.entries) {
        final url = '${widget.store.serverBase}/api/v1/library/mobile/catalog/${job.libraryId}/${entry.value}';
        final target = File('${dir.path}${Platform.pathSeparator}${entry.key}');
        await _downloadToFile(url, target, token, (part) {
          offlineDownloadProgress[job.libraryId] = ((done + part) / assets.length).clamp(0, 1).toDouble();
          if (mounted) setState(() {});
        });
        done++;
      }
      offlineReady.add(job.libraryId);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('成品已下载到本地，后续演奏无需重新加载分轨')));
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('本地成品下载失败：$error')));
    } finally {
      offlineDownloadProgress.remove(job.libraryId);
      if (mounted) setState(() {});
    }
  }

  Future<void> deleteOfflineProduct(PipelineJob job) async {
    final dir = await _offlineDir(job);
    if (await dir.exists()) await dir.delete(recursive: true);
    offlineReady.remove(job.libraryId);
    if (mounted) setState(() {});
  }

'''
    text = text.replace(method_anchor, methods + method_anchor, 1)

text = text.replace("url, 'original_${job.libraryId}', 'mp3',", "url, 'original', 'mp3',", 1)

transport_pattern = re.compile(r"IconButton\.filled\(onPressed: players\.isEmpty \? null : togglePlay, icon: Icon\(players\.isNotEmpty && players\.values\.first\.playing \? Icons\.pause : Icons\.play_arrow\)\)")
transport = "FilledButton.icon(onPressed: players.isEmpty ? null : togglePlay, icon: Icon(players.isNotEmpty && players.values.first.playing ? Icons.pause_circle_filled : Icons.play_circle_fill), label: Text(players.isNotEmpty && players.values.first.playing ? '暂停' : '播放'))"
text, n = transport_pattern.subn(transport, text, count=1)
if n != 1 and "label: Text(players.isNotEmpty" not in text:
    raise SystemExit('main transport button target missing')

selector_marker = "          decoration: const InputDecoration(labelText: '当前歌曲'),\n        ),\n        const SizedBox(height: 12),"
if "下载 AI 成品到本地" not in text:
    offline_ui = r'''          decoration: const InputDecoration(labelText: '当前歌曲'),
        ),
        const SizedBox(height: 8),
        FutureBuilder<bool>(
          future: _hasOfflineProduct(job),
          builder: (context, snapshot) {
            final ready = snapshot.data == true || offlineReady.contains(job.libraryId);
            final downloading = offlineDownloadProgress[job.libraryId];
            return Card(child: Padding(padding: const EdgeInsets.all(12), child: Column(children: [
              Row(children: [
                Icon(ready ? Icons.offline_pin : Icons.cloud_download_outlined, color: ready ? Colors.greenAccent : accent),
                const SizedBox(width: 8),
                Expanded(child: Text(ready ? '本地成品已就绪 · 演奏无需重新加载' : '下载 AI 成品到本地 · 原曲/七轨/歌词/谱面')),
                if (ready)
                  OutlinedButton.icon(onPressed: () => deleteOfflineProduct(job), icon: const Icon(Icons.delete_outline), label: const Text('删除本地'))
                else
                  FilledButton.icon(onPressed: downloading == null ? () => downloadProductOffline(job) : null, icon: const Icon(Icons.download_for_offline), label: Text(downloading == null ? '下载成品' : '${(downloading * 100).round()}%')),
              ]),
              if (downloading != null) ...[const SizedBox(height: 8), LinearProgressIndicator(value: downloading)],
            ])));
          },
        ),
        const SizedBox(height: 12),'''
    if selector_marker not in text:
        raise SystemExit('selector UI marker missing')
    text = text.replace(selector_marker, offline_ui, 1)

text = text.replace(
    "IconButton(onPressed: () async { await performanceKey.currentState?.togglePlay(); if (mounted) setState(() {}); }, icon: const Icon(Icons.play_arrow)),",
    "TextButton.icon(onPressed: () async { await performanceKey.currentState?.togglePlay(); if (mounted) setState(() {}); }, icon: const Icon(Icons.play_circle_fill), label: const Text('播放/暂停')),",
    1,
)

text = text.replace(
    "      stemMixerActive = true;\n      _advanceLoading(1, '分轨混音已接管播放');",
    "      stemMixerActive = true;\n      if (job.libraryId > 0 && await _hasOfflineProduct(job)) offlineReady.add(job.libraryId);\n      _advanceLoading(1, '分轨混音已接管播放');",
    1,
)

if "downloadProductOffline" not in text or "getApplicationSupportDirectory" not in text:
    raise SystemExit('offline feature patch missing')
if "appVersion = '3.5.9'" not in text:
    raise SystemExit('version stamp missing')

path.write_text(text, encoding='utf-8')
print('PATCH_OFFLINE_V359_OK')
