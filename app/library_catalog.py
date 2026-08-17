"""Shared local song-library catalog for desktop and mobile-server clients."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path
from typing import Callable

from app.project_utils import repair_text


AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
    ".wma", ".aiff", ".aif", ".alac",
}


def default_library_root() -> Path:
    configured = os.environ.get("JUWEIER_LIBRARY_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt" and Path("G:/").exists():
        return Path("G:/JuweierMusicLibrary")
    return (Path.cwd() / "JuweierMusicLibrary").resolve()


def ensure_library_layout(root: Path) -> dict[str, Path]:
    root = Path(root).expanduser().resolve()
    paths = {
        "root": root,
        "originals": root / "01_Originals",
        "covers": root / "02_Covers",
        "processed": root / "03_AI_Processed",
        "failed": root / "04_Import_Failed",
        "temp": root / "05_Temp",
        "database": root / "database",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def connect_catalog(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS tracks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT UNIQUE,
            source_path TEXT,
            working_path TEXT,
            title TEXT,
            artist TEXT,
            album TEXT,
            year TEXT,
            duration REAL DEFAULT 0,
            bitrate INTEGER DEFAULT 0,
            samplerate INTEGER DEFAULT 0,
            channels INTEGER DEFAULT 0,
            format TEXT,
            quality TEXT,
            cover_path TEXT,
            bpm REAL,
            musical_key TEXT,
            analysis_status TEXT DEFAULT '未分析',
            stems_status TEXT DEFAULT '未分轨',
            imported_at REAL,
            category TEXT DEFAULT '本地导入',
            favorite INTEGER DEFAULT 0,
            play_count INTEGER DEFAULT 0,
            last_played REAL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_tracks_artist_album ON tracks(artist,album);
        CREATE INDEX IF NOT EXISTS idx_tracks_title_artist ON tracks(title,artist);
        CREATE INDEX IF NOT EXISTS idx_tracks_category ON tracks(category);
        """
    )
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(tracks)")}
    migrations = {
        "chords_status": "TEXT DEFAULT '未处理'",
        "score_status": "TEXT DEFAULT '未处理'",
        "arrangement_status": "TEXT DEFAULT '未处理'",
        "render_status": "TEXT DEFAULT '未处理'",
        "final_audio_path": "TEXT DEFAULT ''",
        "category": "TEXT DEFAULT '本地导入'",
        "favorite": "INTEGER DEFAULT 0",
        "play_count": "INTEGER DEFAULT 0",
        "last_played": "REAL DEFAULT 0",
    }
    for name, ddl in migrations.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE tracks ADD COLUMN {name} {ddl}")
    connection.commit()
    return connection


def quick_fingerprint(path: Path) -> str:
    """Stable content fingerprint without rereading multi-GB libraries in full."""
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(str(stat.st_size).encode("ascii"))
    with path.open("rb") as stream:
        digest.update(stream.read(1024 * 1024))
        if stat.st_size > 1024 * 1024:
            stream.seek(max(0, stat.st_size - 1024 * 1024))
            digest.update(stream.read(1024 * 1024))
    return digest.hexdigest()


def _first_tag(tags, names: tuple[str, ...], fallback: str) -> str:
    if not tags:
        return fallback
    for name in names:
        try:
            value = tags.get(name)
            if value:
                if isinstance(value, (list, tuple)):
                    value = value[0]
                return repair_text(value, fallback)
        except Exception:
            continue
    return fallback


