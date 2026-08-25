from pathlib import Path
import re

path = Path('mobile/lib/main.dart')
text = path.read_text(encoding='utf-8')
text = re.sub(r"const appVersion = '3\.5\.[0-9]+';", "const appVersion = '3.5.10';", text, count=1)

state_anchor = "  final Map<int, double> offlineDownloadProgress = <int, double>{};"
if state_anchor in text and "int? serverLatencyMs;" not in text:
    text = text.replace(state_anchor, state_anchor + "\n  int? serverLatencyMs;", 1)

method_anchor = "  Future<void> setStemEnabled(String name, bool enabled) async {"
if method_anchor not in text:
    raise SystemExit('setStemEnabled anchor missing')

helpers = r'''  Future<int?> _measureServerLatency() async {
    final values = <int>[];
    for (var i = 0; i < 3; i++) {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
      final sw = Stopwatch()..start();
      try {
        final request = await client.getUrl(Uri.parse('${widget.store.serverBase}/api/v1/library/mobile/health'));
        request.headers.set(HttpHeaders.cacheControlHeader, 'no-cache');
        final response = await request.close().timeout(const Duration(seconds: 12));
        await response.drain<void>();
        sw.stop();
        if (response.statusCode >= 200 && response.statusCode < 500) values.add(sw.elapsedMilliseconds);
      } catch (_) {
      } finally {
        client.close(force: true);
      }
    }
    if (values.isEmpty) return null;
    values.sort();
    return values[values.length ~/ 2];
  }

  Future<void> _showLocalProductLibrary(PipelineJob currentJob) async {
    final songById = <int, LibrarySong>{for (final s in widget.store.catalog) s.id: s};
    final currentSong = songById[currentJob.libraryId];
    if (!mounted) return;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(builder: (sheetContext, refresh) {
        final folders = widget.store.performanceAlbums.entries.toList();
        return SafeArea(child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
          child: SizedBox(height: MediaQuery.of(sheetContext).size.height * .72, child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(children: [
                const Expanded(child: Text('本地成品库', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800))),
                FilledButton.icon(
                  onPressed: () async {
                    final controller = TextEditingController();
                    final name = await showDialog<String>(context: sheetContext, builder: (dialogContext) => AlertDialog(
                      title: const Text('新建本地目录'),
                      content: TextField(controller: controller, autofocus: true, decoration: const InputDecoration(hintText: '例如：常用演出、粤语歌、排练曲目')),
                      actions: [
                        TextButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('取消')),
                        FilledButton(onPressed: () => Navigator.pop(dialogContext, controller.text.trim()), child: const Text('创建')),
                      ],
                    ));
                    if (name != null && name.isNotEmpty) {
                      await widget.store.createPerformanceAlbum(name);
                      refresh(() {});
                    }
                  },
                  icon: const Icon(Icons.create_new_folder_outlined),
                  label: const Text('新建目录'),
                ),
              ]),
              const SizedBox(height: 10),
              const Text('目录只保存曲目关系；已下载的原曲、七轨、歌词和谱面仍保存在 App 本地成品区。'),
              const SizedBox(height: 10),
              Expanded(child: ListView.builder(
                itemCount: folders.length,
                itemBuilder: (context, index) {
                  final folder = folders[index];
                  final songs = folder.value.map((id) => songById[id]).whereType<LibrarySong>().toList();
                  final containsCurrent = currentSong != null && folder.value.contains(currentSong.id);
                  return Card(child: ExpansionTile(
                    title: Text(folder.key),
                    subtitle: Text('${songs.length} 首'),
                    trailing: currentSong == null ? null : IconButton(
                      tooltip: containsCurrent ? '从目录移除当前歌曲' : '把当前歌曲加入目录',
                      icon: Icon(containsCurrent ? Icons.remove_circle_outline : Icons.add_circle_outline),
                      onPressed: () async {
                        if (containsCurrent) {
                          await widget.store.removeSongFromAlbum(folder.key, currentSong.id);
                        } else {
                          if (!await _hasOfflineProduct(currentJob)) {
                            if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('请先下载当前歌曲成品到本地')));
                            return;
                          }
                          await widget.store.addSongToAlbum(folder.key, currentSong);
                        }
                        refresh(() {});
                      },
                    ),
                    children: [
                      for (final song in songs)
                        ListTile(
                          leading: const Icon(Icons.offline_pin),
                          title: Text(song.title),
                          subtitle: Text(song.artist),
                          trailing: IconButton(
                            tooltip: '从目录移除',
                            icon: const Icon(Icons.remove_circle_outline),
                            onPressed: () async { await widget.store.removeSongFromAlbum(folder.key, song.id); refresh(() {}); },
                          ),
                          onTap: () async {
                            await widget.store.addLibrarySong(song);
                            if (sheetContext.mounted) Navigator.pop(sheetContext);
                            if (mounted) setState(() {});
                          },
                        ),
                    ],
                  ));
                },
              )),
            ],
          )),
        ));
      }),
    );
  }

'''
if "Future<int?> _measureServerLatency()" not in text:
    text = text.replace(method_anchor, helpers + method_anchor, 1)

