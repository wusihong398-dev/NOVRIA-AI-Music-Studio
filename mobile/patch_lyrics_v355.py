from pathlib import Path

path = Path('mobile/lib/main.dart')
text = path.read_text(encoding='utf-8')

text = text.replace("  String loadingText = '';\n  bool stemsReady = false;", "  String loadingText = '';\n  String lyricsCorrection = '';\n  bool stemsReady = false;", 1)
text = text.replace(
    "    final token = widget.store.accountToken.isNotEmpty ? widget.store.accountToken : widget.store.apiToken;\n    final cacheRoot = Directory(",
    "    final token = widget.store.accountToken.isNotEmpty ? widget.store.accountToken : widget.store.apiToken;\n    final lyricPrefs = await SharedPreferences.getInstance();\n    lyricsCorrection = lyricPrefs.getString('juweier_lyrics_fix_${job.libraryId}') ?? '';\n    final cacheRoot = Directory(",
    1,
)
text = text.replace(
    "ScorePreview(url: job.artifacts['score_data']!, token: widget.store.accountToken.isNotEmpty ? widget.store.accountToken : widget.store.apiToken, tablature: scoreType == '六线谱' || scoreType == '木吉他谱' || scoreType == '电吉他谱', positionSeconds: position.inMilliseconds / 1000)",
    "ScorePreview(url: job.artifacts['score_data']!, token: widget.store.accountToken.isNotEmpty ? widget.store.accountToken : widget.store.apiToken, tablature: scoreType == '六线谱' || scoreType == '木吉他谱' || scoreType == '电吉他谱', positionSeconds: position.inMilliseconds / 1000, lyricsOverride: lyricsCorrection)",
    1,
)
text = text.replace(
    "const ScorePreview({super.key, required this.url, required this.token, required this.tablature, required this.positionSeconds});",
    "const ScorePreview({super.key, required this.url, required this.token, required this.tablature, required this.positionSeconds, required this.lyricsOverride});",
    1,
)
text = text.replace("  final double positionSeconds;\n", "  final double positionSeconds;\n  final String lyricsOverride;\n", 1)
text = text.replace(
    "if (oldWidget.url != widget.url || oldWidget.tablature != widget.tablature) unawaited(load());",
    "if (oldWidget.url != widget.url || oldWidget.tablature != widget.tablature || oldWidget.lyricsOverride != widget.lyricsOverride) unawaited(load());",
    1,
)
old = "          lyrics = lyricRows is List ? lyricRows.map((e) => Map<String, dynamic>.from(e as Map)).toList() : const [];"
new = "          final baseLyrics = lyricRows is List ? lyricRows.map((e) => Map<String, dynamic>.from(e as Map)).toList() : <Map<String, dynamic>>[];\n          final corrected = widget.lyricsOverride.split('\\n').map((e) => e.trim()).where((e) => e.isNotEmpty).toList();\n          if (corrected.isNotEmpty) { for (var i = 0; i < baseLyrics.length && i < corrected.length; i++) { baseLyrics[i]['text'] = corrected[i]; } }\n          lyrics = baseLyrics;"
text = text.replace(old, new, 1)
text = text.replace(
    "await prefs.setString(key, value); if (mounted) ScaffoldMessenger.of(context).showSnackBar",
    "await prefs.setString(key, value); if (mounted) setState(() => lyricsCorrection = value); if (mounted) ScaffoldMessenger.of(context).showSnackBar",
    1,
)

path.write_text(text, encoding='utf-8')
print('PATCH_LYRICS_V355_OK')
