"""Rules for turning an unmanaged source folder into the published AI library.

The functions in this module are deliberately independent from Qt/FastAPI so the
same rules are used by the preflight report, the batch worker and unit tests.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from app.chinese_normalization import to_simplified


AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
    ".wma", ".aiff", ".aif", ".alac",
}

DJ_PATTERN = re.compile(r"(?<![a-z])dj(?![a-z])|dj版|dj混音|dj慢摇", re.I)
INSTRUMENT_VERSION_PATTERN = re.compile(
    r"(?:^|[\s（(\[_-])(?:伴奏|纯伴奏|纯音乐|消音版|无人声|"
    r"架子鼓版|鼓版|吉他版|木吉他版|电吉他版|钢琴版|键盘版|贝斯版|"
    r"弦乐版|萨克斯版|小提琴版|古筝版)(?:$|[\s）)\]_-])",
    re.I,
)
FRAGMENT_PATTERN = re.compile(r"(?:片段|试听|铃声|live弹唱版片段|demo)", re.I)
TRACK_PREFIX_PATTERN = re.compile(r"^\s*\d{1,4}(?:[ ._-]+|(?=[\u4e00-\u9fffA-Za-z]))")
ARTIST_SUFFIX_PATTERN = re.compile(
    r"(?:\s*[（(]\s*\d+\s*[）)]|\s*[-_ ]?\d+|\s*(?:歌曲合集|音乐合集|全集|精选))+$",
    re.I,
)
TITLE_VERSION_PATTERN = re.compile(
    r"\s*[（(]\s*(?:原版|正式版|完整版|录音室版|国语版|粤语版)\s*[）)]\s*$",
    re.I,
)


def _text(value: str) -> str:
    return to_simplified(unicodedata.normalize("NFC", str(value or "")).strip())


def normalize_artist_name(value: str) -> str:
    """Merge numbered/collection singer folders into one canonical singer."""

    text = _text(value)
    text = TRACK_PREFIX_PATTERN.sub("", text)
    text = re.sub(r"[（(](?:MP3|FLAC|WAV|无损)[）)]", "", text, flags=re.I)
    text = ARTIST_SUFFIX_PATTERN.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" ._-—")
    return text or "未知歌手"


def normalize_song_title(value: str) -> str:
    """Normalize track numbers while retaining meaningful song-title text."""

    text = _text(Path(value).stem)
    text = TRACK_PREFIX_PATTERN.sub("", text)
    text = TITLE_VERSION_PATTERN.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" ._-—")
    return text or "未知歌曲"


def artist_from_source_path(path: Path, source_root: Path) -> str:
    """Use the first directory below the source root as the authoritative singer.

    This avoids incorrectly treating nested album or CD folders as singers.
    Existing A-Z bucket layouts are also supported.
    """

    try:
        directories = list(path.relative_to(source_root).parts[:-1])
    except (ValueError, OSError):
        directories = list(path.parts[:-1])
    generic = {
        "01_originals", "originals", "mp3", "flac", "无损", "音乐", "歌曲",
        "本地导入", "链接导入", "临时歌曲库", "working", "converted",
    }
    for raw in directories:
        candidate = normalize_artist_name(raw)
        if not candidate or candidate.casefold() in generic or "按歌手分类" in candidate:
            continue
        if re.match(r"^[A-Z](?:\s|$)", candidate, flags=re.I) and any(
            marker in candidate for marker in ("字母", "歌手", "分类", "开头")
        ):
            continue
        return candidate
    return "未知歌手"


def title_and_artist(path: Path, source_root: Path) -> tuple[str, str]:
    """Derive stable title/artist labels without album folders in the result."""

    artist = artist_from_source_path(path, source_root)
    stem = _text(path.stem)
    clean = TRACK_PREFIX_PATTERN.sub("", stem)
    if " - " in clean:
        left, right = clean.split(" - ", 1)
        left_artist = normalize_artist_name(left)
        if left_artist and left_artist != "未知歌手":
            artist = left_artist
        clean = right
    elif "-" in clean:
        left, right = clean.split("-", 1)
        if normalize_artist_name(left).casefold() == artist.casefold():
            clean = right
        elif artist == "未知歌手" and 1 <= len(right.strip()) <= 100:
            clean = left
            artist = normalize_artist_name(right)
    return normalize_song_title(clean), artist


def candidate_key(artist: str, title: str) -> str:
    simplified_title = re.sub(r"[\s·•._—-]+", "", normalize_song_title(title)).casefold()
    simplified_artist = re.sub(r"[\s·•._—-]+", "", normalize_artist_name(artist)).casefold()
    return f"{simplified_artist}|{simplified_title}"


@dataclass(frozen=True)
class BatchDecision:
    source_path: str
    artist: str
    title: str
    canonical_key: str
    action: str
    reason: str
    size_bytes: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def classify_source_candidate(path: Path, source_root: Path) -> BatchDecision:
    title, artist = title_and_artist(path, source_root)
    searchable = f"{path.parent} {path.stem}"
    action, reason = "process", "符合处理规则"
    if path.suffix.casefold() not in AUDIO_EXTENSIONS:
        action, reason = "ignore", "不是音频文件"
    elif DJ_PATTERN.search(searchable):
        action, reason = "skip", "DJ/混音版本不处理"
    elif INSTRUMENT_VERSION_PATTERN.search(searchable):
        action, reason = "skip", "伴奏或单乐器版本不处理"
    elif FRAGMENT_PATTERN.search(searchable):
        action, reason = "review", "DEMO/片段/试听版本需要人工复核"
    try:
        size = int(path.stat().st_size)
    except OSError:
        size = 0
    return BatchDecision(
        source_path=str(path), artist=artist, title=title,
        canonical_key=candidate_key(artist, title), action=action,
        reason=reason, size_bytes=size,
    )


def _quality_rank(decision: BatchDecision) -> tuple[int, int, str]:
    extension = Path(decision.source_path).suffix.casefold()
    lossless = 2 if extension in {".flac", ".wav", ".aiff", ".aif", ".alac"} else 1
    return lossless, int(decision.size_bytes), decision.source_path.casefold()


def build_processing_plan(paths: Iterable[Path], source_root: Path) -> list[BatchDecision]:
    """Classify candidates and suppress duplicate canonical artist/title pairs."""

    decisions = [classify_source_candidate(Path(path), source_root) for path in paths]
    winners: dict[str, BatchDecision] = {}
    for item in decisions:
        if item.action != "process":
            continue
        current = winners.get(item.canonical_key)
        if current is None or _quality_rank(item) > _quality_rank(current):
            winners[item.canonical_key] = item
    result: list[BatchDecision] = []
    for item in decisions:
        if item.action == "process" and winners.get(item.canonical_key) != item:
            item = BatchDecision(
                **{**item.as_dict(), "action": "duplicate", "reason": "同歌手同名歌曲只保留一个最佳源文件"}
            )
        result.append(item)
    return sorted(result, key=lambda item: (item.artist.casefold(), item.title.casefold(), item.source_path.casefold()))


def finished_song_dir(processed_root: Path, artist_initial: str, artist: str, title: str) -> Path:
    """Return `01_Ready/首字母/歌手/歌曲`; album names are intentionally absent."""

    def safe(value: str, fallback: str) -> str:
        text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", _text(value))
        return (text.strip(" .") or fallback)[:96]

    initial = (str(artist_initial or "#").strip().upper()[:1] or "#")
    if not re.fullmatch(r"[A-Z]", initial):
        initial = "#"
    return (
        Path(processed_root) / "01_Ready" / initial
        / safe(normalize_artist_name(artist), "未知歌手")
        / safe(normalize_song_title(title), "未知歌曲")
    )