download_pattern = re.compile(
    r"  Future<void> _downloadToFile\(String url, File target, String token, void Function\(double\) onProgress\) async \{.*?\n  \}\n\n  Future<void> downloadProductOffline\(PipelineJob job\) async \{.*?\n  \}\n\n  Future<void> deleteOfflineProduct",
    re.S,
)
download_replacement = r'''  Future<void> _downloadToFile(String url, File target, String token, void Function(double) onProgress) async {
    if (await target.exists() && await target.length() > 1024) { onProgress(1); return; }
    final part = File('${target.path}.part');
    var existing = await part.exists() ? await part.length() : 0;
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 20);
    try {
      final request = await client.getUrl(Uri.parse(url));
      if (token.isNotEmpty) request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
      if (existing > 0) request.headers.set(HttpHeaders.rangeHeader, 'bytes=$existing-');
      final response = await request.close().timeout(const Duration(minutes: 30));
      if (response.statusCode < 200 || response.statusCode >= 300) throw HttpException('HTTP ${response.statusCode}');
      final append = existing > 0 && response.statusCode == HttpStatus.partialContent;
      if (!append) existing = 0;
      final bodyLength = response.contentLength > 0 ? response.contentLength : 0;
      final total = bodyLength > 0 ? existing + bodyLength : 0;
      var received = existing;
      final sink = part.openWrite(mode: append ? FileMode.append : FileMode.write);
      await for (final chunk in response) {
        sink.add(chunk);
        received += chunk.length;
        if (total > 0) onProgress((received / total).clamp(0, 1));
      }
      await sink.close();
      if (!await part.exists() || await part.length() < 1024) throw const FileSystemException('下载文件为空');
      try { if (await target.exists()) await target.delete(); } catch (_) {}
      try { await part.rename(target.path); } catch (_) { await part.copy(target.path); try { await part.delete(); } catch (_) {} }
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
      'stem_vocals.wav':'artifacts/stem_vocals', 'stem_drums.wav':'artifacts/stem_drums',
      'stem_bass.wav':'artifacts/stem_bass', 'stem_guitar.wav':'artifacts/stem_guitar',
      'stem_electric_guitar.wav':'artifacts/stem_electric_guitar', 'stem_piano.wav':'artifacts/stem_piano',
      'stem_other.wav':'artifacts/stem_other', 'lyrics_timeline.json':'artifacts/lyrics_timeline',
      'score_data.json':'artifacts/score_data',
    };
    offlineDownloadProgress[job.libraryId] = 0;
    if (mounted) setState(() {});
    final progress = <String, double>{for (final key in assets.keys) key: 0};
    void updateOverall() {
      final value = progress.values.fold<double>(0, (a, b) => a + b) / progress.length;
      offlineDownloadProgress[job.libraryId] = value.clamp(0, 1);
      if (mounted) setState(() {});
    }
    try {
      await Future.wait(assets.entries.map((entry) async {
        final url = '${widget.store.serverBase}/api/v1/library/mobile/catalog/${job.libraryId}/${entry.value}';
        final target = File('${dir.path}${Platform.pathSeparator}${entry.key}');
        await _downloadToFile(url, target, token, (part) { progress[entry.key] = part; updateOverall(); });
      }));
      offlineReady.add(job.libraryId);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('成品已完整下载到本地，可离线演奏')));
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('下载已暂停，已保存进度；解锁后点“继续下载”即可断点续传')));
    } finally {
      offlineDownloadProgress.remove(job.libraryId);
      if (mounted) setState(() {});
    }
  }

  Future<void> deleteOfflineProduct'''
