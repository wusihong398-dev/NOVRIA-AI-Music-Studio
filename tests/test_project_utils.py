import json
import tempfile
import unittest
import wave
from pathlib import Path

from app.project_utils import (
    align_lyric_units_to_notes,
    atomic_write_json,
    expand_lyric_units,
    normalized_path,
    repair_text,
    safe_file_stem,
    unique_import_candidates,
    load_synced_lyrics,
)

try:
    import numpy as np
    import soundfile as sf
    from app.project_utils import split_guitar_stem
    HAS_AUDIO_STACK = True
except ImportError:
    HAS_AUDIO_STACK = False


class ProjectUtilsTests(unittest.TestCase):
    def test_lyrics_expand_per_character_and_align_to_notes(self):
        units = expand_lyric_units([{"start": 0, "end": 2, "text": "你好吗"}])
        self.assertEqual([item["text"] for item in units], ["你", "好", "吗"])
        notes = [
            {"start": 0.0, "duration": .5, "midi": 60},
            {"start": .7, "duration": .5, "midi": 62},
            {"start": 1.4, "duration": .5, "midi": 64},
        ]
        aligned = align_lyric_units_to_notes(notes, units)
        self.assertEqual([item.get("lyric") for item in aligned], ["你", "好", "吗"])

    def test_safe_file_stem_preserves_chinese_and_removes_windows_chars(self):
        self.assertEqual(safe_file_stem('橘味儿:测试?.mp3'), '橘味儿_测试_.mp3')

    def test_repair_text_repairs_utf8_mojibake(self):
        broken = '橘味儿音乐'.encode('utf-8').decode('latin-1')
        self.assertEqual(repair_text(broken), '橘味儿音乐')

    def test_atomic_write_json_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            atomic_write_json(path, {'歌曲': '测试', '进度': 100})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['歌曲'], '测试')
            self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_source_and_working_file_are_one_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / '歌曲.mp3'
            working = root / '歌曲_123_work.wav'
            source.write_bytes(b'source')
            working.write_bytes(b'working')
            database = {
                'source-fingerprint': {
                    'source': str(source),
                    'working': str(working),
                    'imported_at': 1,
                }
            }
            rows = unique_import_candidates(database, [working], lambda _: 'working-fingerprint')
            self.assertEqual(len(rows), 1)
            self.assertEqual(normalized_path(rows[0][2]), normalized_path(working))

    def test_lrc_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "song.wav"
            with wave.open(str(audio), "wb") as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(8000)
                stream.writeframes(b"\0\0" * 8000)
            audio.with_suffix(".lrc").write_text("[00:01.00]第一句\n[00:03.50]第二句", encoding="utf-8")
            rows = load_synced_lyrics(audio, 6)
            self.assertEqual(rows[0]["text"], "第一句")
            self.assertEqual(rows[0]["start"], 1.0)
            self.assertEqual(rows[0]["end"], 3.5)

    @unittest.skipUnless(HAS_AUDIO_STACK, "soundfile/librosa audio test dependencies are not installed")
    def test_guitar_second_stage_creates_distinct_aligned_tracks(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            sample_rate = 8000
            t = np.arange(sample_rate, dtype=np.float32) / sample_rate
            signal = (0.2 * np.sin(2 * np.pi * 220 * t) + 0.08 * np.sin(2 * np.pi * 1800 * t)).astype(np.float32)
            sf.write(folder / "guitar.wav", np.column_stack((signal, signal)), sample_rate)
            info = split_guitar_stem(folder)
            acoustic, _ = sf.read(folder / "guitar.wav", always_2d=True)
            electric, _ = sf.read(folder / "electric_guitar.wav", always_2d=True)
            combined, _ = sf.read(folder / "guitar_combined.wav", always_2d=True)
            self.assertEqual(acoustic.shape, combined.shape)
            self.assertEqual(electric.shape, combined.shape)
            self.assertGreater(float(np.max(np.abs(electric))), 0.001)
            self.assertLess(float(np.max(np.abs((acoustic + electric) - combined))), 0.01)
            self.assertEqual(info["base_model"], "htdemucs_6s")

    @unittest.skipUnless(HAS_AUDIO_STACK, "soundfile/librosa audio test dependencies are not installed")
    def test_guitar_retry_replaces_corrupt_combined_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            sample_rate = 8000
            signal = np.zeros((sample_rate, 2), dtype=np.float32)
            signal[:, 0] = 0.1
            signal[:, 1] = -0.1
            sf.write(folder / "guitar.wav", signal, sample_rate)
            (folder / "guitar_combined.wav").write_bytes(b"partial failed output")

            split_guitar_stem(folder)

            repaired, repaired_rate = sf.read(
                folder / "guitar_combined.wav", always_2d=True,
            )
            self.assertEqual(repaired_rate, sample_rate)
            self.assertEqual(repaired.shape, signal.shape)
            self.assertFalse((folder / "guitar_combined.part.wav").exists())


if __name__ == '__main__':
    unittest.main()
