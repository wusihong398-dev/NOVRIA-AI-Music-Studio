from pathlib import Path
import re

path = Path('mobile/lib/main.dart')
text = path.read_text(encoding='utf-8')
text = re.sub(r"const appVersion = '3\.5\.[0-9]+';", "const appVersion = '3.5.6';", text, count=1)

# Add one monotonic progress updater. Any late or out-of-order callback may
# update the status text, but it can never move the visible percentage back.
needle = "  double loadingProgress = 0;\n  String loadingText = '';\n  bool stemsReady = false;\n"
replacement = "  double loadingProgress = 0;\n  String loadingText = '';\n  bool stemsReady = false;\n\n  void _advanceLoading(double value, [String? text]) {\n    final next = value.clamp(0.0, 1.0).toDouble();\n    if (next > loadingProgress) loadingProgress = next;\n    if (text != null && text.isNotEmpty) loadingText = text;\n    if (mounted) setState(() {});\n  }\n"
if needle not in text:
    raise SystemExit('v3.5.5 loading state target not found')
text = text.replace(needle, replacement, 1)

# Replace direct progress mutations produced by the v3.5.5 patch with the
# monotonic updater. This fixes Android/iOS bars jumping backwards.
text = text.replace("    loadingProgress = .02;\n    loadingText = '正在连接歌曲服务器…';\n    if (mounted) setState(() {});", "    _advanceLoading(.02, '正在连接歌曲服务器…');", 1)
text = text.replace("        loadingText = '正在加载原曲…';\n        if (mounted) setState(() {});", "        _advanceLoading(loadingProgress, '正在加载原曲…');", 1)
text = text.replace("onProgress: (p) { loadingProgress = .05 + p * .35; if (mounted) setState(() {}); }", "onProgress: (p) => _advanceLoading(.05 + p * .35, '正在加载原曲…')", 1)
text = text.replace("        loadingProgress = .4;\n        loadingText = '原曲已就绪，后台加载分轨…';\n        if (mounted) setState(() {});", "        _advanceLoading(.4, '原曲已就绪，后台加载分轨…');", 1)
text = text.replace("        loadingText = '原曲加载失败：$error';\n        if (mounted) setState(() {});", "        _advanceLoading(loadingProgress, '原曲加载失败：$error');", 1)
text = text.replace("        loadingText = '正在加载${entry.key}分轨 ${done + 1}/7';\n        if (mounted) setState(() {});", "        _advanceLoading(loadingProgress, '正在加载${entry.key}分轨 ${done + 1}/7');", 1)
text = text.replace("onProgress: (x) { loadingProgress = .4 + ((done + x) / 7) * .6; if (mounted) setState(() {}); }", "onProgress: (x) => _advanceLoading(.4 + ((done + x) / 7) * .6, '正在加载${entry.key}分轨 ${done + 1}/7')", 1)
text = text.replace("      stemsReady = true; loadingProgress = 1; loadingText = '七轨混音已就绪';", "      stemsReady = true; _advanceLoading(1, '七轨混音已就绪');", 1)

# Give notation and lyrics their own vertical regions. Increase preview height
# and move per-note lyric text farther below the last staff/tab line.
text = text.replace("        height: 230,", "        height: 270,", 1)
text = text.replace("text.paint(canvas, Offset(x - text.width / 2, top + lineCount * gap + 5));", "text.paint(canvas, Offset(x - text.width / 2, top + lineCount * gap + 24));", 1)
text = text.replace("text.paint(canvas, Offset((size.width - text.width) / 2, size.height - text.height - 8));", "text.paint(canvas, Offset((size.width - text.width) / 2, size.height - text.height - 12));", 1)

path.write_text(text, encoding='utf-8')
print('PATCH_PLAYBACK_V356_OK')
