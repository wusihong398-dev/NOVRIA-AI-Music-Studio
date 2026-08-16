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