text, n = download_pattern.subn(download_replacement, text, count=1)
if n != 1:
    raise SystemExit('v3.5.9 offline downloader block target missing')

stem_pattern = re.compile(
    r"    final stemPlayers = <String, AudioPlayer>\{\};\n    var done = 0;\n    for \(final entry in keys\.entries\) \{.*?\n      done\+\+;\n    \}",
    re.S,
)
stem_replacement = r'''    final stemPlayers = <String, AudioPlayer>{};
    final stemProgress = <String, double>{for (final entry in keys.entries) entry.key: 0};
    void updateStemProgress() {
      if (!current()) return;
      final avg = stemProgress.values.fold<double>(0, (a, b) => a + b) / stemProgress.length;
      _advanceLoading(.4 + avg * .6, '七轨并行加载 ${(avg * 100).round()}%');
    }
    final stemResults = await Future.wait(keys.entries.map((entry) async {
      if (!current()) return null;
      final url = '${widget.store.serverBase}/api/v1/library/mobile/catalog/${job.libraryId}/artifacts/${entry.value}';
      final player = AudioPlayer();
      try {
        final local = await cacheAudio(
          url, entry.value, 'wav',
          onProgress: (x) { stemProgress[entry.key] = x; updateStemProgress(); },
        );
        if (!current()) { await player.dispose(); return null; }
        await player.setFilePath(local);
        if (!current()) { await player.dispose(); return null; }
        await player.setVolume((stemEnabled[entry.key] ?? true) ? (levels[entry.key] ?? .8) * masterVolume : 0);
        stemProgress[entry.key] = 1;
        updateStemProgress();
        return MapEntry(entry.key, player);
      } catch (_) {
        try { await player.dispose(); } catch (_) {}
        return null;
      }
    }).toList());
    for (final result in stemResults) {
      if (result != null) stemPlayers[result.key] = result.value;
    }'''
text, n = stem_pattern.subn(stem_replacement, text, count=1)
if n != 1:
    raise SystemExit('v3.5.9 serial stem loading target missing')

load_anchor = "    loadingJobId = job.id;\n    final generation = ++loadGeneration;"
if load_anchor in text and "serverLatencyMs = await _measureServerLatency();" not in text:
    text = text.replace(load_anchor, load_anchor + "\n    serverLatencyMs = await _measureServerLatency();", 1)

text = text.replace(
    "Text(loadingText, style: const TextStyle(color: Color(0xFFBDAAB5)))",
    "Text(serverLatencyMs == null ? loadingText : '$loadingText  ·  网络 ${serverLatencyMs}ms', style: const TextStyle(color: Color(0xFFBDAAB5)))",
    1,
)

ui_anchor = "        const SizedBox(height: 12),\n        Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(children: ["
if ui_anchor in text and "本地成品目录" not in text:
    text = text.replace(
        ui_anchor,
        "        Row(children: [\n          Expanded(child: OutlinedButton.icon(onPressed: () => _showLocalProductLibrary(job), icon: const Icon(Icons.folder_copy_outlined), label: const Text('本地成品目录'))),\n        ]),\n        const SizedBox(height: 12),\n        Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(children: [",
        1,
    )

if "七轨并行加载" not in text or "Future.wait(assets.entries.map" not in text:
    raise SystemExit('v3.5.10 parallel loading patch incomplete')
if "本地成品目录" not in text:
    raise SystemExit('v3.5.10 local product directory UI missing')
if "appVersion = '3.5.10'" not in text:
    raise SystemExit('v3.5.10 version stamp missing')

path.write_text(text, encoding='utf-8')
print('PATCH_OFFLINE_V3510_OK')
