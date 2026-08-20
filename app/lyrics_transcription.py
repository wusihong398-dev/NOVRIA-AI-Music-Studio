"""Server-side source-song lyric transcription with honest fallbacks.

Sidecar/embedded lyrics remain the preferred source.  When none exist, the
GPU server may enable faster-whisper.  This module is deliberately optional so
desktop and mobile packages do not silently bundle another multi-gigabyte
model.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.project_utils import load_synced_lyrics


def transcribe_synced_lyrics(path: str | Path, duration: float = 0) -> dict:
    audio_path = Path(path)
    existing = load_synced_lyrics(audio_path, duration)
    if existing:
        return {
            "rows": existing,
            "status": "ready",
            "source": "lrc_or_embedded",
            "language": "",
            "message": "已读取同名 LRC 或音频内嵌歌词",
        }

    if os.environ.get("JUWEIER_LYRICS_ASR_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        return {
            "rows": [], "status": "disabled", "source": "none", "language": "",
            "message": "服务器歌词识别已关闭；可上传同名 LRC 或开启 JUWEIER_LYRICS_ASR_ENABLED",
        }

    try:
        from faster_whisper import WhisperModel
    except Exception:
        return {
            "rows": [], "status": "model_unavailable", "source": "none", "language": "",
            "message": "服务器未安装 faster-whisper 歌词识别组件；请安装 requirements-lyrics-server.txt",
        }

    model_name = os.environ.get("JUWEIER_LYRICS_MODEL", "large-v3-turbo").strip() or "large-v3-turbo"
    device = os.environ.get("JUWEIER_LYRICS_DEVICE", "auto").strip().lower() or "auto"
    compute_type = os.environ.get("JUWEIER_LYRICS_COMPUTE_TYPE", "auto").strip() or "auto"
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        segments, info = model.transcribe(
            str(audio_path),
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=True,
        )
        rows = []
        for segment in segments:
            text = str(getattr(segment, "text", "") or "").strip()
            if not text:
                continue
            start = max(0.0, float(getattr(segment, "start", 0) or 0))
            end = max(start + 0.2, float(getattr(segment, "end", start + 0.2) or start + 0.2))
            words = []
            for word in list(getattr(segment, "words", None) or []):
                word_text = str(getattr(word, "word", "") or "").strip()
                if not word_text:
                    continue
                word_start = max(start, float(getattr(word, "start", start) or start))
                word_end = min(end, max(word_start + 0.04, float(getattr(word, "end", word_start + 0.2) or word_start + 0.2)))
                words.append({"start": round(word_start, 3), "end": round(word_end, 3), "text": word_text})
            rows.append({
                "start": round(start, 3), "end": round(end, 3), "text": text,
                "words": words,
            })
        language = str(getattr(info, "language", "") or "")
        return {
            "rows": rows,
            "status": "ready" if rows else "empty",
            "source": "faster_whisper",
            "language": language,
            "message": "AI 转写歌词需人工校对，粤语及现场录音可能出现同音字错误",
        }
    except Exception as exc:
        return {
            "rows": [], "status": "failed", "source": "faster_whisper", "language": "",
            "message": f"歌词识别失败：{type(exc).__name__}: {exc}",
        }
