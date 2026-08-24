from pathlib import Path
import re

path = Path('mobile/lib/main.dart')
text = path.read_text(encoding='utf-8')
text = re.sub(r"const appVersion = '3\.5\.[0-9]+';", "const appVersion = '3.5.8';", text, count=1)

# Mixer state: original audio is preview-only; once stems are ready they become
# the sole audible transport, so per-stem switches really mute/unmute tracks.
if "  bool stemMixerActive = false;" not in text:
    text = text.replace(
        "  bool stemsReady = false;",
        "  bool stemsReady = false;\n  bool stemMixerActive = false;",
        1,
    )

text = text.replace(
    "Switch(value: stemEnabled[entry.key] ?? true, onChanged: stemsReady ? (value) => setStemEnabled(entry.key, value) : null)",
    "Switch(value: stemEnabled[entry.key] ?? true, onChanged: stemMixerActive ? (value) => setStemEnabled(entry.key, value) : null)",
    1,
)

# v3.5.7 rewrote loadPlayers. Match the semantic block rather than an exact
# multiline string, so comments/spacing from prior hotfixes cannot break CI.
pattern = re.compile(
    r"    if \(stemPlayers\.isNotEmpty\) \{.*?\n    \} else \{\n      _advanceLoading\(1, '原曲播放中，分轨暂未加载'\);\n    \}",
    re.S,
)
replacement = r'''    if (stemPlayers.isNotEmpty) {
      final old = players.values.first;
      final oldPosition = old.position;
      final wasPlaying = old.playing;

      // Freeze and dispose the original preview before stems take over. Keeping
      // the original underneath the stems makes mute switches appear ineffective.
      try { await old.pause(); } catch (_) {}
      await positionSub?.cancel();
      await durationSub?.cancel();

      // Align every stem to the same master-clock position before playback.
      for (final p in stemPlayers.values) {
        await p.seek(oldPosition);
      }
      for (final p in players.values.toList()) {
        try { await p.dispose(); } catch (_) {}
      }
      players
        ..clear()
        ..addAll(stemPlayers);

      final master = players.values.first;
      positionSub = master.positionStream.listen((value) {
        if (mounted && generation == loadGeneration && !dragging) {
          setState(() => position = value);
        }
      });
      durationSub = master.durationStream.listen((value) {
        if (mounted && generation == loadGeneration && value != null) {
          setState(() => duration = value);
        }
      });

      stemsReady = true;
      stemMixerActive = true;
      _advanceLoading(1, '分轨混音已接管播放');
      if (wasPlaying && generation == loadGeneration) {
        for (final p in players.values) {
          unawaited(p.play());
        }
      }
    } else {
      stemMixerActive = false;
      _advanceLoading(1, '原曲播放中，分轨暂未加载');
    }'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    # Diagnostic fallback: locate the semantic anchor so CI logs are useful.
    if "if (stemPlayers.isNotEmpty)" not in text:
        raise SystemExit('v3.5.7 stem takeover anchor missing')
    raise SystemExit('v3.5.7 stem takeover block shape changed')

# Reset mixer state whenever transport is stopped/reloaded.
text = text.replace(
    "    loadedJobId = '';\n    position = Duration.zero;",
    "    loadedJobId = '';\n    stemsReady = false;\n    stemMixerActive = false;\n    position = Duration.zero;",
    1,
)

# Volume sliders and switches only control real stem players after takeover.
text = text.replace(
    "subtitle: Slider(value: entry.value, onChanged: (value) { setState(() => levels[entry.key] = value); players[entry.key]?.setVolume(value * masterVolume); }),",
    "subtitle: Slider(value: entry.value, onChanged: !stemMixerActive || !(stemEnabled[entry.key] ?? true) ? null : (value) { setState(() => levels[entry.key] = value); players[entry.key]?.setVolume(value * masterVolume); }),",
    1,
)

# Declutter per-note lyrics while retaining the current-line karaoke band.
text = text.replace(
    "      final noteLyric = '${note['lyric'] ?? ''}';\n      if (noteLyric.isNotEmpty) {",
    "      final noteLyric = '${note['lyric'] ?? ''}';\n      if (noteLyric.isNotEmpty && (i % 2 == 0 || visible.length <= 12)) {",
    1,
)

if "final lyricBand = Paint()" not in text:
    text = text.replace(
        "    if (lineUnits.isNotEmpty) {",
        "    if (lineUnits.isNotEmpty) {\n      final lyricBand = Paint()..color = const Color(0x22111111);\n      canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTWH(10, size.height - 58, size.width - 20, 50), const Radius.circular(10)), lyricBand);",
        1,
    )

if 'stemMixerActive = true' not in text:
    raise SystemExit('stem mixer takeover missing')
if 'i % 2 == 0' not in text:
    raise SystemExit('lyric declutter missing')
if "appVersion = '3.5.8'" not in text:
    raise SystemExit('version stamp missing')

path.write_text(text, encoding='utf-8')
print('PATCH_PLAYBACK_V358_OK')
