import ast
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tools.patch_bs_roformer_tail_chunk import PATCH_MARKER, patch_source
from tools.patch_bs_roformer_low_vram import (
    PATCH_MARKER as LOW_VRAM_MARKER,
    patch_source as patch_low_vram_source,
)


ROOT = Path(__file__).resolve().parents[1]


class Mega53RunnerCompatibilityTests(unittest.TestCase):
    def test_verifier_has_registry_and_architecture_probe(self):
        source = (ROOT / "tools" / "verify_bs_roformer_mega53_runner.py").read_text(
            encoding="utf-8"
        )
        ast.parse(source)
        self.assertIn("MODEL_REGISTRY.get(MODEL_SLUG)", source)
        self.assertIn("inspect.getsource(get_model_from_config)", source)
        self.assertIn("MaskEstimator(", source)
        self.assertIn("mlp_expansion_factor=2", source)
        self.assertIn("probe_shape != [8, 4]", source)
        self.assertIn("b0f1386fcced25f559f3e61c9f08a73cd9bddf80", source)

    def test_installer_pins_source_and_preserves_cuda_dependencies(self):
        installer = (ROOT / "Install-BS-RoFormer-Mega53-v336.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("b0f1386fcced25f559f3e61c9f08a73cd9bddf80", installer)
        self.assertIn("--no-deps", installer)
        self.assertIn("torch.cuda.is_available()", installer)
        self.assertNotIn("mvsep_mega_model_bs_roformer_53_stems_v1.ckpt'", installer)

    def test_server_refuses_unverified_old_runner(self):
        server = (ROOT / "server" / "mobile_api.py").read_text(encoding="utf-8")
        start = (ROOT / "Start-Juweier-Server-v336-Demucs-Mega53-Pilot.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("bs-roformer-mega53-runner", server)
        self.assertIn("mlp_expansion_factor_probe", server)
        self.assertIn("verify_bs_roformer_mega53_runner", start)

    def test_tail_chunk_patch_uses_actual_model_output_length(self):
        upstream = """def f(result, counter, x, window, i, length):
            while i < result.shape[-1]:
                result[..., i:i+length] += x[..., :length] * window[..., :length]
                counter[..., i:i+length] += window[..., :length]
                i += length
"""
        patched = patch_source(upstream)
        self.assertIn(PATCH_MARKER, patched)
        self.assertIn("usable_length = min(", patched)
        self.assertIn("x.shape[-1]", patched)
        self.assertIn("result.shape[-1] - i", patched)
        self.assertNotIn("result[..., i:i+length]", patched)
        namespace = {}
        exec(patched, namespace)
        result = np.zeros((1, 1, 882000), dtype=np.float32)
        counter = np.zeros_like(result)
        model_output = np.ones((1, 1, 881664), dtype=np.float32)
        window = np.ones(882000, dtype=np.float32)
        namespace["f"](result, counter, model_output, window, 0, 882000)
        self.assertTrue(np.all(result[..., :881664] == 1))
        self.assertTrue(np.all(counter[..., :881664] == 1))
        self.assertTrue(np.all(result[..., 881664:] == 0))

    def test_v337_installer_does_not_reinstall_torch_or_models(self):
        installer = (ROOT / "Install-BS-RoFormer-Tail-Fix-v337.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("patch_bs_roformer_tail_chunk", installer)
        self.assertIn("torch.cuda.is_available()", installer)
        self.assertNotIn("pip install", installer)
        self.assertNotIn("curl.exe", installer)

    def test_v338_patch_keeps_full_song_buffers_on_cpu(self):
        upstream = '''def demix(model, mix, device, C, fade_size, config):
    windowing_array = get_windowing_array(C, fade_size, device)
    with autocast:
        with torch.no_grad():
            if config.training.target_instrument is not None:
                req_shape = (1, ) + tuple(mix.shape)
            else:
                req_shape = (len(config.training.instruments),) + tuple(mix.shape)

            mix = mix.to(device)
            result = torch.zeros(req_shape, dtype=torch.float32).to(device)
            counter = torch.zeros(req_shape, dtype=torch.float32).to(device)

            while True:
                part = mix
                x = model(part.unsqueeze(0))[0]
                break
'''
        patched = patch_low_vram_source(upstream)
        self.assertIn(LOW_VRAM_MARKER, patched)
        self.assertIn('device="cpu", dtype=torch.float32', patched)
        self.assertIn('(1, 1, mix.shape[-1])', patched)
        self.assertIn('part_on_device', patched)
        self.assertIn('torch.cuda.empty_cache()', patched)
        self.assertNotIn('result = torch.zeros(req_shape, dtype=torch.float32).to(device)', patched)

    def test_v338_installer_preserves_cuda_and_model_assets(self):
        installer = (ROOT / "Install-BS-RoFormer-Low-VRAM-v338.ps1").read_text(
            encoding="utf-8"
        )
        start = (ROOT / "Start-Juweier-Server-v338-Low-VRAM-Pilot.ps1").read_text(
            encoding="utf-8"
        )
        pilot = (ROOT / "Start-1-Song-Pilot-v338.cmd").read_text(encoding="utf-8")
        self.assertIn("patch_bs_roformer_low_vram", installer)
        self.assertIn("torch.cuda.is_available()", installer)
        self.assertNotIn("pip install", installer)
        self.assertNotIn("curl.exe", installer)
        self.assertIn("JUWEIER_MEGA53_TIMEOUT_SECONDS = '7200'", start)
        self.assertIn("limit=1", pilot)


if __name__ == "__main__":
    unittest.main()
