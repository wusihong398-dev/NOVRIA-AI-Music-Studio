"""Headless Ultimate Vocal Remover compatible six-stem separation.

The desktop and mobile server use ``audio-separator`` as the maintained
headless runner for models distributed through the UVR ecosystem.  The base
model produces the real guitar stem; a deterministic second stage then divides
that guitar signal into acoustic and electric outputs for the seven-channel UI.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable

from app.project_utils import split_guitar_stem


DEFAULT_UVR_MODEL = "htdemucs_6s.yaml"
STANDARD_STEMS = ("vocals", "drums", "bass", "guitar", "piano", "other")


def _resolve_output(stem_dir: Path, returned: list[str], stem: str) -> Path | None:
    target = stem_dir / f"{stem}.wav"
    if target.is_file():
        return target
    label = stem.casefold()
    candidates: list[Path] = []
    for value in returned:
        path = Path(value)
        if not path.is_absolute():
            path = stem_dir / path
        if path.is_file() and label in path.stem.casefold():
            candidates.append(path)
    candidates.extend(
        path for path in stem_dir.glob("*.wav")
        if label in path.stem.casefold() and path not in candidates
    )
    return candidates[0] if candidates else None


def run_uvr_separation(
    input_file: str | Path,
    output_root: str | Path,
    device: str = "auto",
    progress: Callable[[int, str], None] | None = None,
) -> tuple[Path, dict]:
    """Run a UVR-compatible six-stem model and return the standardized folder."""

    notify = progress or (lambda _value, _text: None)
    source = Path(input_file).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"找不到待分轨歌曲：{source}")

    try:
        import torch
        from audio_separator.separator import Separator
    except ImportError as exc:
        raise RuntimeError(
            "未安装 UVR 分轨运行环境（audio-separator）；请重新运行 Install-AI-Engine.bat "
            "或安装 requirements-server.txt。"
        ) from exc

    selected_device = (
        "cuda" if device == "auto" and torch.cuda.is_available() else
        "cpu" if device == "auto" else device
    )
    model = os.environ.get("JUWEIER_UVR_MODEL", DEFAULT_UVR_MODEL).strip() or DEFAULT_UVR_MODEL
    output_root = Path(output_root).resolve()
    stem_dir = output_root / "uvr_htdemucs_6s" / source.stem
    model_dir = Path(os.environ.get("JUWEIER_UVR_MODEL_DIR", output_root.parent / "uvr_models")).resolve()
    stem_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)

    notify(2, f"正在加载 UVR 模型：{model}")
    separator = Separator(
        output_dir=str(stem_dir),
        output_format="WAV",
        model_file_dir=str(model_dir),
        use_soundfile=True,
        use_autocast=selected_device == "cuda",
        demucs_params={
            "segment_size": "Default",
            "shifts": 2,
            "overlap": 0.25,
            "segments_enabled": True,
        },
    )
    separator.load_model(model_filename=model)
    notify(8, f"UVR 六轨分离中（{selected_device.upper()}）")
    output_names = {
        "Vocals": "vocals",
        "Drums": "drums",
        "Bass": "bass",
        "Guitar": "guitar",
        "Piano": "piano",
        "Other": "other",
    }
    returned = [str(item) for item in separator.separate(str(source), output_names)]

    missing: list[str] = []
    for stem in STANDARD_STEMS:
        target = stem_dir / f"{stem}.wav"
        resolved = _resolve_output(stem_dir, returned, stem)
        if resolved is None:
            missing.append(stem)
            continue
        if resolved.resolve() != target.resolve():
            shutil.move(str(resolved), str(target))
    if missing:
        raise RuntimeError("UVR 分轨结果缺少：" + "、".join(missing))

    notify(96, "UVR 吉他轨完成，正在识别木吉他与电吉他")
    diagnostics = split_guitar_stem(
        stem_dir,
        engine="audio-separator/UVR",
        model=model,
    )
    notify(100, "UVR 六轨及独立电吉他轨处理完成")
    return stem_dir, diagnostics
