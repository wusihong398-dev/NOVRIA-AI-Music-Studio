"""One-time migration of published products and catalog labels to Simplified Chinese."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

from app.chinese_normalization import (
    simplify_json_value,
    simplify_published_tree,
    to_simplified,
)
from app.library_taxonomy import artist_initial_for
from app.server_batch_rules import candidate_key


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--processed-root", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser


def _json_text(value: object) -> str:
    try:
        payload = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return to_simplified(value)
    return json.dumps(simplify_json_value(payload), ensure_ascii=False)


def migrate(database: Path, processed_root: Path, apply: bool) -> dict:
    ready_root = processed_root / "01_Ready"
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT * FROM tracks WHERE publish_status='已发布' ORDER BY id"
        ).fetchall()
        changes = []
        for row in rows:
            artist = to_simplified(row["artist"] or row["source_group"] or "未知歌手")
            title = to_simplified(row["title"] or "未知歌曲")
            final_audio = to_simplified(row["final_audio_path"] or "")
            artifacts = _json_text(row["artifacts_json"])
            initial, _ = artist_initial_for(
                row["source_path"] or "", artist,
                row["artist_initial"] or "", bool(row["artist_initial_locked"]),
            )
            changes.append({
                "id": int(row["id"]), "artist": artist, "title": title,
                "artist_initial": initial,
            })
            if apply:
                connection.execute(
                    """UPDATE tracks SET title=?,artist=?,source_group=?,artist_initial=?,
                       canonical_key=?,final_audio_path=?,artifacts_json=?,
                       catalog_updated_at=?,catalog_revision=? WHERE id=?""",
                    (
                        title, artist, artist, initial, candidate_key(artist, title),
                        final_audio, artifacts, time.time(), int(time.time() * 1000),
                        int(row["id"]),
                    ),
                )
        if apply:
            simplify_published_tree(ready_root)
            connection.execute(
                "INSERT INTO catalog_meta(key,value) VALUES('catalog_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(int(time.time() * 1000)),),
            )
            connection.commit()
        return {"apply": apply, "published_tracks": len(rows), "changes": changes}
    finally:
        connection.close()


def main() -> int:
    args = _parser().parse_args()
    database = Path(args.database)
    processed_root = Path(args.processed_root)
    if not database.is_file():
        raise SystemExit(f"Database not found: {database}")
    if args.apply:
        backup = database.with_name(
            f"{database.stem}-before-simplified-{time.strftime('%Y%m%d-%H%M%S')}{database.suffix}"
        )
        source_connection = sqlite3.connect(database)
        backup_connection = sqlite3.connect(backup)
        try:
            source_connection.backup(backup_connection)
        finally:
            backup_connection.close()
            source_connection.close()
        print(f"BACKUP={backup}")
    result = migrate(database, processed_root, args.apply)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
