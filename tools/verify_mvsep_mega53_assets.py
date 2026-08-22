"""Verify the official MVSep Mega 53-Stems checkpoint before server use."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


MODEL_SLUG = "roformer-model-bs-roformer-mvsep-mega-53-stems"
CHECKPOINT_NAME = "mvsep_mega_model_bs_roformer_53_stems_v1.ckpt"
CHECKPOINT_SIZE = 1_368_919_887
CHECKPOINT_SHA256 = "c62820893bbf86d4e734f966bd142d9157cfc8bb8e79e9d8f9ea553f3ff3519f"
CONFIG_NAME = "mvsep_mega_model_bs_roformer_53_stems.yaml"
CONFIG_SIZE = 4_184
CONFIG_SHA256 = "7e198062a251587088adb91215a4f44ab59e67bd62fcc805cf54d6e7dfc51103"
MARKER_NAME = "mvsep-mega53-ready.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _asset(model_dir: Path, name: str) -> Path:
    direct = model_dir / name
    nested = model_dir / MODEL_SLUG / name
    return direct if direct.exists() else nested


def verify(model_dir: Path, quick: bool = False) -> dict:
    checkpoint = _asset(model_dir, CHECKPOINT_NAME)
    config = _asset(model_dir, CONFIG_NAME)
    expected = (
        ("checkpoint", checkpoint, CHECKPOINT_SIZE, CHECKPOINT_SHA256),
        ("config", config, CONFIG_SIZE, CONFIG_SHA256),
    )
    result: dict[str, object] = {"model": MODEL_SLUG, "verified": False}
    for label, path, size, sha256 in expected:
        if not path.is_file():
            raise FileNotFoundError(f"Missing {label}: {path}")
        actual_size = path.stat().st_size
        if actual_size != size:
            raise RuntimeError(
                f"Invalid {label} size: {actual_size}; expected {size}: {path}"
            )
        if not quick:
            actual_sha256 = _sha256(path)
            if actual_sha256.casefold() != sha256:
                raise RuntimeError(
                    f"Invalid {label} SHA256: {actual_sha256}; expected {sha256}: {path}"
                )
        result[label] = {
            "path": str(path.resolve()), "size": size, "sha256": sha256,
        }
    config_text = config.read_text(encoding="utf-8")
    for stem in ("acoustic-guitar", "electric-guitar"):
        if stem not in config_text:
            raise RuntimeError(f"Official config does not declare {stem}: {config}")
    result["outputs"] = ["acoustic-guitar", "electric-guitar"]
    result["verified"] = True
    if quick:
        marker = model_dir / MARKER_NAME
        try:
            saved = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Missing or invalid verified marker; run the v3.3.5 installer: {marker}"
            ) from exc
        if (
            saved.get("verified") is not True
            or saved.get("model") != MODEL_SLUG
            or saved.get("checkpoint", {}).get("sha256") != CHECKPOINT_SHA256
            or saved.get("config", {}).get("sha256") != CONFIG_SHA256
        ):
            raise RuntimeError(
                "Old/fake MVSep ready marker rejected; run Install-MVSep-Mega53-v335.cmd"
            )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--write-marker", action="store_true")
    args = parser.parse_args()
    result = verify(args.model_dir.resolve(), quick=args.quick)
    if args.write_marker:
        marker = args.model_dir.resolve() / MARKER_NAME
        marker.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"READY: {marker}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
