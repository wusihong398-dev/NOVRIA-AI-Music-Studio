"""Shared local song-library catalog for desktop and mobile-server clients."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from app.project_utils import repair_text, safe_file_stem


AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
    ".wma", ".aiff", ".aif", ".alac",
}

PARTIAL_DOWNLOAD_SUFFIXES = {
    ".part", ".tmp", ".download", ".downloading", ".aria2", ".crdownload",
    ".baiduyun.downloading", ".td",
}

GENERIC_ARTIST_FOLDERS = {
    "01_originals", "originals", "本地导入", "链接导入", "临时歌曲库",
    "抖音流行", "酷狗排行榜", "mp3", "flac", "无损", "音乐", "歌曲",
    "05_temp", "temp", "database", "按歌手分类", "working", "converted",
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
        "link_imports": root / "05_Temp" / "链接导入",
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
        "source_group": "TEXT DEFAULT ''",
    }
    for name, ddl in migrations.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE tracks ADD COLUMN {name} {ddl}")
    connection.commit()
    return connection


def _clean_folder_artist(value: str) -> str:
    text = repair_text(value, "").strip()
    text = re.sub(r"^\d+[.、_ -]+", "", text)
    text = re.sub(r"[（(](?:MP3|FLAC|WAV|无损)[）)]", "", text, flags=re.I)
    return text.strip(" ._-—")


def _is_letter_bucket(value: str) -> bool:
    """Return True for folders such as `A 字母开头歌手`, but not `A-Lin`."""
    text = _clean_folder_artist(value)
    if re.fullmatch(r"[A-Z]", text, flags=re.I):
        return True
    return bool(
        re.match(r"^[A-Z]\s+", text, flags=re.I)
        and any(marker in text for marker in ("字母", "开头", "歌手", "歌曲", "分类"))
    )


def infer_artist_from_path(path: Path, root: Path | None = None) -> str:
    """Infer the singer from the user's `按歌手分类/歌手/歌曲` directory layout."""
    try:
        parts = list(path.relative_to(root).parts[:-1]) if root else list(path.parts[:-1])
    except (ValueError, OSError):
        parts = list(path.parts[:-1])

    for index, raw in enumerate(parts):
        if "按歌手分类" in raw and index + 1 < len(parts):
            for nested in parts[index + 1:]:
                candidate = _clean_folder_artist(nested)
                if not candidate or _is_letter_bucket(candidate):
                    continue
                if candidate.casefold() in GENERIC_ARTIST_FOLDERS:
                    continue
                return candidate

    for raw in reversed(parts):
        candidate = _clean_folder_artist(raw)
        folded = candidate.casefold()
        if not candidate or folded in GENERIC_ARTIST_FOLDERS:
            continue
        if _is_letter_bucket(candidate):
            continue
        if "按歌手分类" in candidate or candidate.lower().endswith(("musiclibrary", "covers")):
            continue
        return candidate
    if root:
        candidate = _clean_folder_artist(root.name)
        if candidate and candidate.casefold() not in GENERIC_ARTIST_FOLDERS and "按歌手分类" not in candidate:
            return candidate
    return "未知歌手"


def catalog_artist_name(row: dict) -> str:
    """Prefer the real singer folder so G-drive classification wins over bad tags."""
    source_group = _clean_folder_artist(str(row.get("source_group") or ""))
    if (
        source_group
        and source_group != "未知歌手"
        and source_group.casefold() not in GENERIC_ARTIST_FOLDERS
        and not _is_letter_bucket(source_group)
    ):
        return source_group
    return repair_text(row.get("artist"), "未知歌手")


def _is_partial_download(path: Path) -> bool:
    name = path.name.casefold()
    return any(name.endswith(suffix) for suffix in PARTIAL_DOWNLOAD_SUFFIXES)


def is_generated_work_audio(path: str | Path) -> bool:
    """Identify internal conversion files that must never become library songs."""
    item = Path(path)
    name = item.name.casefold()
    if re.search(r"_[0-9a-f]{8,64}_work\.(?:wav|flac|aiff?|alac)$", name):
        return True
    parts = {part.casefold() for part in item.parts}
    return bool({"working", "converted"} & parts and {"05_temp", "imports"} & parts)


