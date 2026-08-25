from pathlib import Path
import re

path = Path('mobile/lib/main.dart')
text = path.read_text(encoding='utf-8')
text = re.sub(r"const appVersion = '3\.5\.[0-9]+';", "const appVersion = '3.5.11';", text, count=1)

# An offline product is complete when the seven lightweight M4A stems are present.
has_pattern = re.compile(
    r"  Future<bool> _hasOfflineProduct\(PipelineJob job\) async \{.*?\n  \}\n\n  Future<void> _downloadToFile",
    re.S,
)
has_replacement = r'''  Future<bool> _hasOfflineProduct(PipelineJob job) async {
    final dir = await _offlineDir(job);
    const required = [
      'original.mp3',
      'stem_vocals.m4a','stem_drums.m4a','stem_bass.m4a','stem_guitar.m4a',
      'stem_electric_guitar.m4a','stem_piano.m4a','stem_other.m4a',
    ];
    for (final name in required) {
      final file = File('${dir.path}${Platform.pathSeparator}$name');
      if (!await file.exists() || await file.length() < 1024) return false;
    }
    return true;
  }

  Future<void> _downloadToFile'''
text, n = has_pattern.subn(has_replacement, text, count=1)
if n != 1:
    raise SystemExit('v3.5.9 _hasOfflineProduct target missing')

# Offline package: download playback-optimized AAC/M4A stems instead of huge WAV files.
assets_pattern = re.compile(
    r"    const assets = <String, String>\{\n      'original\.mp3':'audio',\n      'stem_vocals\.wav':'artifacts/stem_vocals', 'stem_drums\.wav':'artifacts/stem_drums',\n      'stem_bass\.wav':'artifacts/stem_bass', 'stem_guitar\.wav':'artifacts/stem_guitar',\n      'stem_electric_guitar\.wav':'artifacts/stem_electric_guitar', 'stem_piano\.wav':'artifacts/stem_piano',\n      'stem_other\.wav':'artifacts/stem_other', 'lyrics_timeline\.json':'artifacts/lyrics_timeline',\n      'score_data\.json':'artifacts/score_data',\n    \};"
)
assets_replacement = r'''    const assets = <String, String>{
      'original.mp3':'audio',
      'stem_vocals.m4a':'artifacts/stem_vocals_mobile', 'stem_drums.m4a':'artifacts/stem_drums_mobile',
      'stem_bass.m4a':'artifacts/stem_bass_mobile', 'stem_guitar.m4a':'artifacts/stem_guitar_mobile',
      'stem_electric_guitar.m4a':'artifacts/stem_electric_guitar_mobile', 'stem_piano.m4a':'artifacts/stem_piano_mobile',
      'stem_other.m4a':'artifacts/stem_other_mobile', 'lyrics_timeline.json':'artifacts/lyrics_timeline',
      'score_data.json':'artifacts/score_data',
    };'''
text, n = assets_pattern.subn(assets_replacement, text, count=1)
if n != 1:
    raise SystemExit('v3.5.10 offline assets target missing')

# Runtime stem prefetch: prefer lightweight mobile artifact and gracefully fall
# back to the original WAV if the server has not generated that one yet.
stem_pattern = re.compile(
    r"      final url = '\$\{widget\.store\.serverBase\}/api/v1/library/mobile/catalog/\$\{job\.libraryId\}/artifacts/\$\{entry\.value\}';\n      final player = AudioPlayer\(\);\n      try \{\n        final local = await cacheAudio\(\n          url, entry\.value, 'wav',\n          onProgress: \(x\) \{ stemProgress\[entry\.key\] = x; updateStemProgress\(\); \},\n        \);",
    re.S,
)
stem_replacement = r'''      final player = AudioPlayer();
      try {
        String local;
        final mobileUrl = '${widget.store.serverBase}/api/v1/library/mobile/catalog/${job.libraryId}/artifacts/${entry.value}_mobile';
        try {
          local = await cacheAudio(
            mobileUrl, '${entry.value}_mobile', 'm4a',
            onProgress: (x) { stemProgress[entry.key] = x; updateStemProgress(); },
          );
        } catch (_) {
          final wavUrl = '${widget.store.serverBase}/api/v1/library/mobile/catalog/${job.libraryId}/artifacts/${entry.value}';
          local = await cacheAudio(
            wavUrl, entry.value, 'wav',
            onProgress: (x) { stemProgress[entry.key] = x; updateStemProgress(); },
          );
        }'''
text, n = stem_pattern.subn(stem_replacement, text, count=1)
if n != 1:
    raise SystemExit('v3.5.10 parallel stem URL target missing')

text = text.replace("'七轨并行加载 ${(avg * 100).round()}%'", "'七轨高速加载 ${(avg * 100).round()}%'", 1)
text = text.replace("'下载 AI 成品到本地 · 原曲/七轨/歌词/谱面'", "'下载 AI 成品到本地 · 轻量七轨/歌词/谱面'", 1)

if "stem_vocals_mobile" not in text or "七轨高速加载" not in text:
    raise SystemExit('v3.5.11 lightweight stem patch incomplete')
if "appVersion = '3.5.11'" not in text:
    raise SystemExit('v3.5.11 version stamp missing')

path.write_text(text, encoding='utf-8')
print('PATCH_STREAM_V3511_OK')
