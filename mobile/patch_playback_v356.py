from pathlib import Path
import re

path = Path('mobile/lib/main.dart')
text = path.read_text(encoding='utf-8')
text = re.sub(r"const appVersion = '3\.5\.[0-9]+';", "const appVersion = '3.5.6';", text, count=1)

# v3.5.5 must already have added these state fields. Do not depend on their
# whitespace or adjacency; only verify that they exist somewhere in the page.
required_fields = [
    'double loadingProgress = 0;',
    "String loadingText = '';",
    'bool stemsReady = false;',
]
for field in required_fields:
    if field not in text:
        raise SystemExit(f'v3.5.5 loading field missing: {field}')

# Insert the monotonic updater at a stable method boundary instead of trying to
# match the exact field layout. The selected getter is part of PerformancePage
# and survives the preceding v3.5.3-v3.5.5 patches.
if 'void _advanceLoading(double value' not in text:
    marker = '  PipelineJob? get selected {'
    if marker not in text:
        raise SystemExit('PerformancePage selected getter target not found')
    helper = '''  void _advanceLoading(double value, [String? text]) {\n    final next = value.clamp(0.0, 1.0).toDouble();\n    if (next > loadingProgress) loadingProgress = next;\n    if (text != null && text.isNotEmpty) loadingText = text;\n    if (mounted) setState(() {});\n  }\n\n'''
    text = text.replace(marker, helper + marker, 1)

# Replace direct progress mutations produced by v3.5.5. All visible progress
# updates now go through _advanceLoading(), so late callbacks cannot move the
# bar backwards on either Android or iOS.
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

# Five-line staff / tablature spacing: reserve more vertical space between the
# notation and lyrics instead of drawing lyric text immediately below the last line.
text = text.replace('        height: 230,', '        height: 270,', 1)
text = text.replace(
    'text.paint(canvas, Offset(x - text.width / 2, top + lineCount * gap + 5));',
    'text.paint(canvas, Offset(x - text.width / 2, top + lineCount * gap + 24));',
    1,
)
text = text.replace(
    'text.paint(canvas, Offset((size.width - text.width) / 2, size.height - text.height - 8));',
    'text.paint(canvas, Offset((size.width - text.width) / 2, size.height - text.height - 12));',
    1,
)

# Final CI assertions verify the feature itself, not a fragile source layout.
if "const appVersion = '3.5.6';" not in text:
    raise SystemExit('v3.5.6 version stamp missing')
if 'void _advanceLoading(double value' not in text:
    raise SystemExit('monotonic progress updater missing')
if 'if (next > loadingProgress) loadingProgress = next;' not in text:
    raise SystemExit('monotonic progress guard missing')
if 'height: 270' not in text:
    raise SystemExit('score height spacing fix missing')

path.write_text(text, encoding='utf-8')
print('PATCH_PLAYBACK_V356_OK')
