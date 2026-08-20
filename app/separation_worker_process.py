import argparse
import json
import sys
import traceback
from pathlib import Path

from app.uvr_separator import run_uvr_separation


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


def _self_test() -> int:
    """Verify imports inside the real frozen Worker, not the build interpreter."""

    modules = {}
    failures = []
    checks = (
        ("torch", "torch"),
        ("demucs", "demucs.api"),
        ("audio_separator", "audio_separator.separator"),
        ("soundfile", "soundfile"),
        ("librosa", "librosa"),
    )
    for label, module_name in checks:
        try:
            module = __import__(module_name, fromlist=["*"])
            modules[label] = str(getattr(module, "__version__", "OK"))
        except Exception as exc:
            modules[label] = f"ERROR: {type(exc).__name__}: {exc}"
            failures.append(label)
    if failures:
        emit(
            "failed",
            error="Worker 缺少或无法加载模块：" + "、".join(failures),
            modules=modules,
        )
        return 2
    emit("done", self_test=True, modules=modules)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?")
    parser.add_argument("--output")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return _self_test()
    if not args.input or not args.output:
        parser.error("input and --output are required unless --self-test is used")

    input_file = Path(args.input).resolve()
    output_root = Path(args.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    log_dir = output_root.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "separation-worker.log"

    try:
        import torch

        if args.device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            device = args.device

        emit("diagnostic", torch=str(torch.__version__), cuda_runtime=str(torch.version.cuda), cuda_available=bool(torch.cuda.is_available()), device=device)
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("请求使用 CUDA，但当前 Worker 检测不到 NVIDIA CUDA。")

        if device == "cuda":
            emit("diagnostic", gpu=torch.cuda.get_device_name(0), gpu_count=torch.cuda.device_count())

        emit("model_progress", value=5, text="正在准备 UVR 六轨模型...")

        def callback(value, text):
            kind = "model_progress" if value <= 8 else "separation_progress"
            emit(kind, value=value, text=text)

        stem_dir, guitar_diagnostics = run_uvr_separation(
            input_file,
            output_root,
            device=device,
            progress=callback,
        )
        emit("model_progress", value=100, text="UVR 六轨模型准备完成")
        emit(
            "separation_progress", value=100,
            text=f"UVR 六轨 + 独立电吉他完成（电吉他活跃度 {guitar_diagnostics['electric_activity']:.0%}）",
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
