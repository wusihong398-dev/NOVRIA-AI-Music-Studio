from pathlib import Path
import re

path = Path('mobile/lib/main.dart')
text = path.read_text(encoding='utf-8')
text = re.sub(r"const appVersion = '3\.5\.[0-9]+';", "const appVersion = '3.5.8';", text, count=1)

# v3.5.8: strict stem takeover. Original audio is preview only; once all available
# stems are prepared, dispose preview and let stem players become the only audible source.
text = text.replace(
    "  bool stemsReady = false;",
    "  bool stemsReady = false;\n  bool stemMixerActive = false;",
    1,
)

# Ensure switches cannot appear active before the stem mixer has taken over.
text = text.replace(
    "Switch(value: stemEnabled[entry.key] ?? true, onChanged: stemsReady ? (value) => setStemEnabled(entry.key, value) : null)",
    "Switch(value: stemEnabled[entry.key] ?? true, onChanged: stemMixerActive ? (value) => setStemEnabled(entry.key, value) : null)",
    1,
)

# Replace the background stem completion block to require a coordinated takeover.
old = '''      if (stemPlayers.isEmpty || loadedJobId != job.id) return;
      final old = players.values.first;
      final oldPosition = old.position;
      final wasPlaying = old.playing;
      await positionSub?.cancel(); await durationSub?.cancel();
      for (final p in players.values) { await p.pause(); await p.dispose(); }
      players..clear()..addAll(stemPlayers);
      for (final p in players.values) { await p.seek(oldPosition); }
      final master = players.values.first;
      positionSub = master.positionStream.listen((value) { if (mounted && !dragging) setState(() => position = value); });
      durationSub = master.durationStream.listen((value) { if (mounted && value != null) setState(() => duration = value); });
      stemsReady = true; _advanceLoading(1, '七轨混音已就绪');
      if (wasPlaying) for (final p in players.values) { unawaited(p.play()); }
      if (mounted) setState(() {});'''
new = '''      if (stemPlayers.isEmpty || loadedJobId != job.id) {
        for (final p in stemPlayers.values) { await p.dispose(); }
        return;
      }
      final old = players.values.first;
      final oldPosition = old.position;
      final wasPlaying = old.playing;
      // Freeze preview before the synchronized stem seek.  Preview is never kept
      // underneath the stem mixer, otherwise mute/solo controls cannot be audible.
      await old.pause();
      await positionSub?.cancel();
      await durationSub?.cancel();
      for (final p in stemPlayers.values) { await p.seek(oldPosition); }
      for (final p in players.values) { await p.dispose(); }
      players..clear()..addAll(stemPlayers);
      final master = players.values.first;
      positionSub = master.positionStream.listen((value) { if (mounted && !dragging) setState(() => position = value); });
      durationSub = master.durationStream.listen((value) { if (mounted && value != null) setState(() => duration = value); });
      stemsReady = true;
      stemMixerActive = true;
      _advanceLoading(1, '分轨混音已接管播放');
      if (wasPlaying) {
        for (final p in players.values) { unawaited(p.play()); }
      }
      if (mounted) setState(() {});'''
if old not in text:
    raise SystemExit('stem takeover target not found')
text = text.replace(old, new, 1)

# Stop/reset must clear stem mixer state too.
text = text.replace(
    "    loadedJobId = '';\n    position = Duration.zero;",
    "    loadedJobId = '';\n    stemsReady = false;\n    stemMixerActive = false;\n    position = Duration.zero;",
    1,
)

# Make mute controls explicitly show state and disable volume slider for muted stems.
text = text.replace(
    "subtitle: Slider(value: entry.value, onChanged: (value) { setState(() => levels[entry.key] = value); players[entry.key]?.setVolume(value * masterVolume); }),",
    "subtitle: Slider(value: entry.value, onChanged: !stemMixerActive || !(stemEnabled[entry.key] ?? true) ? null : (value) { setState(() => levels[entry.key] = value); players[entry.key]?.setVolume(value * masterVolume); }),",
    1,
)

# Reduce per-note lyric clutter: only draw a note lyric when sufficiently spaced.
text = text.replace(
    "      final noteLyric = '${note['lyric'] ?? ''}';\n      if (noteLyric.isNotEmpty) {",
    "      final noteLyric = '${note['lyric'] ?? ''}';\n      if (noteLyric.isNotEmpty && (i % 2 == 0 || visible.length <= 12)) {",
    1,
)

# Add a separated current-lyric band label for readability.
text = text.replace(
    "    if (lineUnits.isNotEmpty) {",
    "    if (lineUnits.isNotEmpty) {\n      final lyricBand = Paint()..color = const Color(0x22111111);\n      canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTWH(10, size.height - 58, size.width - 20, 50), const Radius.circular(10)), lyricBand);",
    1,
)

if 'stemMixerActive = true' not in text:
    raise SystemExit('stem mixer takeover missing')
if 'i % 2 == 0' not in text:
    raise SystemExit('lyric declutter missing')

path.write_text(text, encoding='utf-8')
print('PATCH_PLAYBACK_V358_OK')