def extract_metadata(path: Path, cover_dir: Path) -> dict:
    stem = repair_text(path.stem, path.stem)
    title = stem
    artist = "未知歌手"
    if " - " in stem:
        left, right = stem.split(" - ", 1)
        artist, title = repair_text(left, "未知歌手"), repair_text(right, stem)
    data = {
        "title": title,
        "artist": artist,
        "album": "未分类专辑",
        "year": "",
        "duration": 0.0,
        "bitrate": 0,
        "samplerate": 0,
        "channels": 0,
        "format": path.suffix.lower().lstrip(".").upper(),
        "cover_path": "",
    }
    try:
        import mutagen

        audio = mutagen.File(str(path), easy=False)
        if audio is not None:
            info = getattr(audio, "info", None)
            if info:
                data["duration"] = float(getattr(info, "length", 0) or 0)
                data["bitrate"] = int(getattr(info, "bitrate", 0) or 0)
                data["samplerate"] = int(
                    getattr(info, "sample_rate", getattr(info, "samplerate", 0)) or 0
                )
                data["channels"] = int(getattr(info, "channels", 0) or 0)
            tags = getattr(audio, "tags", None)
            data["title"] = _first_tag(tags, ("title", "TITLE", "TIT2"), data["title"])
            data["artist"] = _first_tag(tags, ("artist", "ARTIST", "TPE1"), data["artist"])
            data["album"] = _first_tag(tags, ("album", "ALBUM", "TALB"), data["album"])
            data["year"] = _first_tag(tags, ("date", "year", "DATE", "TDRC"), "")
            cover_bytes = None
            try:
                for key in tags.keys() if tags else ():
                    value = tags[key]
                    if str(key).startswith("APIC"):
                        cover_bytes = getattr(value, "data", None)
                        if cover_bytes:
                            break
            except Exception:
                pass
            try:
                pictures = getattr(audio, "pictures", [])
                if pictures and not cover_bytes:
                    cover_bytes = pictures[0].data
            except Exception:
                pass
            try:
                covr = tags.get("covr") if tags and hasattr(tags, "get") else None
                if covr and not cover_bytes:
                    cover_bytes = bytes(covr[0])
            except Exception:
                pass
            if cover_bytes:
                cover_dir.mkdir(parents=True, exist_ok=True)
                cover = cover_dir / f"{hashlib.md5(str(path).encode('utf-8')).hexdigest()}.jpg"
                cover.write_bytes(cover_bytes)
                data["cover_path"] = str(cover)
    except Exception:
        pass
    bitrate = int(data["bitrate"] or 0)
    if path.suffix.lower() in {".wav", ".flac", ".aiff", ".aif", ".alac"}:
        data["quality"] = "无损/PCM"
    elif bitrate >= 320000:
        data["quality"] = "高码率"
    elif bitrate >= 192000:
        data["quality"] = "标准"
    elif bitrate:
        data["quality"] = "较低码率"
    else:
        data["quality"] = "待检测"
    return data


def category_for(path: Path) -> str:
    value = str(path).casefold()
    if "抖音" in value or "douyin" in value:
        return "抖音流行"
    if "酷狗" in value or "kugou" in value:
        return "酷狗排行榜"
    return "本地导入"


def scan_catalog(
    root: Path,
    db_path: Path,
    cover_dir: Path,
    progress: Callable[[int, int, Path], None] | None = None,
) -> dict[str, int]:
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    )
    connection = connect_catalog(db_path)
    added = updated = skipped = failed = 0
    try:
        for index, path in enumerate(files, start=1):
            if progress:
                progress(index, len(files), path)
            try:
                stat = path.stat()
                existing = connection.execute(
                    "SELECT id,imported_at FROM tracks WHERE source_path=?", (str(path),)
                ).fetchone()
                if existing and float(existing["imported_at"] or 0) == float(stat.st_mtime):
                    skipped += 1
                    continue
                fingerprint = quick_fingerprint(path)
                metadata = extract_metadata(path, cover_dir)
                connection.execute(
                    """
                    INSERT INTO tracks(
                        fingerprint,source_path,working_path,title,artist,album,year,
                        duration,bitrate,samplerate,channels,format,quality,cover_path,
                        imported_at,category
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        source_path=excluded.source_path,working_path=excluded.working_path,
                        title=excluded.title,artist=excluded.artist,album=excluded.album,
                        year=excluded.year,duration=excluded.duration,bitrate=excluded.bitrate,
                        samplerate=excluded.samplerate,channels=excluded.channels,
                        format=excluded.format,quality=excluded.quality,
                        cover_path=CASE WHEN excluded.cover_path<>'' THEN excluded.cover_path ELSE tracks.cover_path END,
                        imported_at=excluded.imported_at,category=excluded.category
                    """,
                    (
                        fingerprint, str(path), str(path), metadata["title"], metadata["artist"],
                        metadata["album"], metadata["year"], metadata["duration"],
                        metadata["bitrate"], metadata["samplerate"], metadata["channels"],
                        metadata["format"], metadata["quality"], metadata["cover_path"],
                        float(stat.st_mtime), category_for(path),
                    ),
                )
                if existing:
                    updated += 1
                else:
                    added += 1
            except Exception:
                failed += 1
        connection.commit()
    finally:
        connection.close()
    return {"total": len(files), "added": added, "updated": updated, "skipped": skipped, "failed": failed}


def list_catalog(db_path: Path, query: str = "", category: str = "全部", limit: int = 500) -> list[dict]:
    connection = connect_catalog(db_path)
    try:
        where = []
        values: list[object] = []
        text = query.strip()
        if text:
            where.append("(title LIKE ? OR artist LIKE ? OR album LIKE ?)")
            like = f"%{text}%"
            values.extend((like, like, like))
        if category and category != "全部":
            where.append("category=?")
            values.append(category)
        clause = " WHERE " + " AND ".join(where) if where else ""
        values.append(max(1, min(5000, int(limit))))
        rows = connection.execute(
            "SELECT * FROM tracks" + clause + " ORDER BY artist,title LIMIT ?", values
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def catalog_track(db_path: Path, track_id: int) -> dict | None:
    connection = connect_catalog(db_path)
    try:
        row = connection.execute("SELECT * FROM tracks WHERE id=?", (int(track_id),)).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()
