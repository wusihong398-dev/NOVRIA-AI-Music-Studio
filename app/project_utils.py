"""Pure helpers shared by the desktop app and its regression tests."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable


def normalized_path(value: str | os.PathLike[str]) -> str:
    """Return a stable, case-insensitive path key without requiring existence."""

    text = os.path.abspath(os.path.normpath(os.fspath(value)))
    return os.path.normcase(text).replace("\\", "/").casefold()


def safe_file_stem(value: str, fallback: str = "audio") -> str:
    """Create a Windows-safe filename stem while preserving Chinese text."""

    text = unicodedata.normalize("NFC", str(value or "")).strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text or fallback)[:96]


def repair_text(value: Any, fallback: str = "") -> str:
    """Normalize metadata and repair common UTF-8/Latin-1 mojibake safely."""

    if value is None:
        return fallback
    if isinstance(value, bytes):
        for encoding in ("utf-8", "gb18030", "big5", "latin-1"):
            try:
                return unicodedata.normalize("NFC", value.decode(encoding)).strip()
            except (UnicodeDecodeError, LookupError):
                continue
        return value.decode("utf-8", errors="replace").strip()

    text = unicodedata.normalize("NFC", str(value)).strip()
    if not text:
        return fallback
    if any(marker in text for marker in ("Ã", "Â", "â", "ä¸", "å", "æ", "�")):
        try:
            repaired = text.encode("latin-1").decode("utf-8")
            if repaired and repaired.count("�") <= text.count("�"):
                text = repaired
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return text.strip() or fallback


_LRC_TIME = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


def _parse_lrc(text: str) -> list[dict]:
    rows: list[dict] = []
    offset_match = re.search(r"\[offset:([+-]?\d+)\]", text, flags=re.I)
    offset_ms = int(offset_match.group(1)) if offset_match else 0
    for line in text.splitlines():
        stamps = list(_LRC_TIME.finditer(line))
        lyric = _LRC_TIME.sub("", line).strip()
        if not stamps or not lyric or re.fullmatch(r"\[[a-z]+:.*\]", lyric, flags=re.I):
            continue
        for stamp in stamps:
            fraction = stamp.group(3) or "0"
            start = max(
                0.0,
                int(stamp.group(1)) * 60 + int(stamp.group(2))
                + int(fraction) / (10 ** len(fraction)) + offset_ms / 1000,
            )
            rows.append({"start": round(start, 3), "text": lyric})
    rows.sort(key=lambda row: row["start"])
    return rows


def _embedded_lyrics(path: Path) -> str:
    try:
        import mutagen
        audio = mutagen.File(str(path), easy=False)
        tags = getattr(audio, "tags", None)
        if not tags:
            return ""
        for key in tags.keys():
            value = tags[key]
            lowered = str(key).casefold()
            if lowered.startswith(("sylt", "uslt")):
                raw = getattr(value, "text", "")
                return "\n".join(str(item) for item in raw) if isinstance(raw, list) else str(raw or "")
            if lowered in {"lyrics", "unsyncedlyrics", "syncedlyrics", "©lyr"}:
                return "\n".join(str(item) for item in value) if isinstance(value, (list, tuple)) else str(value or "")
    except Exception:
        return ""
    return ""


def load_synced_lyrics(path: str | Path, duration: float = 0) -> list[dict]:
    audio_path = Path(path)
    text = ""
    for candidate in (audio_path.with_suffix(".lrc"), audio_path.parent / f"{audio_path.stem}.LRC"):
        if not candidate.is_file():
            continue
        for encoding in ("utf-8-sig", "gb18030", "big5"):
            try:
                text = candidate.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        if text:
            break
    if not text:
        text = _embedded_lyrics(audio_path)
    if not text.strip():
        return []
    rows = _parse_lrc(text)
    if not rows:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        step = max(2.0, float(duration or len(lines) * 4) / max(1, len(lines)))
        rows = [{"start": round(index * step, 3), "text": line} for index, line in enumerate(lines)]
    for index, row in enumerate(rows):
        next_start = rows[index + 1]["start"] if index + 1 < len(rows) else max(float(duration), row["start"] + 4)
        row["end"] = round(max(row["start"] + .2, next_start), 3)
    return rows


def split_guitar_stem(stem_dir: str | Path) -> dict:
    """Split the six-stem model's combined guitar into aligned acoustic/electric files."""
    import shutil
    import librosa
    import numpy as np
    import soundfile as sf

    def percentile_scale(values):
        low, high = np.percentile(values, (10, 90))
        if high - low < 1e-8:
            return np.full_like(values, 0.5, dtype=np.float32)
        return np.clip((values - low) / (high - low), 0, 1).astype(np.float32)

    folder = Path(stem_dir)
    guitar = folder / "guitar.wav"
    if not guitar.is_file():
        raise FileNotFoundError(f"缺少基础吉他轨：{guitar}")
    combined = folder / "guitar_combined.wav"
    if not combined.exists():
        shutil.copy2(guitar, combined)
    audio, sample_rate = sf.read(str(combined), always_2d=True, dtype="float32")
    if not len(audio):
        raise RuntimeError("基础吉他轨为空")

    acoustic_channels, electric_channels, frame_scores = [], [], []
    n_fft, hop = 2048, 512
    for channel in audio.T:
        spectrum = librosa.stft(channel, n_fft=n_fft, hop_length=hop, center=True)
        magnitude = np.abs(spectrum) + 1e-9
        frequencies = librosa.fft_frequencies(sr=sample_rate, n_fft=n_fft)
        flatness = librosa.feature.spectral_flatness(S=magnitude)[0]
        centroid = librosa.feature.spectral_centroid(S=magnitude, sr=sample_rate)[0]
        high = magnitude[frequencies >= 1800].sum(axis=0) / magnitude.sum(axis=0)
        electric_time = 0.42 * percentile_scale(flatness) + 0.33 * percentile_scale(centroid) + 0.25 * percentile_scale(high)
        electric_time = np.convolve(electric_time, np.ones(9) / 9, mode="same")
        frame_scores.append(float(np.mean(electric_time)))
        frequency_prior = 0.35 + 0.65 / (1 + np.exp(-(frequencies - 900) / 650))
        mask = np.clip(0.10 + 0.72 * frequency_prior[:, None] * electric_time[None, :], 0.08, 0.82)
        electric = librosa.istft(spectrum * mask, hop_length=hop, length=len(channel))
        electric_channels.append(electric.astype(np.float32))
        acoustic_channels.append((channel - electric).astype(np.float32))
    sf.write(str(guitar), np.column_stack(acoustic_channels), sample_rate, subtype="PCM_24")
    sf.write(str(folder / "electric_guitar.wav"), np.column_stack(electric_channels), sample_rate, subtype="PCM_24")
    diagnostics = {
        "method": "spectral-soft-mask-v1", "base_model": "htdemucs_6s",
        "sample_rate": int(sample_rate), "duration": float(len(audio) / sample_rate),
        "electric_activity": round(float(np.mean(frame_scores)), 4),
        "outputs": ["guitar.wav", "electric_guitar.wav", "guitar_combined.wav"],
    }
    (folder / "guitar_second_stage.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    return diagnostics


def atomic_write_json(path: Path, data: Any) -> None:
    """Persist JSON without leaving a half-written recovery file after a crash."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def unique_import_candidates(
    fingerprint_db: dict[str, dict[str, Any]],
    working_files: Iterable[Path],
    fingerprint_func,
) -> list[tuple[str, str, str, float]]:
    """Merge source records and orphan work WAVs without creating duplicates."""

    candidates: list[tuple[str, str, str, float]] = []
    referenced_working: set[str] = set()
    seen_fingerprints: set[str] = set()

    for fingerprint, item in fingerprint_db.items():
        work = str(item.get("working") or item.get("source") or "")
        source = str(item.get("source") or work)
        if not work or not Path(work).exists():
            continue
        key = normalized_path(work)
        if key in referenced_working:
            continue
        referenced_working.add(key)
        seen_fingerprints.add(str(fingerprint))
        candidates.append((str(fingerprint), source, work, float(item.get("imported_at") or 0)))

    for path in working_files:
        if not path.is_file() or path.suffix.lower() != ".wav":
            continue
        if normalized_path(path) in referenced_working:
            continue
        fingerprint = str(fingerprint_func(path))
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        referenced_working.add(normalized_path(path))
        candidates.append((fingerprint, str(path), str(path), path.stat().st_mtime))

    return candidates

# v3.2 sync marker
