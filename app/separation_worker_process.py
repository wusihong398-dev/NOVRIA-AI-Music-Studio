import argparse
import hashlib
import json
import os
import sys
import traceback
import urllib.request
from pathlib import Path

from app.project_utils import split_guitar_stem


def _force_utf8_stdio():
    # PyInstaller console workers on Simplified Chinese Windows may inherit GBK/CP936.
    # The parent process consumes JSONL as UTF-8, so make the worker stream deterministic.
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_force_utf8_stdio()


def emit(kind, **payload):
    obj = {"type": kind, **payload}
    print(json.dumps(obj, ensure_ascii=False), flush=True)


MODEL_URL = "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/5c90dfd2-34c22ccb.th"
MODEL_FILE = "5c90dfd2-34c22ccb.th"
MODEL_HASH_PREFIX = "34c22ccb"


def _sha256_ok(path: Path) -> bool:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest().startswith(MODEL_HASH_PREFIX)


def _ensure_model(torch_module) -> Path:
    cache_dir = Path(torch_module.hub.get_dir()) / "checkpoints"
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / MODEL_FILE
    if target.exists() and _sha256_ok(target):
        emit("model_progress", value=100, text="AI 六轨模型已安装")
        return target
    if target.exists():
        target.unlink()

    part = target.with_suffix(target.suffix + ".part")
    part.unlink(missing_ok=True)
    emit("model_progress", value=0, text="首次使用：正在连接 AI 模型服务器...")
    request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "Juweier-Music/3.2.2"})
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
                value = min(99, int(downloaded * 100 / total))
                text = f"下载 AI 模型 {value}%（{downloaded/1048576:.1f}/{total/1048576:.1f} MB）"
            else:
                value = 0
                text = f"已下载 AI 模型 {downloaded/1048576:.1f} MB"
            emit("model_progress", value=value, text=text)
    emit("model_progress", value=99, text="正在校验 AI 模型...")
    if not _sha256_ok(part):
        part.unlink(missing_ok=True)
        raise RuntimeError("AI 模型校验失败，请检查网络后重试。")
    os.replace(part, target)
    emit("model_progress", value=100, text="AI 六轨模型下载完成")
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    args = parser.parse_args()

    input_file = Path(args.input).resolve()
    output_root = Path(args.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    log_dir = output_root.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "separation-worker.log"

    try:
        import torch
        from demucs.api import Separator, save_audio

        if args.device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            device = args.device

        emit("diagnostic", torch=str(torch.__version__), cuda_runtime=str(torch.version.cuda), cuda_available=bool(torch.cuda.is_available()), device=device)
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("请求使用 CUDA，但当前 Worker 检测不到 NVIDIA CUDA。")

        if device == "cuda":
            emit("diagnostic", gpu=torch.cuda.get_device_name(0), gpu_count=torch.cuda.device_count())

        emit("model_progress", value=5, text="正在准备 Demucs 六轨模型...")
        _ensure_model(torch)

        def callback(info):
            try:
                audio_length = max(1, int(info.get("audio_length", 1)))
                offset = max(0, int(info.get("segment_offset", 0)))
                pct = int(min(96, max(1, offset * 96 / audio_length)))
                emit("separation_progress", value=pct, text=f"AI 六轨分离中 {pct}%")
            except Exception:
                pass

        separator = Separator(
            model="htdemucs_6s",
            device=device,
            shifts=1,
            overlap=0.25,
            split=True,
            jobs=0,
            progress=False,
            callback=callback,
        )
        emit("model_progress", value=100, text="AI 六轨模型准备完成")
        emit("separation_progress", value=1, text="正在读取歌曲并开始六轨分离...")

        _, separated = separator.separate_audio_file(input_file)
        song_name = input_file.stem
        stem_dir = output_root / "htdemucs_6s" / song_name
        stem_dir.mkdir(parents=True, exist_ok=True)

        stems = list(separated.items())
        total = max(1, len(stems))
        for i, (stem, source) in enumerate(stems, start=1):
            out = stem_dir / f"{stem}.wav"
            save_audio(source, out, samplerate=separator.samplerate)
            pct = 96 + int(i / total * 4)
            emit("separation_progress", value=min(100, pct), text=f"正在保存 {stem}.wav")

        emit("separation_progress", value=97, text="正在二次识别木吉他与电吉他...")
        guitar_diagnostics = split_guitar_stem(stem_dir)
        emit(
            "separation_progress", value=100,
            text=f"六轨基础分离 + 电吉他二次分离完成（电吉他活跃度 {guitar_diagnostics['electric_activity']:.0%}）",
        )

        emit("done", stem_dir=str(stem_dir))
        return 0
    except Exception as exc:
        text = traceback.format_exc()
        try:
            with log_file.open("a", encoding="utf-8") as f:
                f.write("\n===== worker failure =====\n")
                f.write(text)
        except Exception:
            pass
        emit("failed", error=f"{type(exc).__name__}: {exc}", traceback=text[-5000:])
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
