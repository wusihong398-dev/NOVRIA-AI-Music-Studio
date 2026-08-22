"""Install and verify the RTX 3060 low-VRAM patch for bs-roformer-infer.

The upstream runner keeps the complete 53-stem overlap-add buffers on CUDA.
For a normal song those buffers consume several gigabytes and eventually push
the 12 GB RTX 3060 out of memory.  This patch keeps only the active inference
chunk on CUDA and accumulates completed chunks in system RAM.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import py_compile
import shutil
from pathlib import Path


PATCH_VERSION = "juweier-low-vram-v338"
PATCH_MARKER = "# JUWEIER_LOW_VRAM_FIX_V338"
MARKER_NAME = "bs-roformer-low-vram-v338-ready.json"

OLD_WINDOW = "    windowing_array = get_windowing_array(C, fade_size, device)\n"
NEW_WINDOW = """    # JUWEIER_LOW_VRAM_FIX_V338
    # Keep overlap-add weights off the GPU; only one model chunk uses VRAM.
    windowing_array = get_windowing_array(C, fade_size, "cpu")
"""

OLD_ALLOCATIONS = """            mix = mix.to(device)
            result = torch.zeros(req_shape, dtype=torch.float32).to(device)
            counter = torch.zeros(req_shape, dtype=torch.float32).to(device)
"""
NEW_ALLOCATIONS = """            # Full-song 53-stem buffers can exceed 12 GB on CUDA.
            # Accumulate on CPU and use one broadcast counter for every stem.
            mix = mix.to(device="cpu", dtype=torch.float32)
            result = torch.zeros(req_shape, dtype=torch.float32, device="cpu")
            counter = torch.zeros(
                (1, 1, mix.shape[-1]), dtype=torch.float32, device="cpu"
            )
"""

OLD_INFERENCE = "                x = model(part.unsqueeze(0))[0]\n"
NEW_INFERENCE = """                part_on_device = part.unsqueeze(0).to(
                    device, non_blocking=True
                )
                x_on_device = model(part_on_device)[0]
                x = x_on_device.to(device="cpu", dtype=torch.float32)
                del x_on_device, part_on_device
                if torch.device(device).type == "cuda":
                    torch.cuda.empty_cache()
"""


def patch_source(source: str) -> str:
    if PATCH_MARKER in source:
        return source
    replacements = (
        (OLD_WINDOW, NEW_WINDOW, "窗口数组"),
        (OLD_ALLOCATIONS, NEW_ALLOCATIONS, "完整歌曲累加缓冲区"),
        (OLD_INFERENCE, NEW_INFERENCE, "逐块模型推理"),
    )
    patched = source
    for old, new, label in replacements:
        if old not in patched:
            raise RuntimeError(
                f"未找到 bs-roformer-infer 0.1.6 的{label}代码；禁止修改未知版本"
            )
        patched = patched.replace(old, new, 1)
    compile(patched, "bs_roformer/utils.py", "exec")
    return patched


def locate_utils() -> Path:
    spec = importlib.util.find_spec("bs_roformer.utils")
    if spec is None or not spec.origin:
        raise RuntimeError("未找到 bs_roformer.utils，请先安装 v3.3.6 兼容运行器")
    return Path(spec.origin).resolve()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def install(model_dir: Path) -> dict:
    target = locate_utils()
    source = target.read_text(encoding="utf-8")
    patched = patch_source(source)
    backup = target.with_suffix(target.suffix + ".juweier-v338.bak")
    if patched != source:
        if not backup.exists():
            shutil.copy2(target, backup)
        target.write_text(patched, encoding="utf-8", newline="\n")
    py_compile.compile(str(target), doraise=True)
    if PATCH_MARKER not in target.read_text(encoding="utf-8"):
        raise RuntimeError("RTX 3060 低显存修复写入后校验失败")

    model_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "verified": True,
        "patch_version": PATCH_VERSION,
        "runner_file": str(target),
        "runner_sha256": sha256(target),
        "gpu_resident": "model-and-active-chunk-only",
        "accumulator_device": "cpu",
        "counter_shape": "broadcast-single-track",
        "cpu_fallback": False,
    }
    marker = model_dir / MARKER_NAME
    marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # The v3.3.7 tail marker also pins the runner hash.  Both patches coexist in
    # the same source file, so refresh that hash after adding the v3.3.8 patch.
    tail_marker = model_dir / "bs-roformer-tail-chunk-v337-ready.json"
    if tail_marker.is_file():
        tail_payload = json.loads(tail_marker.read_text(encoding="utf-8"))
        if tail_payload.get("patch_version") != "juweier-tail-chunk-v337":
            raise RuntimeError("v3.3.7 尾块修复标记不兼容，禁止覆盖")
        tail_payload["runner_sha256"] = payload["runner_sha256"]
        tail_payload["compatible_low_vram_patch"] = PATCH_VERSION
        tail_marker.write_text(
            json.dumps(tail_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return {"marker": str(marker), **payload}


def verify(model_dir: Path) -> dict:
    target = locate_utils()
    source = target.read_text(encoding="utf-8")
    marker = model_dir / MARKER_NAME
    if PATCH_MARKER not in source or not marker.is_file():
        raise RuntimeError("RTX 3060 低显存修复尚未安装")
    payload = json.loads(marker.read_text(encoding="utf-8"))
    if (
        payload.get("verified") is not True
        or payload.get("patch_version") != PATCH_VERSION
        or payload.get("runner_sha256") != sha256(target)
        or payload.get("cpu_fallback") is not False
    ):
        raise RuntimeError("RTX 3060 低显存修复校验失败或运行器随后被改动")
    return {"marker": str(marker), **payload}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    result = verify(args.model_dir) if args.verify_only else install(args.model_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
