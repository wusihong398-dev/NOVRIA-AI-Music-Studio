# Juweier Music v3.2.0

## Complete upgrade

- Fixed recursive G-drive scanning and added visible diagnostics for roots, folders, complete audio files, partial downloads, and read errors.
- The library now follows the on-disk `artist/song` folders and shows expandable artist groups, an explicit Search button, and Clear.
- Added local-file import and public share-link import into `05_Temp/link imports`. Login, membership, paid, or DRM restrictions are never bypassed.
- The base AI model remains `htdemucs_6s`. A second spectral stage splits its combined guitar output into aligned `guitar.wav` and `electric_guitar.wav`, while preserving `guitar_combined.wav`.
- Added electric guitar to the performer center, mixer, Mute/Solo, export, server artifacts, Android, and iOS.
- Added automatically generated staff notation, guitar tablature, adjacent/embedded lyric reading, and playback-synchronized highlighting on desktop and mobile.
- Kept synchronized seeking across every loaded stem. Desktop playback speed now affects every stem; transpose renders synchronized new stems; score/metronome delay calibrates wireless devices.
- Retained the full live-performance workflow: transpose, speed, delay, sections, metronome, count-in, per-track level, Mute/Solo, auto page following, Setlist, and export.

Default library root: `G:\JuweierMusicLibrary`.

Mobile clients still use the Windows/GPU server for separation, analysis, scores, and arrangement. Demucs does not run on the phone.
