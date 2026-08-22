"""Create an auditable batch manifest and update the server catalog safely."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from pathlib import Path

from app.library_catalog import (
    AUDIO_EXTENSIONS, connect_catalog, ensure_library_layout, scan_catalog_roots,
)
from app.server_batch_rules import build_processing_plan


PILOT_HINTS = ("刘德华\\练习", "张国荣\\01 风继续吹", "郑秀文(1)\\")


def discover(root: Path) -> list[Path]:
    return sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() in AUDIO_EXTENSIONS),
        key=lambda path: str(path).casefold(),
    )


def choose_pilot(plan, limit: int) -> list:
    eligible = [item for item in plan if item.action == "process"]
    selected = []
    for hint in PILOT_HINTS:
        normalized_hint = hint.casefold()
        match = next(
            (item for item in eligible if normalized_hint in item.source_path.replace("/", "\\").casefold()),
            None,
        )
        if match and match not in selected:
            selected.append(match)
    for item in eligible:
        if len(selected) >= limit:
            break
        if item not in selected:
            selected.append(item)
    return selected[:limit]


def write_manifest(folder: Path, plan: list, selected: list) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    json_path = folder / f"batch-preflight-{stamp}.json"
    csv_path = folder / f"batch-preflight-{stamp}.csv"
    selected_paths = {item.source_path for item in selected}
    rows = [
        {**item.as_dict(), "pilot_selected": item.source_path in selected_paths}
        for item in plan
    ]
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["source_path"])
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path


def update_pilot_rows(db_path: Path, plan: list, selected: list) -> None:
    selected_paths = {item.source_path for item in selected}
    connection = connect_catalog(db_path)
    try:
        for order, item in enumerate(selected, start=1):
            connection.execute(
                "UPDATE tracks SET processing_status='待处理',publish_status='待发布',sort_order=? "
                "WHERE source_path=?",
                (order, item.source_path),
            )
        for item in plan:
            if item.action == "process" and item.source_path not in selected_paths:
                connection.execute(
                    "UPDATE tracks SET processing_status='等待批量确认',publish_status='待发布',sort_order=999999 "
                    "WHERE source_path=?",
                    (item.source_path,),
                )
        connection.commit()
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="橘味儿音乐服务器批处理预检")
    parser.add_argument("--source", default=r"D:\MP3")
    parser.add_argument("--data", default=os.environ.get("JUWEIER_DATA_DIR", str(Path.cwd())))
    parser.add_argument("--pilot", type=int, default=3)
    args = parser.parse_args()

    source = Path(args.source)
    data = Path(args.data)
    if not source.is_dir():
        raise SystemExit(f"测试歌曲目录不存在：{source}")
    layout = ensure_library_layout(data)
    db_path = Path(os.environ.get(
        "JUWEIER_LIBRARY_DB", layout["database"] / "juweier_music_library.sqlite3",
    ))
    files = discover(source)
    plan = build_processing_plan(files, source)
    scan_catalog_roots([source], db_path, layout["covers"])
    selected = choose_pilot(plan, max(1, args.pilot))
    update_pilot_rows(db_path, plan, selected)
    json_path, csv_path = write_manifest(data / "manifests", plan, selected)
    counts = {}
    for item in plan:
        counts[item.action] = counts.get(item.action, 0) + 1
    print(json.dumps({
        "source": str(source), "database": str(db_path), "counts": counts,
        "pilot": [item.as_dict() for item in selected],
        "manual_review": [item.as_dict() for item in plan if item.action == "review"],
        "skipped": [item.as_dict() for item in plan if item.action in {"skip", "duplicate"}],
        "manifest_json": str(json_path), "manifest_csv": str(csv_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
