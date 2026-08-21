"""Headless Ultimate Vocal Remover compatible six-stem separation.

The desktop and mobile server use ``audio-separator`` as the maintained
headless runner for models distributed through the UVR ecosystem.  The base
model produces the real guitar stem; a deterministic second stage then divides
that guitar signal into acoustic and electric outputs for the seven-channel UI.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.request
from pathlib import Path
from typing import Callable

from app.project_utils import split_guitar_stem


DEFAULT_UVR_MODEL = "htdemucs_6s.yaml"
STANDARD_STEMS = ("vocals", "drums", "bass", "guitar", "piano", "other")
DEMUCS_MODEL_FILE = "5c90dfd2-34c22ccb.th"
DEMUCS_MODEL_URL = (
    "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/"
    + DEMUCS_MODEL_FILE
)
DEMUCS_MODEL_HASH_PREFIX = "34c22ccb"


def _sha256_matches(path: Path, prefix: str) -> bool:
    if not path.is_file():
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().startswith(prefix)


def _atomic_text(path: Path, text: str) -> None:
    temp = path.with_name(path.name + ".part")
    temp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temp, path)


def _seed_offline_uvr_catalog(model_dir: Path) -> None:
    """Seed the two tiny UVR metadata files so model loading never needs GitHub."""

    yaml_path = model_dir / DEFAULT_UVR_MODEL
    yaml_text = (
        yaml_path.read_text(encoding="utf-8", errors="ignore").strip()
        if yaml_path.is_file() else ""
    )
    if yaml_text != "models: ['5c90dfd2']":
        _atomic_text(yaml_path, "models: ['5c90dfd2']\n")

    checks_path = model_dir / "download_checks.json"
    usable = False
    if checks_path.is_file():
        try:
            checks = json.loads(checks_path.read_text(encoding="utf-8"))
            usable = any(
                DEFAULT_UVR_MODEL in files
                for files in checks.get("demucs_download_list", {}).values()
            )
        except (OSError, ValueError, TypeError):
            usable = False
    if usable:
        return

    checks = {
        "vr_download_list": {},
        "mdx_download_list": {},
        "mdx_download_vip_list": {},
        "demucs_download_list": {
            "Demucs v4: htdemucs_6s": {
                DEMUCS_MODEL_FILE: DEMUCS_MODEL_URL,
                DEFAULT_UVR_MODEL: (
                    "https://github.com/TRvlvr/model_repo/releases/download/"
                    "all_public_uvr_models/htdemucs_6s.yaml"
                ),
            }
        },
        "mdx23c_download_list": {},
        "mdx23c_download_vip_list": {},
        "roformer_download_list": {},
    }
    _atomic_text(checks_path, json.dumps(checks, ensure_ascii=False, indent=2) + "\n")


def _ensure_demucs_model(
    model_dir: Path,
    notify: Callable[[int, str], None],
) -> Path:
    """Download the official six-stem weight once, with a resumable temp file."""

    target = model_dir / DEMUCS_MODEL_FILE
    if _sha256_matches(target, DEMUCS_MODEL_HASH_PREFIX):
        notify(7, "UVR htdemucs_6s 模型已从本地缓存加载")
        return target
    target.unlink(missing_ok=True)
    part = target.with_name(target.name + ".part")
    part.unlink(missing_ok=True)
    notify(1, "首次使用：正在从 Demucs 官方服务器下载六轨模型")
    request = urllib.request.Request(
        DEMUCS_MODEL_URL,
        headers={"User-Agent": "Juweier-Music/3.3.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as stream:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            while True:
                chunk = response.read(1024 * 512)
                if not chunk:
                    break
                stream.write(chunk)
                downloaded += len(chunk)
                if total:
                    percent = min(99, int(downloaded * 100 / total))
                    notify(
                        min(6, 1 + percent * 5 // 100),
                        f"下载六轨模型 {percent}%（{downloaded / 1048576:.1f}/{total / 1048576:.1f} MB）",
                    )
                else:
                    notify(3, f"已下载六轨模型 {downloaded / 1048576:.1f} MB")
    except Exception as exc:
        part.unlink(missing_ok=True)
        raise RuntimeError(
            "无法连接 Demucs 官方模型服务器；请检查服务器网络后重试。"
            f"模型缓存目录：{model_dir}"
        ) from exc
    if not _sha256_matches(part, DEMUCS_MODEL_HASH_PREFIX):
        part.unlink(missing_ok=True)
        raise RuntimeError("htdemucs_6s 模型校验失败，已删除不完整文件，请重试。")
    os.replace(part, target)
    notify(7, "UVR htdemucs_6s 六轨模型下载并校验完成")
    return target


def _valid_wav(path: Path) -> bool:
    try:
        import soundfile as sf

        info = sf.info(str(path))
        return info.frames > 0 and info.channels > 0 and info.samplerate > 0
    except Exception:
        return False


def _write_wav_atomic(path: Path, audio, sample_rate: int) -> None:
    import soundfile as sf

    temp = path.with_name(path.stem + ".part.wav")
    temp.unlink(missing_ok=True)
    sf.write(str(temp), audio, sample_rate, subtype="PCM_24")
    if not _valid_wav(temp):
        temp.unlink(missing_ok=True)
        raise RuntimeError(f"分轨结果不是有效 WAV：{path.name}")
    os.replace(temp, path)


def _clear_stale_outputs(stem_dir: Path) -> None:
    for name in (*STANDARD_STEMS, "electric_guitar", "guitar_combined"):
        (stem_dir / f"{name}.wav").unlink(missing_ok=True)
        (stem_dir / f"{name}.part.wav").unlink(missing_ok=True)
    (stem_dir / "guitar_second_stage.json").unlink(missing_ok=True)


def _run_demucs_fallback(
    source: Path,
    stem_dir: Path,
    model_dir: Path,
    selected_device: str,
    notify: Callable[[int, str], None],
) -> list[str]:
    """Run the same official htdemucs_6s model without audio-separator."""

    try:
        from demucs.api import Separator as DemucsSeparator
    except ImportError as exc:
        missing = getattr(exc, "name", "demucs") or "demucs"
        raise RuntimeError(f"六轨运行环境缺少 Python 模块：{missing}") from exc

    last_value = 8

    def callback(state: dict) -> None:
        nonlocal last_value
        length = max(1, int(state.get("audio_length", 1) or 1))
        offset = max(0, int(state.get("segment_offset", 0) or 0))
        value = min(92, 10 + int(offset * 82 / length))
        if value >= last_value + 2:
            last_value = value
            notify(value, f"Demucs 六轨离线分离中（{selected_device.upper()}）")

    notify(8, "UVR 运行器不可用，切换本地 Demucs htdemucs_6s 六轨引擎")
    separator = DemucsSeparator(
        model="htdemucs_6s",
        repo=model_dir,
        device=selected_device,
        shifts=2,
        overlap=0.25,
        split=True,
        progress=False,
        callback=callback,
    )
    _, separated = separator.separate_audio_file(source)
    returned: list[str] = []
    for stem in STANDARD_STEMS:
        tensor = separated.get(stem)
        if tensor is None:
            continue
        target = stem_dir / f"{stem}.wav"
        _write_wav_atomic(
            target,
            tensor.detach().cpu().float().numpy().T,
            int(separator.samplerate),
        )
        returned.append(str(target))
    return returned


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
    except ImportError as exc:
        raise RuntimeError("未安装 PyTorch，无法运行六轨分离。") from exc

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
    _clear_stale_outputs(stem_dir)
    _seed_offline_uvr_catalog(model_dir)
    _ensure_demucs_model(model_dir, notify)

    separator = None
    load_error: Exception | None = None
    try:
        from audio_separator.separator import Separator

        notify(7, f"正在从本地缓存加载 UVR 模型：{model}")
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
    except Exception as exc:
        load_error = exc
        separator = None

    notify(8, f"UVR 六轨分离中（{selected_device.upper()}）")
    output_names = {
        "Vocals": "vocals",
        "Drums": "drums",
        "Bass": "bass",
        "Guitar": "guitar",
        "Piano": "piano",
        "Other": "other",
    }
    if separator is not None:
        returned = [str(item) for item in separator.separate(str(source), output_names)]
        engine = "audio-separator/UVR"
    else:
        if load_error is not None:
            missing = getattr(load_error, "name", "") or str(load_error)
            notify(8, f"UVR 加载失败（{missing}），自动启用本地六轨兜底")
        returned = _run_demucs_fallback(
            source, stem_dir, model_dir, selected_device, notify,
        )
        engine = "demucs/htdemucs_6s-offline-fallback"

    missing: list[str] = []
    for stem in STANDARD_STEMS:
        target = stem_dir / f"{stem}.wav"
        resolved = _resolve_output(stem_dir, returned, stem)
        if resolved is None:
            missing.append(stem)
            continue
        if resolved.resolve() != target.resolve():
            shutil.move(str(resolved), str(target))
        if not _valid_wav(target):
            missing.append(f"{stem}（WAV 损坏）")
    if missing:
        raise RuntimeError("UVR 分轨结果缺少：" + "、".join(missing))

    notify(96, "UVR 吉他轨完成，正在识别木吉他与电吉他")
    diagnostics = split_guitar_stem(
        stem_dir,
        engine=engine,
        model=model,
    )
    electric = stem_dir / "electric_guitar.wav"
    if not _valid_wav(electric):
        raise RuntimeError("二阶段电吉他识别没有生成有效 electric_guitar.wav，歌曲不能发布")
    guitar_info = stem_dir / "guitar_second_stage.json"
    if not guitar_info.is_file():
        raise RuntimeError("缺少电吉他二阶段识别报告，歌曲不能发布")
    notify(100, "UVR 六轨及独立电吉他轨处理完成")
    return stem_dir, diagnostics
