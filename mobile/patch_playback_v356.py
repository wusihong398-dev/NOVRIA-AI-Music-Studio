from pathlib import Path
import re

path = Path('mobile/lib/main.dart')
text = path.read_text(encoding='utf-8')
text = re.sub(r"const appVersion = '3\.5\.[0-9]+';", "const appVersion = '3.5.6';", text, count=1)

# Add one monotonic progress updater after the v3.5.5 loading-state fields.
# Use a regex instead of an exact multiline string so earlier hotfix formatting
# cannot make this patch fail on Android/iOS CI.
state_pattern = re.compile(
    r"(\s*double\s+loadingProgress\s*=\s*0\s*;\s*\n\s*String\s+loadingText\s*=\s*''\s*;\s*\n\s*bool\s+stemsReady\s*=\s*false\s*;)",
    re.M,
)
state_replacement = r'''\1

  void _advanceLoading(double value, [String? text]) {
    final next = value.clamp(0.0, 1.0).toDouble();
    if (next > loadingProgress) loadingProgress = next;
    if (text != null && text.isNotEmpty) loadingText = text;
    if (mounted) setState(() {});
  }'''
text, count = state_pattern.subn(state_replacement, text, count=1)
if count != 1:
    raise SystemExit('v3.5.5 loading state target not found')

# Replace direct progress mutations produced by the v3.5.5 patch with the
# monotonic updater. Late/out-of-order download callbacks can no longer move
# the visible progress backwards.
replacements = [
    ("    loadingProgress = .02;\n    loadingText = '正在连接歌曲服务器…';\n    if (mounted) setState(() {});", "    _advanceLoading(.02, '正在连接歌曲服务器…');"),
    ("        loadingText = '正在加载原曲…';\n        if (mounted) setState(() {});", "        _advanceLoading(loadingProgress, '正在加载原曲…');"),
    ("onProgress: (p) { loadingProgress = .05 + p * .35; if (mounted) setState(() {}); }", "onProgress: (p) => _advanceLoading(.05 + p * .35, '正在加载原曲…')"),
    ("        loadingProgress = .4;\n        loadingText = '原曲已就绪，后台加载分轨…';\n        if (mounted) setState(() {});", "        _advanceLoading(.4, '原曲已就绪，后台加载分轨…');"),
    ("        loadingText = '原曲加载失败：$error';\n        if (mounted) setState(() {});", "        _advanceLoading(loadingProgress, '原曲加载失败：$error');"),
    ("        loadingText = '正在加载${entry.key}分轨 ${done + 1}/7';\n        if (mounted) setState(() {});", "        _advanceLoading(loadingProgress, '正在加载${entry.key}分轨 ${done + 1}/7');"),
    ("onProgress: (x) { loadingProgress = .4 + ((done + x) / 7) * .6; if (mounted) setState(() {}); }", "onProgress: (x) => _advanceLoading(.4 + ((done + x) / 7) * .6, '正在加载${entry.key}分轨 ${done + 1}/7')"),
    ("      stemsReady = true; loadingProgress = 1; loadingText = '七轨混音已就绪';", "      stemsReady = true; _advanceLoading(1, '七轨混音已就绪');"),
]
for old, new in replacements:
    text = text.replace(old, new, 1)

# Score/lyrics spacing: give notation and lyrics separate vertical regions.
text = text.replace("        height: 230,", "        height: 270,", 1)
text = text.replace("text.paint(canvas, Offset(x - text.width / 2, top + lineCount * gap + 5));", "text.paint(canvas, Offset(x - text.width / 2, top + lineCount * gap + 24));", 1)
text = text.replace("text.paint(canvas, Offset((size.width - text.width) / 2, size.height - text.height - 8));", "text.paint(canvas, Offset((size.width - text.width) / 2, size.height - text.height - 12));", 1)

# CI sanity checks: fail here if the actual intended fixes are not present.
if "void _advanceLoading(double value" not in text:
    raise SystemExit('monotonic progress updater missing')
if "height: 270" not in text:
    raise SystemExit('score height spacing fix missing')

path.write_text(text, encoding='utf-8')
print('PATCH_PLAYBACK_V356_OK')
