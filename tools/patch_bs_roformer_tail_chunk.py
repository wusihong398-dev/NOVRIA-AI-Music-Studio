"""Install and verify the Juweier tail-chunk fix for bs-roformer-infer 0.1.6.

The pinned upstream runner assumes the model always returns exactly the input
chunk length.  Mega53 can return a waveform that is a few STFT samples shorter
(for the observed pilot: 881664 instead of 882000).  Cropping all operands to
the actually writable length keeps overlap-add valid and prevents both CUDA
and CPU inference from failing on the first chunk.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import py_compile
import shutil
from pathlib import Path


PATCH_VERSION = "juweier-tail-chunk-v337"
PATCH_MARKER = "# JUWEIER_TAIL_CHUNK_FIX_V337"
OLD_BLOCK = """                result[..., i:i+length] += x[..., :length] * window[..., :length]
                counter[..., i:i+length] += window[..., :length]
"""
NEW_BLOCK = """                # JUWEIER_TAIL_CHUNK_FIX_V337
                # Mega53 may return fewer samples than the requested STFT chunk.
                # Overlap-add only the samples produced by every operand.
                usable_length = min(
                    length,
                    x.shape[-1],
                    window.shape[-1],
                    result.shape[-1] - i,
                )
                if usable_length <= 0:
                    break
                result[..., i:i+usable_length] += (
                    x[..., :usable_length] * window[..., :usable_length]
                )
                counter[..., i:i+usable_length] += window[..., :usable_length]
"""


def patch_source(source: str) -> str:
    if PATCH_MARKER in source:
        return source
    if OLD_BLOCK not in source:
        raise RuntimeError(
            "未找到 bs-roformer-infer 0.1.6 的尾块写回代码；禁止修改未知版本"
        )
    patched = source.replace(OLD_BLOCK, NEW_BLOCK, 1)
    compile(patched, "bs_roformer/utils.py", "exec")
    return patched


def locate_utils() -> Path:
    spec = importlib.util.find_spec("bs_roformer.utils")
    if spec is None or not spec.origin:
        raise RuntimeError("未找到 bs-roformer.utils，请先安装 v3.3.6 兼容运行器")
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
    backup = target.with_suffix(target.suffix + ".juweier-v337.bak")
    if patched != source:
        if not backup.exists():
            shutil.copy2(target, backup)
        target.write_text(patched, encoding="utf-8", newline="\n")
    py_compile.compile(str(target), doraise=True)
    verified_source = target.read_text(encoding="utf-8")
    if PATCH_MARKER not in verified_source:
        raise RuntimeError("尾块修复写入后校验失败")

    model_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "verified": True,
        "patch_version": PATCH_VERSION,
        "runner_file": str(target),
        "runner_sha256": sha256(target),
        "observed_input_samples": 882000,
        "observed_output_samples": 881664,
        "strategy": "crop-overlap-add-to-usable-length",
    }
    marker = model_dir / "bs-roformer-tail-chunk-v337-ready.json"
    marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"marker": str(marker), **payload}


def verify(model_dir: Path) -> dict:
    target = locate_utils()
    source = target.read_text(encoding="utf-8")
    marker = model_dir / "bs-roformer-tail-chunk-v337-ready.json"
    if PATCH_MARKER not in source or not marker.is_file():
        raise RuntimeError("BS-RoFormer 尾块修复尚未安装")
    payload = json.loads(marker.read_text(encoding="utf-8"))
    if (
        payload.get("verified") is not True
        or payload.get("patch_version") != PATCH_VERSION
        or payload.get("runner_sha256") != sha256(target)
    ):
        raise RuntimeError("BS-RoFormer 尾块修复校验失败或运行器随后被改动")
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
