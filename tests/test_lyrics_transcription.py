import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.lyrics_transcription import transcribe_synced_lyrics


class LyricsTranscriptionTests(unittest.TestCase):
    def test_prefers_existing_lrc_without_loading_asr(self):
        with tempfile.TemporaryDirectory() as raw:
            audio = Path(raw) / "song.mp3"
            audio.write_bytes(b"test")
            audio.with_suffix(".lrc").write_text(
                "[00:01.00]第一句\n[00:03.50]Second line", encoding="utf-8",
            )
            result = transcribe_synced_lyrics(audio, 6)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["source"], "lrc_or_embedded")
        self.assertEqual([row["text"] for row in result["rows"]], ["第一句", "Second line"])

    def test_disabled_asr_returns_explicit_status(self):
        with tempfile.TemporaryDirectory() as raw, patch.dict(
            os.environ, {"JUWEIER_LYRICS_ASR_ENABLED": "0"}, clear=False,
        ):
            audio = Path(raw) / "song.mp3"
            audio.write_bytes(b"test")
            result = transcribe_synced_lyrics(audio, 6)
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(result["rows"], [])


if __name__ == "__main__":
    unittest.main()
