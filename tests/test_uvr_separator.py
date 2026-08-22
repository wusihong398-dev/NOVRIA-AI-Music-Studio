import json
import tempfile
import unittest
from pathlib import Path

from app.uvr_separator import (
    DEFAULT_UVR_MODEL,
    DEMUCS_MODEL_FILE,
    _clear_stale_outputs,
    _seed_offline_uvr_catalog,
    _run_electric_guitar_uvr,
)


class UvrSeparatorTests(unittest.TestCase):
    def test_mega53_uses_explicit_verified_assets_not_old_registry_slug(self):
        source = (Path(__file__).resolve().parents[1] / "app" / "uvr_separator.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"--model_path", str(checkpoint)', source)
        self.assertIn('"--config_path", str(config)', source)
        self.assertNotIn('"--model", model_slug', source)
        self.assertIn('"--output_format", "wav_float32"', source)
        self.assertIn('bs-roformer-mega53-runner-ready.json', source)
        self.assertIn('bs-roformer-tail-chunk-v337-ready.json', source)
        self.assertIn('bs-roformer-low-vram-v338-ready.json', source)
        self.assertNotIn('devices.append("cpu")', source)
        self.assertIn('已禁止 CPU 回退', source)

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

    def test_real_electric_guitar_model_is_mandatory(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, "真实电吉他二阶段模型"):
                _run_electric_guitar_uvr(
                    Path(folder), Path(folder) / "models", "cpu",
                    "audio-separator/UVR", DEFAULT_UVR_MODEL,
                    lambda _value, _text: None,
                )


if __name__ == "__main__":
    unittest.main()
