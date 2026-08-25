from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.library_catalog import connect_catalog, default_library_root, ensure_library_layout, bump_catalog_version

STEM_KEYS = (
    "stem_vocals",
    "stem_drums",
    "stem_bass",
    "stem_guitar",
    "stem_electric_guitar",
    "stem_piano",
    "stem_other",
)


def resolve_db() -> Path:
    configured = os.environ.get("JUWEIER_LIBRARY_DB", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    layout = ensure_library_layout(default_library_root())
    return (layout["database"] / "juweier_music_library.sqlite3").resolve()


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError("找不到 FFmpeg，请确认服务器 FFmpeg 已安装") from exc


def resolve_artifact(raw: str, row: dict) -> Path | None:
    value = str(raw or "").strip()
    if not value or value.startswith(("http://", "https://")):
        return None
    if value.startswith("file://"):
        value = value[7:]
    p = Path(value)
    candidates = [p]
    if not p.is_absolute():
        candidates.append(ROOT / p)
        final_audio = str(row.get("final_audio_path") or "").strip()
        if final_audio:
            candidates.append(Path(final_audio).parent / p)
        for root in os.environ.get("JUWEIER_PROCESSED_ROOTS", "").split(";"):
            root = root.strip()
            if root:
                candidates.append(Path(root) / p)
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def encode_mobile(ffmpeg: str, src: Path, dst: Path, bitrate: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_file() and dst.stat().st_size > 4096 and dst.stat().st_mtime >= src.stat().st_mtime:
        return
    tmp = dst.with_suffix(".tmp.m4a")
    if tmp.exists():
        tmp.unlink()
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src), "-vn", "-c:a", "aac", "-b:a", bitrate,
        "-ar", "44100", "-movflags", "+faststart", str(tmp),
    ]
    subprocess.run(cmd, check=True)
    if not tmp.is_file() or tmp.stat().st_size < 4096:
        raise RuntimeError(f"压缩分轨生成失败：{src.name}")
    os.replace(tmp, dst)


def main() -> int:
    bitrate = os.environ.get("JUWEIER_MOBILE_STEM_BITRATE", "160k").strip() or "160k"
    db = resolve_db()
    ffmpeg = ffmpeg_exe()
    connection = connect_catalog(db)
    generated = 0
    skipped = 0
    failed = 0
    changed_tracks = 0
    try:
        rows = connection.execute(
            "SELECT id,title,artist,final_audio_path,artifacts_json,publish_status,processing_status "
            "FROM tracks WHERE publish_status='已发布' AND processing_status='已完成' "
            "AND artifacts_json IS NOT NULL AND artifacts_json<>'' AND artifacts_json<>'{}' ORDER BY id"
        ).fetchall()
        print(f"待检查成品：{len(rows)} 首，AAC 码率：{bitrate}")
        for raw_row in rows:
            row = dict(raw_row)
            track_id = int(row["id"])
            try:
                artifacts = json.loads(str(row.get("artifacts_json") or "{}"))
            except Exception:
                failed += 1
                print(f"[失败] ID {track_id} artifacts_json 无法解析")
                continue
            changed = False
            print(f"\n[{track_id}] {row.get('artist') or ''} - {row.get('title') or ''}")
            for key in STEM_KEYS:
                src = resolve_artifact(str(artifacts.get(key) or ""), row)
                if src is None:
                    skipped += 1
                    print(f"  - {key}: 原 WAV 不存在，跳过")
                    continue
                mobile_key = f"{key}_mobile"
                dst = src.parent / "mobile_streams" / f"{key}.m4a"
                try:
                    before = dst.stat().st_size if dst.exists() else 0
                    encode_mobile(ffmpeg, src, dst, bitrate)
                    artifacts[mobile_key] = str(dst)
                    changed = True
                    generated += 1
                    ratio = (dst.stat().st_size / src.stat().st_size * 100) if src.stat().st_size else 0
                    state = "复用" if before and before == dst.stat().st_size else "生成"
                    print(f"  + {mobile_key}: {state} {dst.stat().st_size/1024/1024:.1f}MB，约为 WAV 的 {ratio:.1f}%")
                except Exception as exc:
                    failed += 1
                    print(f"  ! {mobile_key}: {exc}")
            if changed:
                connection.execute(
                    "UPDATE tracks SET artifacts_json=?, catalog_updated_at=strftime('%s','now') WHERE id=?",
                    (json.dumps(artifacts, ensure_ascii=False), track_id),
                )
                changed_tracks += 1
        if changed_tracks:
            bump_catalog_version(connection)
        connection.commit()
    finally:
        connection.close()
    print(f"\n完成：更新 {changed_tracks} 首，mobile 分轨 {generated} 个，跳过 {skipped}，失败 {failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
