"""Traditional-to-Simplified normalization for published library products.

Source-file paths are deliberately not changed: they point to the user's
original files on D:.  Everything copied into the published product tree is
normalized before the atomic publish rename.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


TEXT_SUFFIXES = {
    ".csv", ".html", ".htm", ".json", ".lrc", ".md", ".musicxml",
    ".srt", ".txt", ".vtt", ".xml", ".yaml", ".yml",
}
PRESERVE_JSON_STRING_KEYS = {"source_path", "original_source_path"}


@lru_cache(maxsize=1)
def _opencc():
    try:
        from opencc import OpenCC
    except ImportError as exc:  # pragma: no cover - exercised on Windows install
        raise RuntimeError(
            "缺少繁体转简体组件，请运行 Install-Simplified-Chinese-Publishing-v339.cmd"
        ) from exc
    return OpenCC("t2s")


def to_simplified(value: object) -> str:
    """Return NFC-compatible Simplified Chinese text using OpenCC t2s."""

    return _opencc().convert(str(value or ""))


def simplify_json_value(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            to_simplified(key): simplify_json_value(item, parent_key=str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [simplify_json_value(item, parent_key=parent_key) for item in value]
    if isinstance(value, tuple):
        return [simplify_json_value(item, parent_key=parent_key) for item in value]
    if isinstance(value, str):
        if parent_key in PRESERVE_JSON_STRING_KEYS:
            return value
        return to_simplified(value)
    return value


def simplified_relative_path(path: Path) -> Path:
    return Path(*(to_simplified(part) for part in Path(path).parts))


def _rewrite_text_file(path: Path) -> None:
    if path.suffix.casefold() not in TEXT_SUFFIXES:
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    if path.suffix.casefold() == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            converted = to_simplified(text)
        else:
            converted = json.dumps(
                simplify_json_value(payload), ensure_ascii=False, indent=2,
            ) + "\n"
    else:
        converted = to_simplified(text)
    if converted != text:
        path.write_text(converted, encoding="utf-8")


def simplify_published_tree(root: Path) -> None:
    """Normalize text contents and every name below a staged product root."""

    root = Path(root)
    for item in root.rglob("*"):
        if item.is_file():
            _rewrite_text_file(item)

    # Rename bottom-up so parent changes never invalidate a child path.
    items = sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True)
    for item in items:
        simplified_name = to_simplified(item.name)
        if simplified_name == item.name:
            continue
        destination = item.with_name(simplified_name)
        if destination.exists():
            raise RuntimeError(f"简体化后文件名冲突：{destination}")
        item.rename(destination)
