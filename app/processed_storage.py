"""Multi-disk placement policy for published Juweier Music products."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Iterable, NamedTuple


class StorageCapacityError(RuntimeError):
    """No configured product disk can accept another published song safely."""


class DiskUsage(NamedTuple):
    total: int
    used: int
    free: int


def configured_processed_roots(primary: Path, configured: str = "") -> list[Path]:
    values = [Path(value.strip()) for value in configured.split(";") if value.strip()]
    values = values or [Path(primary)]
    result: list[Path] = []
    seen: set[str] = set()
    for value in values:
        key = str(value).rstrip("\\/").casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def storage_snapshot(
    roots: Iterable[Path], *, reserve_ratio: float, reserve_min_bytes: int,
    required_bytes: int = 0,
    usage_provider: Callable[[Path], DiskUsage] = shutil.disk_usage,
) -> list[dict]:
    result = []
    safe_ratio = max(0.0, min(float(reserve_ratio), 0.95))
    required = max(0, int(required_bytes))
    for priority, raw_root in enumerate(roots, start=1):
        root = Path(raw_root)
        item = {
            "root": str(root), "priority": priority, "available": False,
            "eligible": False, "total_bytes": 0, "free_bytes": 0,
            "reserve_bytes": 0, "required_bytes": required, "error": "",
        }
        try:
            root.mkdir(parents=True, exist_ok=True)
            usage = usage_provider(root)
            reserve = max(int(usage.total * safe_ratio), max(0, int(reserve_min_bytes)))
            item.update(
                available=True,
                eligible=int(usage.free) - required >= reserve,
                total_bytes=int(usage.total),
                free_bytes=int(usage.free),
                reserve_bytes=reserve,
            )
        except Exception as exc:
            item["error"] = str(exc)
        result.append(item)
    return result


def select_processed_root(
    roots: Iterable[Path], *, reserve_ratio: float, reserve_min_bytes: int,
    required_bytes: int = 0,
    usage_provider: Callable[[Path], DiskUsage] = shutil.disk_usage,
) -> tuple[Path | None, list[dict]]:
    snapshot = storage_snapshot(
        roots,
        reserve_ratio=reserve_ratio,
        reserve_min_bytes=reserve_min_bytes,
        required_bytes=required_bytes,
        usage_provider=usage_provider,
    )
    selected = next((item for item in snapshot if item["eligible"]), None)
    return (Path(str(selected["root"])) if selected else None), snapshot


def capacity_message(snapshot: list[dict]) -> str:
    details = []
    for item in snapshot:
        if not item.get("available"):
            details.append(f"{item['root']} 不可用")
            continue
        free_gb = int(item["free_bytes"]) / 1024 ** 3
        reserve_gb = int(item["reserve_bytes"]) / 1024 ** 3
        details.append(f"{item['root']} 剩余 {free_gb:.1f} GB（保留线 {reserve_gb:.1f} GB）")
    return "G/F 成品盘均已达到安全保留线，批处理已自动暂停；" + "；".join(details)
