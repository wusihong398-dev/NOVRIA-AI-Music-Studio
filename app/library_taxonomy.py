"""Shared Juweier Music discovery taxonomy for desktop, mobile and server."""

from __future__ import annotations

import json
import re
from pathlib import Path


DISCOVERY_TABS = ("推荐", "乐库", "歌单", "歌手", "分类", "AI成果")

CATEGORY_GROUPS = {
    "语种": ("华语", "粤语", "欧美", "日韩"),
    "曲风": ("流行", "摇滚", "民谣", "古风", "电子", "DJ", "经典", "轻音乐"),
    "场景": ("情歌", "儿童", "车载", "KTV", "广场舞", "影视", "游戏", "运动"),
    "榜单": ("新歌", "抖音流行", "酷狗排行榜"),
    "成果": ("AI已完成", "有歌词", "有乐谱", "有分轨"),
}

DEFAULT_CATEGORIES = (
    "全部", "推荐", "临时歌曲库", "新歌", "华语", "粤语", "欧美", "日韩", "流行", "摇滚",
    "民谣", "古风", "电子", "DJ", "经典", "轻音乐", "情歌", "儿童", "车载",
    "KTV", "广场舞", "影视", "游戏", "运动", "抖音流行", "酷狗排行榜",
    "AI已完成", "有歌词", "有乐谱", "有分轨",
)


def taxonomy_payload() -> dict:
    return {
        "tabs": list(DISCOVERY_TABS),
        "groups": {name: list(values) for name, values in CATEGORY_GROUPS.items()},
        "categories": list(DEFAULT_CATEGORIES),
    }


def normalize_artist_initial(value: str | None) -> str:
    text = (value or "").strip().upper()
    return text[0] if text and "A" <= text[0] <= "Z" else "#"


def manual_initial_from_path(path: str | Path) -> str:
    """Read the curator-written A-Z bucket from folders; this value wins over tags."""
    for part in re.split(r"[\\/]", str(path)):
        text = str(part).strip().upper()
        match = re.match(r"^([A-Z])(?:\s+|[._-])", text)
        if match and any(marker in text for marker in ("字母", "歌手", "开头", "分类")):
            return match.group(1)
        if re.fullmatch(r"[A-Z]", text):
            return text
    return ""


def automatic_artist_initial(artist: str) -> str:
    text = (artist or "").strip()
    if text and text[0].isascii() and text[0].isalpha():
        return text[0].upper()
    try:
        from pypinyin import Style, lazy_pinyin

        values = lazy_pinyin(text, style=Style.FIRST_LETTER, errors="ignore")
        return normalize_artist_initial(values[0] if values else "")
    except Exception:
        return "#"


def artist_initial_for(path: str | Path, artist: str, saved: str = "", locked: bool = False) -> tuple[str, int]:
    if locked and normalize_artist_initial(saved) != "#":
        return normalize_artist_initial(saved), 1
    manual = manual_initial_from_path(path)
    if manual:
        return manual, 1
    return automatic_artist_initial(artist), 0


def classify_path(path: str | Path, title: str = "", artist: str = "") -> dict:
    value = " ".join((str(path), title, artist)).casefold()
    tags: list[str] = []

    rules = {
        "粤语": ("粤语", "广东", "hong kong", "cantonese"),
        "华语": ("华语", "国语", "中文", "mandarin", "大陆", "台湾"),
        "欧美": ("欧美", "western", "english", "billboard"),
        "日韩": ("日韩", "韩国", "日本", "k-pop", "j-pop", "korean", "japanese"),
        "摇滚": ("摇滚", "rock"),
        "民谣": ("民谣", "folk"),
        "古风": ("古风", "国风"),
        "电子": ("电子", "edm", "electronic"),
        "DJ": ("dj", "舞曲"),
        "经典": ("经典", "怀旧", "老歌"),
        "轻音乐": ("轻音乐", "纯音乐", "instrumental"),
        "情歌": ("情歌", "love song"),
        "儿童": ("儿童", "儿歌"),
        "车载": ("车载",),
        "KTV": ("ktv", "伴奏"),
        "广场舞": ("广场舞",),
        "影视": ("影视", "电影", "电视剧", "ost"),
        "游戏": ("游戏", "game"),
        "运动": ("运动", "跑步", "workout"),
        "新歌": ("新歌", "新碟"),
        "抖音流行": ("抖音", "douyin", "tiktok"),
        "酷狗排行榜": ("酷狗", "kugou"),
    }
    for name, needles in rules.items():
        if any(needle in value for needle in needles):
            tags.append(name)
    if not any(tag in tags for tag in ("摇滚", "民谣", "古风", "电子", "DJ", "经典", "轻音乐")):
        tags.append("流行")
    if not any(tag in tags for tag in ("华语", "粤语", "欧美", "日韩")):
        if re.search(r"[\u4e00-\u9fff]", title + artist):
            tags.append("华语")
    if any(marker in value for marker in ("05_temp", "链接导入", "临时歌曲库")):
        category = "临时歌曲库"
    else:
        category = next((tag for tag in ("抖音流行", "酷狗排行榜", "新歌") if tag in tags), "乐库")
    language = next((tag for tag in ("粤语", "华语", "欧美", "日韩") if tag in tags), "其他")
    genre = next((tag for tag in ("流行", "摇滚", "民谣", "古风", "电子", "DJ", "经典", "轻音乐") if tag in tags), "流行")
    scene = next((tag for tag in ("情歌", "儿童", "车载", "KTV", "广场舞", "影视", "游戏", "运动") if tag in tags), "")
    return {
        "category": category,
        "language": language,
        "genre": genre,
        "scene": scene,
        "tags": json.dumps(list(dict.fromkeys(tags)), ensure_ascii=False),
    }


def decode_tags(value: str | list | None) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    try:
        rows = json.loads(value or "[]")
        return [str(item) for item in rows] if isinstance(rows, list) else []
    except Exception:
        return [item.strip() for item in str(value or "").split(",") if item.strip()]