def discover_audio_files(roots: list[Path] | tuple[Path, ...]) -> tuple[list[tuple[Path, Path]], dict]:
    """Walk every configured folder, including Windows junction/reparse directories."""
    found: dict[str, tuple[Path, Path]] = {}
    folder_count = 0
    linked_folders = 0
    ignored_partial = 0
    errors: list[str] = []
    scanned_roots: list[str] = []

    def onerror(error: OSError) -> None:
        if len(errors) < 12:
            errors.append(str(error))

    for raw_root in roots:
        root = Path(raw_root).expanduser()
        scanned_roots.append(str(root))
        if not root.exists():
            errors.append(f"目录不存在：{root}")
            continue
        stack = [root]
        visited: set[tuple | str] = set()
        while stack:
            current_path = stack.pop()
            try:
                current_stat = current_path.stat()
                identity: tuple | str
                if getattr(current_stat, "st_ino", 0):
                    identity = (getattr(current_stat, "st_dev", 0), current_stat.st_ino)
                else:
                    identity = os.path.normcase(os.path.realpath(str(current_path))).casefold()
                if identity in visited:
                    continue
                visited.add(identity)
                with os.scandir(current_path) as stream:
                    entries = list(stream)
            except OSError as error:
                onerror(error)
                continue
            folder_count += 1
            for entry in entries:
                path = current_path / entry.name
                if _is_partial_download(path):
                    ignored_partial += 1
                    continue
                if is_generated_work_audio(path):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=True):
                        stat_result = entry.stat(follow_symlinks=True)
                        if entry.is_symlink() or bool(getattr(stat_result, "st_file_attributes", 0) & 0x400):
                            linked_folders += 1
                        stack.append(path)
                        continue
                    if not entry.is_file(follow_symlinks=True):
                        continue
                except OSError as error:
                    onerror(error)
                    continue
                if path.suffix.casefold() not in AUDIO_EXTENSIONS:
                    continue
                key = os.path.normcase(os.path.abspath(str(path))).casefold()
                found[key] = (path, root)
    rows = sorted(found.values(), key=lambda item: str(item[0]).casefold())
    return rows, {
        "folders": folder_count,
        "linked_folders": linked_folders,
        "ignored_partial": ignored_partial,
        "scan_errors": len(errors),
        "error_samples": errors,
        "roots": scanned_roots,
    }


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


