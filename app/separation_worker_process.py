import argparse
import json
import os
import sys
import traceback
from pathlib import Path


def emit(kind, **payload):
    obj = {"type": kind, **payload}
    print(json.dumps(obj, ensure_ascii=False), flush=True)


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
