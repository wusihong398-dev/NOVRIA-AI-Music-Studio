import json
import tempfile
import unittest
from pathlib import Path

from app.uvr_separator import (
    DEFAULT_UVR_MODEL,
    DEMUCS_MODEL_FILE,
    _clear_stale_outputs,
    _seed_offline_uvr_catalog,
)


class UvrSeparatorTests(unittest.TestCase):
    def test_offline_catalog_contains_local_six_stem_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            model_dir = Path(folder)
            _seed_offline_uvr_catalog(model_dir)

            self.assertEqual(
                (model_dir / DEFAULT_UVR_MODEL).read_text(encoding="utf-8"),
                "models: ['5c90dfd2']\n",
            )
            checks = json.loads(
                (model_dir / "download_checks.json").read_text(encoding="utf-8")
            )
            files = checks["demucs_download_list"]["Demucs v4: htdemucs_6s"]
            self.assertIn(DEMUCS_MODEL_FILE, files)
            self.assertIn(DEFAULT_UVR_MODEL, files)

    def test_retry_cleanup_removes_partial_and_corrupt_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            stem_dir = Path(folder)
            for name in (
                "vocals.wav",
                "guitar.wav",
                "guitar.part.wav",
                "guitar_combined.wav",
                "guitar_combined.part.wav",
                "guitar_second_stage.json",
            ):
                (stem_dir / name).write_bytes(b"partial")

            _clear_stale_outputs(stem_dir)

            self.assertEqual(list(stem_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