def extract_metadata(path: Path, cover_dir: Path, scan_root: Path | None = None) -> dict:
    stem = repair_text(path.stem, path.stem)
    title = stem
    artist = "未知歌手"
    if " - " in stem:
        left, right = stem.split(" - ", 1)
        artist, title = repair_text(left, "未知歌手"), repair_text(right, stem)
    folder_artist = infer_artist_from_path(path, scan_root)
    data = {
        "title": title,
        "artist": artist if artist != "未知歌手" else folder_artist,
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
    if not data.get("artist") or data["artist"] == "未知歌手":
        data["artist"] = folder_artist
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
    if "05_temp" in value or "链接导入" in value or "临时歌曲库" in value:
        return "临时歌曲库"
    return "本地导入"


def scan_catalog(
    root: Path,
    db_path: Path,
    cover_dir: Path,
    progress: Callable[[int, int, Path], None] | None = None,
) -> dict:
    return scan_catalog_roots([root], db_path, cover_dir, progress)


def scan_catalog_roots(
    roots: list[Path] | tuple[Path, ...],
    db_path: Path,
    cover_dir: Path,
    progress: Callable[[int, int, Path], None] | None = None,
) -> dict:
    files, diagnostics = discover_audio_files(tuple(Path(root) for root in roots))
    connection = connect_catalog(db_path)
    added = updated = skipped = failed = removed_generated = 0
    try:
        for index, (path, scan_root) in enumerate(files, start=1):
            if progress:
                progress(index, len(files), path)
            try:
                stat = path.stat()
                existing = connection.execute(
                    "SELECT id,imported_at,source_group,artist FROM tracks WHERE source_path=?", (str(path),)
                ).fetchone()
                source_group = infer_artist_from_path(path, scan_root)
                if (
                    existing
                    and float(existing["imported_at"] or 0) == float(stat.st_mtime)
                    and str(existing["source_group"] or "").strip() == source_group
                    and str(existing["artist"] or "").strip() not in {"", "未知歌手"}
                ):
                    skipped += 1
                    continue
                fingerprint = quick_fingerprint(path)
                metadata = extract_metadata(path, cover_dir, scan_root)
                connection.execute(
                    """
                    INSERT INTO tracks(
                        fingerprint,source_path,working_path,title,artist,album,year,
                        duration,bitrate,samplerate,channels,format,quality,cover_path,
                        imported_at,category,source_group
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        source_path=excluded.source_path,working_path=excluded.working_path,
                        title=excluded.title,artist=excluded.artist,album=excluded.album,
                        year=excluded.year,duration=excluded.duration,bitrate=excluded.bitrate,
                        samplerate=excluded.samplerate,channels=excluded.channels,
                        format=excluded.format,quality=excluded.quality,
                        cover_path=CASE WHEN excluded.cover_path<>'' THEN excluded.cover_path ELSE tracks.cover_path END,
                        imported_at=excluded.imported_at,category=excluded.category,
                        source_group=excluded.source_group
                    """,
                    (
                        fingerprint, str(path), str(path), metadata["title"], metadata["artist"],
                        metadata["album"], metadata["year"], metadata["duration"],
                        metadata["bitrate"], metadata["samplerate"], metadata["channels"],
                        metadata["format"], metadata["quality"], metadata["cover_path"],
                        float(stat.st_mtime), category_for(path), source_group,
                    ),
                )
                if existing:
                    updated += 1
                else:
                    added += 1
            except Exception:
                failed += 1
        generated_rows = connection.execute("SELECT id,source_path FROM tracks").fetchall()
        for row in generated_rows:
            if is_generated_work_audio(row["source_path"] or ""):
                connection.execute("DELETE FROM tracks WHERE id=?", (row["id"],))
                removed_generated += 1
        connection.commit()
    finally:
        connection.close()
    return {
        "total": len(files), "added": added, "updated": updated,
        "skipped": skipped, "failed": failed, "removed_generated": removed_generated,
        **diagnostics,
    }


def list_catalog(db_path: Path, query: str = "", category: str = "全部", limit: int = 100000) -> list[dict]:
    connection = connect_catalog(db_path)
    try:
        where = []
        values: list[object] = []
        text = query.strip()
        if text:
            where.append("(title LIKE ? OR artist LIKE ? OR album LIKE ? OR source_group LIKE ?)")
            like = f"%{text}%"
            values.extend((like, like, like, like))
        if category and category != "全部":
            where.append("category=?")
            values.append(category)
        clause = " WHERE " + " AND ".join(where) if where else ""
        values.append(max(1, min(100000, int(limit))))
        rows = connection.execute(
            "SELECT * FROM tracks" + clause + " ORDER BY source_group,artist,title LIMIT ?", values
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def list_artists(db_path: Path, query: str = "", category: str = "全部") -> list[dict]:
    connection = connect_catalog(db_path)
    try:
        where = []
        values: list[object] = []
        if query.strip():
            where.append("(title LIKE ? OR artist LIKE ? OR album LIKE ? OR source_group LIKE ?)")
            like = f"%{query.strip()}%"
            values.extend((like, like, like, like))
        if category and category != "全部":
            where.append("category=?")
            values.append(category)
        clause = " WHERE " + " AND ".join(where) if where else ""
        rows = connection.execute(
            "SELECT artist,COUNT(*) AS song_count FROM tracks" + clause
            + " GROUP BY artist ORDER BY artist COLLATE NOCASE",
            values,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def download_public_audio(url: str, destination: str | Path, ffmpeg_path: str = "", progress=None) -> Path:
    """Download a public direct audio URL or a non-DRM share page into 05_Temp."""
    notify = progress or (lambda _value, _text: None)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("请输入有效的 http/https 分享链接")
    suffix = Path(parsed.path).suffix.casefold()
    if suffix in AUDIO_EXTENSIONS:
        source_name = urllib.parse.unquote(Path(parsed.path).name) or "link_audio.mp3"
        target = destination / f"{safe_file_stem(Path(source_name).stem, 'link_audio')}{suffix}"
        part = target.with_suffix(target.suffix + ".part")
        request = urllib.request.Request(url, headers={"User-Agent": "Juweier-Music/3.2.1"})
        with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as stream:
            total, downloaded = int(response.headers.get("Content-Length") or 0), 0
            while True:
                chunk = response.read(1024 * 512)
                if not chunk:
                    break
                stream.write(chunk); downloaded += len(chunk)
                value = int(downloaded * 100 / total) if total else 0
                notify(min(99, value), f"正在下载公开音频 {downloaded / 1048576:.1f} MB")
        os.replace(part, target)
        notify(100, "下载完成，正在加入临时歌曲库")
        return target

    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("当前安装包缺少公开链接解析组件，请更新到完整版 v3.2.1") from exc
    before = {path.resolve() for path in destination.iterdir() if path.is_file()}

    def hook(status: dict) -> None:
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            notify(int(done * 92 / total) if total else 10, f"正在解析并下载公开音频 {done / 1048576:.1f} MB")
        elif status.get("status") == "finished":
            notify(94, "下载完成，正在转换为 MP3")

    options = {
        "format": "bestaudio/best", "noplaylist": True, "quiet": True, "no_warnings": True,
        "outtmpl": str(destination / "%(uploader)s - %(title)s.%(ext)s"),
        "progress_hooks": [hook],
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}],
    }
    if ffmpeg_path:
        ffmpeg = Path(ffmpeg_path)
        options["ffmpeg_location"] = str(ffmpeg.parent if ffmpeg.is_file() else ffmpeg)
    notify(2, "正在识别分享页面")
    with yt_dlp.YoutubeDL(options) as downloader:
        downloader.extract_info(url, download=True)
    candidates = [
        path for path in destination.iterdir()
        if path.is_file() and path.resolve() not in before and path.suffix.casefold() in AUDIO_EXTENSIONS
    ]
    if not candidates:
        raise RuntimeError("平台没有提供可公开下载的音频，或该内容需要登录/会员/DRM 权限")
    target = max(candidates, key=lambda path: path.stat().st_mtime)
    notify(100, "已导入临时歌曲库")
    return target


def catalog_track(db_path: Path, track_id: int) -> dict | None:
    connection = connect_catalog(db_path)
    try:
        row = connection.execute("SELECT * FROM tracks WHERE id=?", (int(track_id),)).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()
