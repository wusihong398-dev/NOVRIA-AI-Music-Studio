"""Headless six-stem and dedicated-guitar separation.

The base stage runs the official Demucs ``htdemucs_6s`` API directly and writes
validated PCM WAV files atomically.  This avoids the audio-separator WAV writer
that produced unreadable files on the target Windows 10 server.  A second
MVSep Mega 53-Stems model must then produce explicit acoustic-guitar and
electric-guitar outputs.  No spectral-mask or EQ approximation is accepted.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Callable

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
        headers={"User-Agent": "Juweier-Music/3.5.0"},
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
    shutil.rmtree(stem_dir / "_electric_uvr", ignore_errors=True)
    shutil.rmtree(stem_dir / "_mega53_input", ignore_errors=True)
    shutil.rmtree(stem_dir / "_mega53_output", ignore_errors=True)


def _run_electric_guitar_uvr(
    stem_dir: Path,
    model_dir: Path,
    selected_device: str,
    base_engine: str,
    base_model: str,
    notify: Callable[[int, str], None],
) -> dict:
    """Run a real UVR two-stem guitar model against the combined Guitar stem."""

    electric_engine = os.environ.get(
        "JUWEIER_ELECTRIC_GUITAR_ENGINE", "audio-separator",
    ).strip().casefold()
    model = os.environ.get("JUWEIER_ELECTRIC_GUITAR_MODEL", "").strip()
    if not model:
        raise RuntimeError(
            "尚未配置真实电吉他二阶段模型；系统不会用频谱遮罩伪造电吉他轨。"
        )
    primary = os.environ.get("JUWEIER_ELECTRIC_GUITAR_PRIMARY_STEM", "Guitar").strip() or "Guitar"
    complement = os.environ.get(
        "JUWEIER_ELECTRIC_GUITAR_COMPLEMENT_STEM", "Instrumental",
    ).strip() or "Instrumental"
    guitar = stem_dir / "guitar.wav"
    if not _valid_wav(guitar):
        raise RuntimeError("基础六轨没有生成有效 Guitar stem，不能执行电吉他二次分离")
    combined = stem_dir / "guitar_combined.wav"
    combined_temp = stem_dir / "guitar_combined.part.wav"
    combined_temp.unlink(missing_ok=True)
    shutil.copy2(guitar, combined_temp)
    if not _valid_wav(combined_temp):
        combined_temp.unlink(missing_ok=True)
        raise RuntimeError("基础 Guitar stem 格式无效，不能执行电吉他二次分离")
    os.replace(combined_temp, combined)

    if electric_engine == "mvsep-mega53":
        return _run_mvsep_mega53_electric(
            combined, stem_dir, selected_device, base_engine, base_model, model, notify,
        )

    try:
        from audio_separator.separator import Separator
    except ImportError as exc:
        raise RuntimeError("缺少 audio-separator，无法运行真实电吉他 UVR 模型") from exc

    second_dir = stem_dir / "_electric_uvr"
    shutil.rmtree(second_dir, ignore_errors=True)
    second_dir.mkdir(parents=True, exist_ok=True)
    notify(96, f"加载真实电吉他 UVR 二阶段模型：{model}")
    separator = Separator(
        output_dir=str(second_dir), output_format="WAV",
        model_file_dir=str(model_dir), use_soundfile=True,
        use_autocast=selected_device == "cuda",
    )
    try:
        separator.load_model(model_filename=model)
        returned = [
            str(item) for item in separator.separate(
                str(combined), {primary: "electric_guitar", complement: "acoustic_guitar"},
            )
        ]
    except Exception as exc:
        raise RuntimeError(
            f"真实电吉他 UVR 模型运行失败：{model}。请确认模型已下载完整，且主 stem={primary}、"
            f"补集 stem={complement}。原始错误：{exc}"
        ) from exc

    electric = _resolve_output(second_dir, returned, "electric_guitar")
    acoustic = _resolve_output(second_dir, returned, "acoustic_guitar")
    if electric is None or not _valid_wav(electric):
        raise RuntimeError(f"模型 {model} 没有输出有效的独立 Electric Guitar stem")
    if acoustic is None or not _valid_wav(acoustic):
        raise RuntimeError(f"模型 {model} 没有输出有效的 Guitar 补集 stem")
    electric_target = stem_dir / "electric_guitar.wav"
    acoustic_target = stem_dir / "guitar.wav"
    electric_target.unlink(missing_ok=True)
    acoustic_target.unlink(missing_ok=True)
    shutil.move(str(electric), electric_target)
    shutil.move(str(acoustic), acoustic_target)
    shutil.rmtree(second_dir, ignore_errors=True)

    import soundfile as sf
    import numpy as np

    electric_audio, sample_rate = sf.read(str(electric_target), always_2d=True, dtype="float32")
    combined_audio, combined_rate = sf.read(str(combined), always_2d=True, dtype="float32")
    if sample_rate != combined_rate or abs(len(electric_audio) - len(combined_audio)) > sample_rate:
        raise RuntimeError("电吉他二阶段输出与原曲时长或采样率不一致，禁止发布")
    electric_rms = float(np.sqrt(np.mean(np.square(electric_audio))) if electric_audio.size else 0.0)
    combined_rms = float(np.sqrt(np.mean(np.square(combined_audio))) if combined_audio.size else 0.0)
    activity = min(1.0, electric_rms / max(combined_rms, 1e-9))
    diagnostics = {
        "method": "audio-separator/UVR-real-two-stage",
        "engine": base_engine,
        "base_model": base_model,
        "electric_model": model,
        "primary_stem": primary,
        "complement_stem": complement,
        "sample_rate": int(sample_rate),
        "duration": float(len(electric_audio) / max(sample_rate, 1)),
        "electric_activity": round(activity, 4),
        "outputs": ["guitar.wav", "electric_guitar.wav", "guitar_combined.wav"],
    }
    (stem_dir / "guitar_second_stage.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return diagnostics


def _run_mvsep_mega53_electric(
    combined: Path,
    stem_dir: Path,
    selected_device: str,
    base_engine: str,
    base_model: str,
    model: str,
    notify: Callable[[int, str], None],
) -> dict:
    """Extract explicit acoustic/electric guitar stems with MVSep Mega 53-Stems.

    The upstream checkpoint exposes separate ``acoustic-guitar`` and
    ``electric-guitar`` outputs.  The patched runner keeps only the active
    inference chunk on CUDA and performs overlap-add in system RAM.  CPU
    fallback is deliberately forbidden because one song can otherwise run for
    many hours without completing.
    """

    try:
        import bs_roformer  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "缺少 bs-roformer-infer，无法运行 MVSep Mega 53-Stems 独立电吉他模型"
        ) from exc

    model_slug = model or "roformer-model-bs-roformer-mvsep-mega-53-stems"
    input_dir = stem_dir / "_mega53_input"
    output_dir = stem_dir / "_mega53_output"
    shutil.rmtree(input_dir, ignore_errors=True)
    shutil.rmtree(output_dir, ignore_errors=True)
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(combined, input_dir / "guitar_combined.wav")
    models_dir = Path(os.environ.get(
        "JUWEIER_BS_ROFORMER_MODEL_DIR",
        str(stem_dir.parents[2] / "bs_roformer_models"),
    )).resolve()
    models_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_name = "mvsep_mega_model_bs_roformer_53_stems_v1.ckpt"
    config_name = "mvsep_mega_model_bs_roformer_53_stems.yaml"
    checkpoint = Path(os.environ.get(
        "JUWEIER_BS_ROFORMER_MODEL_PATH", str(models_dir / checkpoint_name),
    )).resolve()
    config = Path(os.environ.get(
        "JUWEIER_BS_ROFORMER_CONFIG_PATH", str(models_dir / config_name),
    )).resolve()
    if not checkpoint.is_file() or checkpoint.stat().st_size != 1_368_919_887:
        raise RuntimeError(
            "MVSep Mega 53-Stems 官方权重不存在或不完整；请运行 Install-MVSep-Mega53-v335.cmd"
        )
    if not config.is_file() or config.stat().st_size != 4_184:
        raise RuntimeError(
            "MVSep Mega 53-Stems 官方配置不存在或不完整；请运行 Install-MVSep-Mega53-v335.cmd"
        )
    runner_marker = models_dir / "bs-roformer-mega53-runner-ready.json"
    if not runner_marker.is_file():
        raise RuntimeError(
            "BS-RoFormer Mega53 运行器未通过架构兼容检查；"
            "请运行 Install-BS-RoFormer-Mega53-v336.cmd"
        )
    tail_marker = models_dir / "bs-roformer-tail-chunk-v337-ready.json"
    if not tail_marker.is_file():
        raise RuntimeError(
            "BS-RoFormer Mega53 尾块长度修复尚未安装；"
            "请运行 Install-BS-RoFormer-Tail-Fix-v337.cmd"
        )
    low_vram_marker = models_dir / "bs-roformer-low-vram-v338-ready.json"
    if not low_vram_marker.is_file():
        raise RuntimeError(
            "RTX 3060 低显存运行修复尚未安装；"
            "请运行 Install-BS-RoFormer-Low-VRAM-v338.cmd"
        )
    if not selected_device.startswith("cuda"):
        raise RuntimeError(
            "MVSep Mega 53-Stems 必须使用 CUDA；已禁止自动切换 CPU，"
            "避免单首歌曲运行数小时"
        )

    device = selected_device
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    notify(96, "MVSep Mega 53-Stems 低显存 CUDA 分块处理中（最长 120 分钟）")
    command = [
        sys.executable, "-m", "bs_roformer.inference",
        "--model_path", str(checkpoint),
        "--config_path", str(config),
        "--input_folder", str(input_dir),
        "--store_dir", str(output_dir),
        "--device", device,
        "--output_format", "wav_float32",
    ]
    timeout_seconds = max(
        600, int(os.environ.get("JUWEIER_MEGA53_TIMEOUT_SECONDS", "7200"))
    )
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        detail = ((exc.stderr or exc.stdout or "")[-2000:] if isinstance(
            exc.stderr or exc.stdout or "", str
        ) else "")
        raise RuntimeError(
            f"MVSep Mega 53-Stems CUDA 超过 {timeout_seconds // 60} 分钟，"
            f"已自动终止且不会切换 CPU。{detail}"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error")[-6000:]
        raise RuntimeError(
            "MVSep Mega 53-Stems CUDA 运行失败，已禁止 CPU 回退：" + detail
        )
    used_device = device

    electric = next(output_dir.glob("*_electric-guitar.wav"), None)
    acoustic = next(output_dir.glob("*_acoustic-guitar.wav"), None)
    if electric is None or not _valid_wav(electric):
        raise RuntimeError("MVSep Mega 53-Stems 没有生成有效 electric-guitar stem")
    if acoustic is None or not _valid_wav(acoustic):
        raise RuntimeError("MVSep Mega 53-Stems 没有生成有效 acoustic-guitar stem")
    electric_target = stem_dir / "electric_guitar.wav"
    acoustic_target = stem_dir / "guitar.wav"
    electric_target.unlink(missing_ok=True)
    acoustic_target.unlink(missing_ok=True)
    shutil.move(str(electric), electric_target)
    shutil.move(str(acoustic), acoustic_target)
    shutil.rmtree(input_dir, ignore_errors=True)
    shutil.rmtree(output_dir, ignore_errors=True)

    import numpy as np
    import soundfile as sf

    electric_audio, sample_rate = sf.read(str(electric_target), always_2d=True, dtype="float32")
    combined_audio, combined_rate = sf.read(str(combined), always_2d=True, dtype="float32")
    if sample_rate != combined_rate or abs(len(electric_audio) - len(combined_audio)) > sample_rate:
        raise RuntimeError("MVSep 电吉他输出与 Guitar stem 时长或采样率不一致，禁止发布")
    electric_rms = float(np.sqrt(np.mean(np.square(electric_audio))) if electric_audio.size else 0.0)
    combined_rms = float(np.sqrt(np.mean(np.square(combined_audio))) if combined_audio.size else 0.0)
    diagnostics = {
        "method": "MVSep-Mega-53-Stems/BS-RoFormer",
        "engine": base_engine,
        "base_model": base_model,
        "electric_model": model_slug,
        "device": used_device,
        "separate_outputs": ["acoustic-guitar", "electric-guitar"],
        "sample_rate": int(sample_rate),
        "duration": float(len(electric_audio) / max(sample_rate, 1)),
        "electric_activity": round(electric_rms / max(combined_rms, 1e-9), 4),
        "outputs": ["guitar.wav", "electric_guitar.wav", "guitar_combined.wav"],
    }
    (stem_dir / "guitar_second_stage.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return diagnostics


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

    notify(8, f"Demucs htdemucs_6s 直接六轨分离中（{selected_device.upper()}）")
    returned = _run_demucs_fallback(
        source, stem_dir, model_dir, selected_device, notify,
    )
    engine = "demucs/htdemucs_6s-direct-pcm-wav"

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

    notify(96, "UVR Guitar stem 完成，开始真实电吉他二阶段模型")
    diagnostics = _run_electric_guitar_uvr(
        stem_dir, model_dir, selected_device, engine, model, notify,
    )
    electric = stem_dir / "electric_guitar.wav"
    if not _valid_wav(electric):
        raise RuntimeError("二阶段电吉他识别没有生成有效 electric_guitar.wav，歌曲不能发布")
    guitar_info = stem_dir / "guitar_second_stage.json"
    if not guitar_info.is_file():
        raise RuntimeError("缺少电吉他二阶段识别报告，歌曲不能发布")
    notify(100, "UVR 六轨及独立电吉他轨处理完成")
    return stem_dir, diagnostics
