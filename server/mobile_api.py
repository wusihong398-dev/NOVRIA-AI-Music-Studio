"""Mobile API companion for 橘味儿音乐 v3.4.1 multi-disk product catalog.

Run this on the Windows/GPU computer. The server prepares and publishes songs;
Android, iOS and Windows clients consume only validated finished products.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import html
import importlib.util
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.project_utils import (
    align_lyric_units_to_notes,
    atomic_write_json,
    expand_lyric_units,
    safe_file_stem,
    load_synced_lyrics,
)
from app.lyrics_ai import generate_lyrics, lyrics_to_lrc
from app.lyrics_transcription import transcribe_synced_lyrics
from app.library_catalog import (
    catalog_artist_name,
    catalog_facets,
    catalog_track,
    catalog_version,
    bump_catalog_version,
    connect_catalog,
    default_library_root,
    ensure_library_layout,
    list_catalog,
    scan_catalog,
    scan_catalog_roots,
    download_public_audio,
)
from app.library_taxonomy import artist_initial_for, taxonomy_payload
from app.server_batch_rules import finished_song_dir
from app.processed_storage import (
    StorageCapacityError,
    capacity_message,
    configured_processed_roots,
    select_processed_root,
    storage_snapshot,
)
from app.chinese_normalization import (
    simplified_relative_path,
    simplify_published_tree,
    to_simplified,
)


APP_NAME = "橘味儿音乐"
VERSION = "3.4.1"
ROOT = Path(os.environ.get("JUWEIER_DATA_DIR", Path.cwd() / "mobile_server_data")).resolve()
UPLOADS = ROOT / "uploads"
OUTPUTS = ROOT / "outputs"
STATE_FILE = ROOT / "jobs.json"
BATCH_STATE_FILE = ROOT / "library_batch_state.json"
ACCOUNT_DB = ROOT / "accounts.sqlite3"
TOKEN = os.environ.get("JUWEIER_API_TOKEN", "").strip()
SMS_ACCESS_KEY_ID = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip()
SMS_ACCESS_KEY_SECRET = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip()
SMS_SIGN_NAME = os.environ.get("ALIYUN_SMS_SIGN_NAME", "").strip()
SMS_TEMPLATE_CODE = os.environ.get("ALIYUN_SMS_TEMPLATE_CODE", "").strip()
SMS_CODE_PEPPER = os.environ.get("ADMIN_KEY", "").strip()
LIBRARY_PATHS = ensure_library_layout(default_library_root())
if os.environ.get("JUWEIER_PROCESSED_DIR", "").strip():
    LIBRARY_PATHS["processed"] = Path(os.environ["JUWEIER_PROCESSED_DIR"].strip())
    LIBRARY_PATHS["processed"].mkdir(parents=True, exist_ok=True)
PROCESSED_ROOTS = configured_processed_roots(
    Path(LIBRARY_PATHS["processed"]),
    os.environ.get("JUWEIER_PROCESSED_ROOTS", ""),
)
LIBRARY_PATHS["processed"] = PROCESSED_ROOTS[0]
PROCESSED_RESERVE_RATIO = max(
    0.0, min(float(os.environ.get("JUWEIER_MIN_FREE_RATIO", "0.15")), 0.95)
)
PROCESSED_RESERVE_MIN_BYTES = max(
    0, int(float(os.environ.get("JUWEIER_MIN_FREE_GB", "30")) * 1024 ** 3)
)
PROCESSED_SONG_HEADROOM_BYTES = max(
    0, int(float(os.environ.get("JUWEIER_PUBLISH_HEADROOM_GB", "3")) * 1024 ** 3)
)
LIBRARY_DB = Path(os.environ.get(
    "JUWEIER_LIBRARY_DB",
    LIBRARY_PATHS["database"] / "juweier_music_library.sqlite3",
))
SERVER_LIBRARY_ROOT = Path(os.environ.get(
    "JUWEIER_SERVER_LIBRARY",
    r"G:\JuweierMusicLibrary\01_Originals",
))
SERVER_LIBRARY_FLAC_ROOT = Path(os.environ.get(
    "JUWEIER_SERVER_LIBRARY_FLAC",
    r"G:\JuweierMusicLibrary\01_Originals",
))
_configured_roots = [
    Path(value.strip())
    for value in os.environ.get("JUWEIER_SERVER_LIBRARY_ROOTS", "").split(";")
    if value.strip()
]
SERVER_LIBRARY_ROOTS = list(dict.fromkeys(
    _configured_roots or (SERVER_LIBRARY_ROOT, SERVER_LIBRARY_FLAC_ROOT)
))
AUTO_SCAN_LIBRARY = os.environ.get("JUWEIER_AUTO_SCAN_LIBRARY", "0").strip().lower() not in {
    "0", "false", "no", "off",
}
CATALOG_WATCH_INTERVAL = max(60, int(os.environ.get("JUWEIER_CATALOG_WATCH_INTERVAL", "900")))
connect_catalog(LIBRARY_DB).close()
for folder in (UPLOADS, OUTPUTS):
    folder.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=f"{APP_NAME} Mobile API", version=VERSION)
lock = threading.RLock()
executor = ThreadPoolExecutor(max_workers=max(2, int(os.environ.get("JUWEIER_WORKERS", "2"))))
catalog_state = {
    "status": "cached",
    "message": "正在使用服务器已保存的歌曲索引",
    "updated_at": 0.0,
    "result": {},
}
catalog_scan_lock = threading.Lock()
batch_lock = threading.RLock()
batch_thread: threading.Thread | None = None
batch_state = {
    "running": False, "paused": False, "current_track_id": 0,
    "current_job_id": "", "submitted": 0, "completed": 0, "failed": 0,
    "limit": 0, "pause_reason": "", "updated_at": 0.0,
}


class AuthPayload(BaseModel):
    username: str = Field(default="", max_length=32)
    phone: str = Field(default="", max_length=24)
    code: str = Field(default="", max_length=8)
    password: str = Field(min_length=6, max_length=128)
    nickname: str = Field(default="", max_length=32)


class SmsCodePayload(BaseModel):
    phone: str = Field(min_length=6, max_length=24)
    purpose: str = Field(default="register", max_length=16)


class PasswordResetPayload(BaseModel):
    phone: str = Field(min_length=6, max_length=24)
    code: str = Field(min_length=4, max_length=8)
    new_password: str = Field(min_length=6, max_length=128)


class ProfilePayload(BaseModel):
    avatar_url: str = Field(default="", max_length=1024)
    nickname: str = Field(default="", max_length=32)
    gender: str = Field(default="保密", max_length=8)
    bio: str = Field(default="", max_length=300)
    origin: str = Field(default="", max_length=80)
    address: str = Field(default="", max_length=160)
    wechat: str = Field(default="", max_length=80)


class ChatPayload(BaseModel):
    content: str = Field(min_length=1, max_length=500)


def _normalize_arrangement_mode(value: str) -> str:
    normalized = (value or "").strip()
    return {"live_band": "乐队现场版", "studio": "录音室版"}.get(normalized.lower(), normalized or "乐队现场版")


class LibraryProcessPayload(BaseModel):
    arrangement_mode: str = "乐队现场版"
    transpose: int = Field(default=0, ge=-12, le=12)
    output: str = "wav_mp3"


class LinkImportPayload(BaseModel):
    url: str = Field(min_length=8, max_length=4096)


class LyricsGeneratePayload(BaseModel):
    theme: str = Field(min_length=1, max_length=80)
    language: str = Field(default="普通话", max_length=16)
    style: str = Field(default="流行", max_length=24)
    mood: str = Field(default="温暖", max_length=24)
    variants: int = Field(default=1, ge=1, le=3)
    bpm: float = Field(default=72.0, ge=40.0, le=240.0)


class FeedbackPayload(BaseModel):
    category: str = Field(default="功能建议", max_length=32)
    content: str = Field(min_length=2, max_length=2000)
    contact: str = Field(default="", max_length=120)
    device: str = Field(default="", max_length=200)
    app_version: str = Field(default=VERSION, max_length=32)


def _db() -> sqlite3.Connection:
    connection = sqlite3.connect(ACCOUNT_DB, timeout=20)
    connection.row_factory = sqlite3.Row
    return connection


def _init_accounts() -> None:
    connection = _db()
    try:
        connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                nickname TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS verification_codes (
                phone TEXT NOT NULL,
                purpose TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                expires_at REAL NOT NULL,
                last_sent_at REAL NOT NULL,
                consumed_at REAL,
                attempts INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(phone, purpose)
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS community_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_community_messages_created
            ON community_messages(created_at DESC);
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                contact TEXT NOT NULL DEFAULT '',
                device TEXT NOT NULL DEFAULT '',
                app_version TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '待处理',
                created_at REAL NOT NULL
            );
            """
        )
        existing_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        profile_columns = {
            "phone": "TEXT",
            "avatar_url": "TEXT NOT NULL DEFAULT ''",
            "gender": "TEXT NOT NULL DEFAULT '保密'",
            "bio": "TEXT NOT NULL DEFAULT ''",
            "origin": "TEXT NOT NULL DEFAULT ''",
            "address": "TEXT NOT NULL DEFAULT ''",
            "wechat": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "REAL NOT NULL DEFAULT 0",
        }
        for column, definition in profile_columns.items():
            if column not in existing_columns:
                connection.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone_unique "
            "ON users(phone) WHERE phone IS NOT NULL AND phone<>''"
        )
        connection.commit()
    finally:
        connection.close()


def _password_hash(password: str, salt_hex: str | None = None) -> str:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return f"{salt.hex()}:{digest.hex()}"


def _password_matches(password: str, stored: str) -> bool:
    try:
        salt_hex, expected = stored.split(":", 1)
        actual = _password_hash(password, salt_hex).split(":", 1)[1]
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _normalize_phone(value: str) -> str:
    phone = re.sub(r"[\s\-()]", "", value or "")
    if phone.startswith("+86"):
        phone = phone[3:]
    elif phone.startswith("0086"):
        phone = phone[4:]
    if not re.fullmatch(r"1[3-9]\d{9}", phone):
        raise HTTPException(status_code=400, detail="请输入正确的中国大陆手机号")
    return phone


def _verification_hash(phone: str, purpose: str, code: str) -> str:
    pepper = SMS_CODE_PEPPER or TOKEN
    if not pepper:
        raise HTTPException(status_code=503, detail="短信验证码服务尚未配置")
    return hmac.new(
        pepper.encode("utf-8"), f"{phone}:{purpose}:{code}".encode("utf-8"), hashlib.sha256,
    ).hexdigest()


def _verify_sms_code(
    connection: sqlite3.Connection, phone: str, purpose: str, code: str, *, consume: bool = True,
) -> None:
    row = connection.execute(
        "SELECT code_hash,expires_at,consumed_at,attempts FROM verification_codes "
        "WHERE phone=? AND purpose=?",
        (phone, purpose),
    ).fetchone()
    if not row or row["consumed_at"] is not None:
        raise HTTPException(status_code=400, detail="请先获取短信验证码")
    if float(row["expires_at"]) < time.time():
        raise HTTPException(status_code=400, detail="验证码已过期，请重新获取")
    if int(row["attempts"]) >= 5:
        raise HTTPException(status_code=429, detail="验证码错误次数过多，请重新获取")
    actual = _verification_hash(phone, purpose, code.strip())
    if not hmac.compare_digest(actual, str(row["code_hash"])):
        connection.execute(
            "UPDATE verification_codes SET attempts=attempts+1 WHERE phone=? AND purpose=?",
            (phone, purpose),
        )
        connection.commit()
        raise HTTPException(status_code=400, detail="验证码错误")
    if consume:
        connection.execute(
            "UPDATE verification_codes SET consumed_at=? WHERE phone=? AND purpose=?",
            (time.time(), phone, purpose),
        )


def _send_sms(phone: str, code: str) -> None:
    if not all((SMS_ACCESS_KEY_ID, SMS_ACCESS_KEY_SECRET, SMS_SIGN_NAME, SMS_TEMPLATE_CODE, SMS_CODE_PEPPER)):
        raise HTTPException(status_code=503, detail="短信验证码服务尚未完整配置")
    try:
        from alibabacloud_dysmsapi20170525.client import Client as SmsClient
        from alibabacloud_dysmsapi20170525.models import SendSmsRequest
        from alibabacloud_tea_openapi.models import Config
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="服务器尚未安装阿里云短信 SDK") from exc
    try:
        config = Config(access_key_id=SMS_ACCESS_KEY_ID, access_key_secret=SMS_ACCESS_KEY_SECRET)
        config.endpoint = "dysmsapi.aliyuncs.com"
        response = SmsClient(config).send_sms(SendSmsRequest(
            phone_numbers=phone,
            sign_name=SMS_SIGN_NAME,
            template_code=SMS_TEMPLATE_CODE,
            template_param=json.dumps({"code": code}, ensure_ascii=False),
        ))
        body = response.body
        if str(getattr(body, "code", "")) != "OK":
            raise RuntimeError(str(getattr(body, "message", "短信平台发送失败")))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"短信发送失败：{exc}") from exc


def _new_session(connection: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    connection.execute(
        "INSERT INTO sessions(token,user_id,expires_at,created_at) VALUES(?,?,?,?)",
        (token, user_id, now + 30 * 24 * 3600, now),
    )
    connection.execute("DELETE FROM sessions WHERE expires_at<?", (now,))
    return token


def _session_user(authorization: str | None) -> sqlite3.Row | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    value = authorization[7:].strip()
    if not value or (TOKEN and hmac.compare_digest(value, TOKEN)):
        return None
    connection = _db()
    try:
        return connection.execute(
            """SELECT users.id,users.username,users.nickname,users.phone,users.avatar_url,
                      users.gender,users.bio,users.origin,users.address,users.wechat
               FROM sessions JOIN users ON users.id=sessions.user_id
               WHERE sessions.token=? AND sessions.expires_at>?""",
            (value, time.time()),
        ).fetchone()
    finally:
        connection.close()


_init_accounts()


def _load_jobs() -> dict[str, dict]:
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        for job in data.values():
            if job.get("status") in {"queued", "processing", "uploading"}:
                job["status"] = "failed"
                job["error"] = "服务器上次运行中断，请重新提交任务。"
        return data
    except Exception:
        return {}


jobs: dict[str, dict] = _load_jobs()


def _save_jobs() -> None:
    with lock:
        atomic_write_json(STATE_FILE, jobs)


def _update(job_id: str, **values) -> None:
    with lock:
        jobs[job_id].update(values)
        jobs[job_id]["updated_at"] = time.time()
        atomic_write_json(STATE_FILE, jobs)


def authorize(authorization: str | None = Header(default=None)) -> str:
    if authorization and authorization.startswith("Bearer "):
        value = authorization[7:].strip()
        if TOKEN and hmac.compare_digest(value, TOKEN):
            return "server"
        user = _session_user(authorization)
        if user:
            return str(user["username"])
    if not TOKEN:
        return "anonymous"
    raise HTTPException(status_code=401, detail="无效的访问令牌")


def current_user(authorization: str | None = Header(default=None)) -> sqlite3.Row:
    user = _session_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录橘味儿音乐账号")
    return user


def _catalog_count() -> int:
    connection = connect_catalog(LIBRARY_DB)
    try:
        row = connection.execute("SELECT COUNT(*) FROM tracks").fetchone()
        return int(row[0] if row else 0)
    finally:
        connection.close()


def _existing_server_library_roots() -> list[Path]:
    return [root for root in SERVER_LIBRARY_ROOTS if root.is_dir()]


def _artist_initial(artist: str, source_path: str = "") -> str:
    name = str(artist or "").strip()
    if name:
        first = name[0].upper()
        if "A" <= first <= "Z":
            return first
    for part in Path(source_path or ".").parts:
        match = re.match(r"^\s*([A-Za-z])(?:\s|[._-])*(?:字母|开头|歌手|歌曲|分类)", str(part))
        if match:
            return match.group(1).upper()
    try:
        from pypinyin import Style, lazy_pinyin

        values = lazy_pinyin(name, style=Style.FIRST_LETTER, errors="ignore")
        if values and values[0] and values[0][0].isalpha():
            return values[0][0].upper()
    except Exception:
        pass
    return "#"


def _scan_server_catalog() -> dict:
    with catalog_scan_lock:
        roots = _existing_server_library_roots()
        if not roots:
            raise RuntimeError(
                "服务器曲库目录不存在或不可访问：" + "；".join(str(root) for root in SERVER_LIBRARY_ROOTS)
            )
        with lock:
            catalog_state.update(status="scanning", message="服务器正在后台增量同步原版歌曲")
        result = scan_catalog_roots(roots, LIBRARY_DB, LIBRARY_PATHS["covers"])
        with lock:
            catalog_state.update(
                status="ready",
                message="服务器歌曲索引已更新",
                updated_at=time.time(),
                result=dict(result),
            )
        return {**result, "roots": [str(root) for root in roots], "source_scope": "server"}


def _background_catalog_scan() -> None:
    try:
        _scan_server_catalog()
    except Exception as exc:
        with lock:
            catalog_state.update(status="error", message=str(exc), updated_at=time.time())


def _catalog_watch_loop() -> None:
    while True:
        time.sleep(CATALOG_WATCH_INTERVAL)
        _background_catalog_scan()


def _batch_counts() -> dict:
    connection = connect_catalog(LIBRARY_DB)
    try:
        rows = connection.execute(
            "SELECT processing_status,COUNT(*) FROM tracks GROUP BY processing_status"
        ).fetchall()
        counts = {str(row[0] or "待处理"): int(row[1]) for row in rows}
        return {
            "total": sum(counts.values()),
            "pending": counts.get("待处理", 0),
            "queued": counts.get("排队中", 0) + counts.get("处理中", 0),
            "ready": counts.get("已完成", 0),
            "failed": counts.get("失败", 0) + counts.get("成果待校验", 0),
        }
    finally:
        connection.close()


def _set_track_processing_status(track_id: int, status: str) -> None:
    connection = connect_catalog(LIBRARY_DB)
    try:
        revision = max(int(time.time() * 1000), catalog_version(connection) + 1)
        connection.execute(
            "UPDATE tracks SET processing_status=?,catalog_updated_at=?,catalog_revision=? WHERE id=?",
            (status, time.time(), revision, int(track_id)),
        )
        bump_catalog_version(connection, revision)
        connection.commit()
    finally:
        connection.close()


def _save_batch_state() -> None:
    atomic_write_json(BATCH_STATE_FILE, {**batch_state, "counts": _batch_counts()})


def _processed_storage_status(required_bytes: int = 0) -> tuple[Path | None, list[dict]]:
    return select_processed_root(
        PROCESSED_ROOTS,
        reserve_ratio=PROCESSED_RESERVE_RATIO,
        reserve_min_bytes=PROCESSED_RESERVE_MIN_BYTES,
        required_bytes=max(int(required_bytes), PROCESSED_SONG_HEADROOM_BYTES),
    )


def _pause_batch_for_storage(snapshot: list[dict]) -> str:
    reason = capacity_message(snapshot)
    with batch_lock:
        batch_state.update(
            running=False, paused=True, current_track_id=0, current_job_id="",
            pause_reason=reason, updated_at=time.time(),
        )
        _save_batch_state()
    return reason


def _library_batch_loop() -> None:
    global batch_thread
    while True:
        with batch_lock:
            if not batch_state["running"] or batch_state["paused"]:
                break
            limit = int(batch_state.get("limit") or 0)
            if limit > 0 and int(batch_state["submitted"]) >= limit:
                batch_state.update(
                    running=False, current_track_id=0, current_job_id="",
                    updated_at=time.time(),
                )
                _save_batch_state()
                break
        connection = connect_catalog(LIBRARY_DB)
        try:
            row = connection.execute(
                "SELECT id,source_path,working_path FROM tracks "
                "WHERE publish_status='待发布' AND processing_status='待处理' "
                "ORDER BY is_featured DESC,sort_order,id LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        if not row:
            with batch_lock:
                batch_state.update(running=False, current_track_id=0, current_job_id="", updated_at=time.time())
                _save_batch_state()
            break
        _, storage = _processed_storage_status()
        if not any(item.get("eligible") for item in storage):
            _pause_batch_for_storage(storage)
            break
        track_id = int(row["id"])
        _set_track_processing_status(track_id, "排队中")
        input_path = Path(str(row["working_path"] or row["source_path"] or ""))
        if not input_path.is_file():
            _set_track_processing_status(track_id, "失败")
            with batch_lock:
                batch_state["failed"] += 1
            continue
        job_id = _queue_job(
            file_name=input_path.name, input_path=input_path,
            arrangement_mode="乐队现场版", transpose=0, output="wav_mp3",
            library_track_id=track_id,
        )
        with batch_lock:
            batch_state.update(
                current_track_id=track_id, current_job_id=job_id,
                submitted=int(batch_state["submitted"]) + 1, updated_at=time.time(),
            )
            _save_batch_state()
        while True:
            time.sleep(2)
            with lock:
                status = str(jobs.get(job_id, {}).get("status") or "")
            if status in {"completed", "failed", "paused"}:
                with batch_lock:
                    if status in {"completed", "failed"}:
                        key = "completed" if status == "completed" else "failed"
                        batch_state[key] = int(batch_state[key]) + 1
                    batch_state.update(current_track_id=0, current_job_id="", updated_at=time.time())
                    _save_batch_state()
                break
    with batch_lock:
        batch_thread = None


@app.on_event("startup")
def start_catalog_index() -> None:
    """Serve the cached index immediately and refresh it without blocking startup."""

    if AUTO_SCAN_LIBRARY:
        executor.submit(_background_catalog_scan)
        watcher = threading.Thread(target=_catalog_watch_loop, name="catalog-watch", daemon=True)
        watcher.start()
    connection = connect_catalog(LIBRARY_DB)
    try:
        connection.execute(
            "UPDATE tracks SET processing_status='待处理' "
            "WHERE processing_status IN ('排队中','处理中')"
        )
        connection.commit()
    finally:
        connection.close()


def _gpu_name() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return torch.cuda.get_device_name(0)
        return "CPU"
    except Exception:
        return "未检测到 PyTorch"


def _runtime_capabilities() -> dict:
    modules = {
        "torch": importlib.util.find_spec("torch") is not None,
        "demucs": importlib.util.find_spec("demucs") is not None,
        "audio_separator": importlib.util.find_spec("audio_separator") is not None,
        "bs_roformer": importlib.util.find_spec("bs_roformer") is not None,
        "librosa": importlib.util.find_spec("librosa") is not None,
        "mido": importlib.util.find_spec("mido") is not None,
        "opencc": importlib.util.find_spec("opencc") is not None,
    }
    ffmpeg = shutil.which("ffmpeg") is not None
    required_modules = ("torch", "demucs", "librosa", "mido", "opencc")
    missing = [name for name in required_modules if not modules[name]]
    if not ffmpeg:
        missing.append("ffmpeg")
    lyrics_asr = importlib.util.find_spec("faster_whisper") is not None
    electric_model = os.environ.get("JUWEIER_ELECTRIC_GUITAR_MODEL", "").strip()
    electric_engine = os.environ.get("JUWEIER_ELECTRIC_GUITAR_ENGINE", "audio-separator").strip().casefold()
    low_vram_verified = False
    issues = []
    if missing:
        issues.append("AI 处理环境缺少：" + "、".join(missing))
    if electric_engine == "mvsep-mega53":
        if not modules["bs_roformer"]:
            missing.append("bs_roformer")
            issues.append("MVSep Mega 53-Stems 运行器未安装")
        model_dir = Path(os.environ.get(
            "JUWEIER_BS_ROFORMER_MODEL_DIR", ROOT / "models" / "bs-roformer",
        ))
        checkpoint = Path(os.environ.get(
            "JUWEIER_BS_ROFORMER_MODEL_PATH",
            model_dir / "mvsep_mega_model_bs_roformer_53_stems_v1.ckpt",
        ))
        config = Path(os.environ.get(
            "JUWEIER_BS_ROFORMER_CONFIG_PATH",
            model_dir / "mvsep_mega_model_bs_roformer_53_stems.yaml",
        ))
        marker = model_dir / "mvsep-mega53-ready.json"
        runner_marker = model_dir / "bs-roformer-mega53-runner-ready.json"
        tail_marker = model_dir / "bs-roformer-tail-chunk-v337-ready.json"
        low_vram_marker = model_dir / "bs-roformer-low-vram-v338-ready.json"
        if not checkpoint.is_file() or checkpoint.stat().st_size != 1_368_919_887:
            missing.append("mvsep-mega53-checkpoint")
            issues.append("MVSep Mega 53-Stems 官方权重缺失或不完整")
        if not config.is_file() or config.stat().st_size != 4_184:
            missing.append("mvsep-mega53-config")
            issues.append("MVSep Mega 53-Stems 官方配置缺失或不完整")
        marker_verified = False
        if marker.is_file():
            try:
                marker_payload = json.loads(marker.read_text(encoding="utf-8"))
                marker_verified = (
                    marker_payload.get("verified") is True
                    and marker_payload.get("model") == electric_model
                    and marker_payload.get("checkpoint", {}).get("sha256")
                    == "c62820893bbf86d4e734f966bd142d9157cfc8bb8e79e9d8f9ea553f3ff3519f"
                    and marker_payload.get("config", {}).get("sha256")
                    == "7e198062a251587088adb91215a4f44ab59e67bd62fcc805cf54d6e7dfc51103"
                )
            except (OSError, json.JSONDecodeError):
                marker_verified = False
        if not marker_verified:
            missing.append("mvsep-mega53-verification")
            issues.append("MVSep Mega 53-Stems 尚未通过 SHA-256 校验，旧就绪标记已拒绝")
        runner_verified = False
        if runner_marker.is_file():
            try:
                runner_payload = json.loads(runner_marker.read_text(encoding="utf-8"))
                runner_verified = (
                    runner_payload.get("verified") is True
                    and runner_payload.get("model") == electric_model
                    and runner_payload.get("pinned_source_commit")
                    == "b0f1386fcced25f559f3e61c9f08a73cd9bddf80"
                    and runner_payload.get("registry_category") == "mega-stem"
                    and runner_payload.get("mlp_expansion_factor_probe") == [8, 4]
                    and set(runner_payload.get("outputs", []))
                    == {"acoustic-guitar", "electric-guitar"}
                )
            except (OSError, json.JSONDecodeError, TypeError):
                runner_verified = False
        if not runner_verified:
            missing.append("bs-roformer-mega53-runner")
            issues.append(
                "BS-RoFormer 运行器过旧或未通过 Mega53 架构探针；"
                "请运行 Install-BS-RoFormer-Mega53-v336.cmd"
            )
        tail_verified = False
        if tail_marker.is_file():
            try:
                tail_payload = json.loads(tail_marker.read_text(encoding="utf-8"))
                tail_verified = (
                    tail_payload.get("verified") is True
                    and tail_payload.get("patch_version") == "juweier-tail-chunk-v337"
                    and tail_payload.get("observed_input_samples") == 882000
                    and tail_payload.get("observed_output_samples") == 881664
                    and tail_payload.get("strategy")
                    == "crop-overlap-add-to-usable-length"
                )
            except (OSError, json.JSONDecodeError, TypeError):
                tail_verified = False
        if not tail_verified:
            missing.append("bs-roformer-tail-chunk-v337")
            issues.append(
                "BS-RoFormer Mega53 尾块长度修复未安装；"
                "请运行 Install-BS-RoFormer-Tail-Fix-v337.cmd"
            )
        low_vram_verified = False
        if low_vram_marker.is_file():
            try:
                low_vram_payload = json.loads(low_vram_marker.read_text(encoding="utf-8"))
                low_vram_verified = (
                    low_vram_payload.get("verified") is True
                    and low_vram_payload.get("patch_version")
                    == "juweier-low-vram-v338"
                    and low_vram_payload.get("gpu_resident")
                    == "model-and-active-chunk-only"
                    and low_vram_payload.get("accumulator_device") == "cpu"
                    and low_vram_payload.get("cpu_fallback") is False
                )
            except (OSError, json.JSONDecodeError, TypeError):
                low_vram_verified = False
        if not low_vram_verified:
            missing.append("bs-roformer-low-vram-v338")
            issues.append(
                "RTX 3060 低显存 CUDA 修复未安装；"
                "请运行 Install-BS-RoFormer-Low-VRAM-v338.cmd"
            )
    elif not modules["audio_separator"]:
        missing.append("audio_separator")
        issues.append("UVR 包装器不可用，无法运行真实电吉他二阶段模型")
    if not electric_model:
        missing.append("electric-guitar-uvr-model")
        issues.append("尚未配置真实电吉他 UVR 二阶段模型")
    if not lyrics_asr:
        issues.append("AI 歌词转写模型未安装：faster-whisper")
    return {
        "processing_ready": not missing,
        "lyrics_asr_available": lyrics_asr,
        "modules": modules,
        "ffmpeg": ffmpeg,
        "electric_guitar_model": electric_model,
        "electric_guitar_engine": electric_engine,
        "low_vram_cuda": low_vram_verified,
        "cpu_fallback": False if electric_engine == "mvsep-mega53" else None,
        "issues": issues,
    }


def _require_processing_runtime() -> None:
    capabilities = _runtime_capabilities()
    if capabilities["processing_ready"]:
        return
    issue = capabilities["issues"][0]
    raise RuntimeError(
        f"{issue}。请在服务器项目目录使用完整环境安装 requirements-server.txt，"
        "再重启橘味儿音乐 Mobile API。"
    )


def _friendly_job_error(exc: Exception) -> str:
    text = str(exc).strip()
    lowered = text.lower()
    if "no module named 'torch'" in lowered:
        return "AI 处理环境未安装 PyTorch（torch），请安装 requirements-server.txt 后重启服务器。"
    if "no module named 'demucs'" in lowered:
        return "AI 六轨分离模型未安装（demucs），请安装 requirements-server.txt 后重启服务器。"
    if "电吉他 uvr" in lowered or "electric guitar" in lowered or "electric-guitar" in lowered:
        return text
    if "audio_separator" in lowered or "audio-separator" in lowered:
        return "UVR 分轨运行环境未安装（audio-separator），请重新运行 Install-AI-Engine.bat 后重启服务器。"
    if "ffmpeg" in lowered and ("not found" in lowered or "找不到" in text):
        return "服务器未安装或未配置 FFmpeg，暂时无法读取和处理音频。"
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


@app.get("/health")
@app.get("/api/health")
@app.get("/api/v1/library/health")
@app.get("/api/v1/library/mobile/health")
def health(_: None = Depends(authorize)) -> dict:
    capabilities = _runtime_capabilities()
    product_storage = storage_snapshot(
        PROCESSED_ROOTS,
        reserve_ratio=PROCESSED_RESERVE_RATIO,
        reserve_min_bytes=PROCESSED_RESERVE_MIN_BYTES,
    )
    return {
        "status": "healthy", "app": APP_NAME, "version": VERSION, "gpu": _gpu_name(),
        "server_library_root": str(SERVER_LIBRARY_ROOTS[0]),
        "server_library_roots": [str(root) for root in SERVER_LIBRARY_ROOTS],
        "processed_library_roots": [str(root) for root in PROCESSED_ROOTS],
        "processed_storage": product_storage,
        "catalog_count": _catalog_count(),
        "catalog_version": catalog_version(LIBRARY_DB),
        "catalog_stats": catalog_facets(LIBRARY_DB),
        "catalog_state": dict(catalog_state),
        "processing_ready": capabilities["processing_ready"],
        "runtime": capabilities,
        "lyrics_asr_available": capabilities["lyrics_asr_available"],
        "lyrics_asr_model": os.environ.get("JUWEIER_LYRICS_MODEL", "large-v3-turbo"),
    }


@app.get("/api/v1/app/config")
@app.get("/api/v1/library/mobile/app/config")
def app_config(_: None = Depends(authorize)) -> dict:
    capabilities = _runtime_capabilities()
    return {
        "app": APP_NAME, "version": VERSION, "minimum_mobile_version": "3.4.0",
        "service": "online",
        "processing_ready": capabilities["processing_ready"],
        "lyrics_asr_available": capabilities["lyrics_asr_available"],
        "runtime_issues": capabilities["issues"],
        "notice": "本软件目前仅供学习与研究使用，不提供歌曲下载服务。",
    }


@app.post("/api/v1/lyrics/generate")
@app.post("/api/v1/library/mobile/lyrics/generate")
def lyrics_generate(payload: LyricsGeneratePayload, _: None = Depends(authorize)) -> dict:
    variants = generate_lyrics(payload.theme, payload.language, payload.style, payload.mood, payload.variants)
    for item in variants:
        item["lrc"] = lyrics_to_lrc(item["lyrics"], payload.bpm)
    return {"variants": variants, "disclaimer": "AI 生成内容仅作创作初稿，请人工复核。"}


@app.post("/api/v1/feedback", status_code=201)
@app.post("/api/v1/library/mobile/feedback", status_code=201)
def submit_feedback(payload: FeedbackPayload, authorization: str | None = Header(default=None)) -> dict:
    user = _session_user(authorization)
    connection = _db()
    try:
        cursor = connection.execute(
            """INSERT INTO feedback(user_id,category,content,contact,device,app_version,status,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (int(user["id"]) if user else None, payload.category, payload.content,
             payload.contact, payload.device, payload.app_version, "待处理", time.time()),
        )
        connection.commit()
        return {"ok": True, "id": cursor.lastrowid, "message": "反馈已提交"}
    finally:
        connection.close()


@app.post("/api/v1/auth/sms/send", status_code=202)
@app.post("/api/v1/library/mobile/auth/sms/send", status_code=202)
def send_verification_code(payload: SmsCodePayload) -> dict:
    purpose = payload.purpose.strip().lower()
    if purpose not in {"register", "reset"}:
        raise HTTPException(status_code=400, detail="不支持的验证码用途")
    phone = _normalize_phone(payload.phone)
    now = time.time()
    connection = _db()
    try:
        row = connection.execute(
            "SELECT last_sent_at FROM verification_codes WHERE phone=? AND purpose=?",
            (phone, purpose),
        ).fetchone()
        if row:
            wait = 60 - int(now - float(row["last_sent_at"]))
            if wait > 0:
                raise HTTPException(status_code=429, detail=f"请 {wait} 秒后再获取验证码")
        if purpose == "register" and connection.execute(
            "SELECT 1 FROM users WHERE phone=?", (phone,),
        ).fetchone():
            raise HTTPException(status_code=409, detail="该手机号已经注册")
        if purpose == "reset" and not connection.execute(
            "SELECT 1 FROM users WHERE phone=?", (phone,),
        ).fetchone():
            raise HTTPException(status_code=404, detail="该手机号尚未注册")
    finally:
        connection.close()
    code = f"{secrets.randbelow(1_000_000):06d}"
    _send_sms(phone, code)
    connection = _db()
    try:
        connection.execute(
            """INSERT INTO verification_codes(phone,purpose,code_hash,expires_at,last_sent_at,consumed_at,attempts)
               VALUES(?,?,?,?,?,NULL,0)
               ON CONFLICT(phone,purpose) DO UPDATE SET code_hash=excluded.code_hash,
               expires_at=excluded.expires_at,last_sent_at=excluded.last_sent_at,
               consumed_at=NULL,attempts=0""",
            (phone, purpose, _verification_hash(phone, purpose, code), now + 300, now),
        )
        connection.commit()
    finally:
        connection.close()
    return {"ok": True, "retry_after": 60, "expires_in": 300, "message": "验证码已发送"}


@app.post("/api/v1/auth/register", status_code=201)
@app.post("/api/v1/library/mobile/auth/register", status_code=201)
def register(payload: AuthPayload) -> dict:
    phone = _normalize_phone(payload.phone)
    username = payload.username.strip() or phone
    nickname = payload.nickname.strip() or username
    if not re.fullmatch(r"[A-Za-z0-9_\-\u4e00-\u9fff]{3,32}", username):
        raise HTTPException(status_code=400, detail="账号只能使用中文、字母、数字、下划线或短横线")
    connection = _db()
    try:
        _verify_sms_code(connection, phone, "register", payload.code)
        try:
            cursor = connection.execute(
                """INSERT INTO users(username,phone,nickname,password_hash,created_at,updated_at)
                   VALUES(?,?,?,?,?,?)""",
                (username, phone, nickname, _password_hash(payload.password), time.time(), time.time()),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="该账号或手机号已经注册") from exc
        token = _new_session(connection, int(cursor.lastrowid))
        connection.commit()
        return {"token": token, "username": username, "phone": phone, "nickname": nickname, "expires_in": 30 * 24 * 3600}
    finally:
        connection.close()


@app.post("/api/v1/auth/login")
@app.post("/api/v1/library/mobile/auth/login")
def login(payload: AuthPayload) -> dict:
    account = payload.username.strip()
    connection = _db()
    try:
        row = connection.execute(
            """SELECT id,username,phone,nickname,password_hash FROM users
               WHERE username=? COLLATE NOCASE OR phone=?""",
            (account, re.sub(r"\D", "", account)),
        ).fetchone()
        if not row or not _password_matches(payload.password, str(row["password_hash"])):
            raise HTTPException(status_code=401, detail="账号或密码错误")
        token = _new_session(connection, int(row["id"]))
        connection.commit()
        return {
            "token": token,
            "username": str(row["username"]),
            "phone": str(row["phone"] or ""),
            "nickname": str(row["nickname"]),
            "expires_in": 30 * 24 * 3600,
        }
    finally:
        connection.close()


@app.post("/api/v1/auth/password/reset")
@app.post("/api/v1/library/mobile/auth/password/reset")
def reset_password(payload: PasswordResetPayload) -> dict:
    phone = _normalize_phone(payload.phone)
    connection = _db()
    try:
        _verify_sms_code(connection, phone, "reset", payload.code)
        cursor = connection.execute(
            "UPDATE users SET password_hash=?,updated_at=? WHERE phone=?",
            (_password_hash(payload.new_password), time.time(), phone),
        )
        if cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="该手机号尚未注册")
        connection.execute("DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE phone=?)", (phone,))
        connection.commit()
        return {"ok": True, "message": "密码已重置，请重新登录"}
    finally:
        connection.close()


def _profile(user: sqlite3.Row) -> dict:
    return {
        "id": int(user["id"]), "username": str(user["username"]),
        "phone": str(user["phone"] or ""), "nickname": str(user["nickname"]),
        "avatar_url": str(user["avatar_url"] or ""), "gender": str(user["gender"] or "保密"),
        "bio": str(user["bio"] or ""), "origin": str(user["origin"] or ""),
        "address": str(user["address"] or ""), "wechat": str(user["wechat"] or ""),
    }


@app.get("/api/v1/account/me")
@app.get("/api/v1/library/mobile/account/me")
def account_me(user: sqlite3.Row = Depends(current_user)) -> dict:
    return _profile(user)


@app.put("/api/v1/account/me")
@app.put("/api/v1/library/mobile/account/me")
def update_account(payload: ProfilePayload, user: sqlite3.Row = Depends(current_user)) -> dict:
    nickname = payload.nickname.strip() or str(user["username"])
    gender = payload.gender.strip() or "保密"
    if gender not in {"男", "女", "保密", "其他"}:
        raise HTTPException(status_code=400, detail="性别选项无效")
    connection = _db()
    try:
        connection.execute(
            """UPDATE users SET avatar_url=?,nickname=?,gender=?,bio=?,origin=?,address=?,wechat=?,updated_at=?
               WHERE id=?""",
            (payload.avatar_url.strip(), nickname, gender, payload.bio.strip(), payload.origin.strip(),
             payload.address.strip(), payload.wechat.strip(), time.time(), int(user["id"])),
        )
        connection.commit()
        refreshed = connection.execute("SELECT * FROM users WHERE id=?", (int(user["id"]),)).fetchone()
        return _profile(refreshed)
    finally:
        connection.close()


@app.get("/api/v1/community/messages")
@app.get("/api/v1/library/mobile/community/messages")
def community_messages(limit: int = 100, _: sqlite3.Row = Depends(current_user)) -> dict:
    count = max(1, min(200, int(limit)))
    connection = _db()
    try:
        rows = connection.execute(
            """SELECT community_messages.id,community_messages.content,community_messages.created_at,
                      users.username,users.nickname
               FROM community_messages JOIN users ON users.id=community_messages.user_id
               ORDER BY community_messages.id DESC LIMIT ?""",
            (count,),
        ).fetchall()
    finally:
        connection.close()
    return {
        "messages": [
            {
                "id": int(row["id"]),
                "content": str(row["content"]),
                "created_at": float(row["created_at"]),
                "username": str(row["username"]),
                "nickname": str(row["nickname"]),
            }
            for row in reversed(rows)
        ]
    }


@app.post("/api/v1/community/messages", status_code=201)
@app.post("/api/v1/library/mobile/community/messages", status_code=201)
def send_community_message(payload: ChatPayload, user: sqlite3.Row = Depends(current_user)) -> dict:
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="消息不能为空")
    now = time.time()
    connection = _db()
    try:
        cursor = connection.execute(
            "INSERT INTO community_messages(user_id,content,created_at) VALUES(?,?,?)",
            (int(user["id"]), content, now),
        )
        connection.commit()
        return {
            "id": int(cursor.lastrowid),
            "content": content,
            "created_at": now,
            "username": str(user["username"]),
            "nickname": str(user["nickname"]),
        }
    finally:
        connection.close()


@app.post("/api/v1/jobs", status_code=202)
@app.post("/api/v1/library/jobs", status_code=202)
@app.post("/api/v1/library/mobile/jobs", status_code=202)
async def create_job(
    file: UploadFile = File(...),
    original_filename: str = Form(""),
    arrangement_mode: str = Form("乐队现场版"),
    transpose: int = Form(0),
    output: str = Form("wav_mp3"),
    _: None = Depends(authorize),
) -> dict:
    display_name = (original_filename or file.filename or "audio.mp3").replace("\\", "/").split("/")[-1]
    suffix = Path(display_name).suffix.lower() or Path(file.filename or "audio.mp3").suffix.lower() or ".mp3"
    allowed = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif"}
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail="不支持的音频格式")
    job_id = uuid.uuid4().hex
    name = safe_file_stem(Path(display_name).stem)
    upload_path = UPLOADS / f"{job_id}_{name}{suffix}"
    size = 0
    with upload_path.open("wb") as stream:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > 1024 * 1024 * 1024:
                stream.close()
                upload_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="单个音频不能超过 1GB")
            stream.write(chunk)
    await file.close()

    queued_id = _queue_job(
        file_name=display_name or upload_path.name,
        input_path=upload_path,
        arrangement_mode=arrangement_mode,
        transpose=transpose,
        output=output,
    )
    return {"job_id": queued_id, "status": "queued"}


def _queue_job(
    *, file_name: str, input_path: Path, arrangement_mode: str,
    transpose: int, output: str, library_track_id: int | None = None,
) -> str:
    job_id = uuid.uuid4().hex
    now = time.time()
    with lock:
        jobs[job_id] = {
            "id": job_id,
            "file_name": file_name,
            "input_path": str(input_path),
            "library_track_id": library_track_id,
            "arrangement_mode": _normalize_arrangement_mode(arrangement_mode),
            "transpose": max(-12, min(12, int(transpose))),
            "output": output,
            "status": "queued",
            "stage": "等待 GPU",
            "progress": 5,
            "error": "",
            "key": "C",
            "artifacts": {},
            "created_at": now,
            "updated_at": now,
        }
        atomic_write_json(STATE_FILE, jobs)
    executor.submit(_run_job, job_id)
    return job_id


@app.get("/api/v1/library/mobile/catalog")
@app.get("/api/v1/library/catalog")
@app.get("/api/v1/library")
def library(
    request: Request, q: str = "", category: str = "全部", limit: int = 100000,
    initial: str = "全部", offset: int = 0, since: int = 0,
    _: None = Depends(authorize),
) -> dict:
    current_version = catalog_version(LIBRARY_DB)
    if since and since == current_version and not q.strip() and category == "全部" and initial == "全部":
        return {
            "songs": [], "count": 0, "not_modified": True,
            "catalog_version": current_version, "taxonomy": taxonomy_payload(),
            "categories": taxonomy_payload()["categories"], "source_scope": "server",
            "server_library_root": str(SERVER_LIBRARY_ROOTS[0]),
            "server_library_roots": [str(root) for root in SERVER_LIBRARY_ROOTS],
            "catalog_stats": catalog_facets(LIBRARY_DB),
        }
    incremental = bool(since and since < current_version and not q.strip() and category == "全部" and initial == "全部")
    songs = list_catalog(
        LIBRARY_DB, q, category, limit, initial=initial,
        publish_status="已发布", offset=offset,
        since_revision=since if incremental else 0,
    )
    # Published products live under JUWEIER_PROCESSED_DIR/01_Ready, while the
    # immutable originals may live on a different disk.  A consumer catalog
    # row is valid when either its published audio/artifacts or its original
    # source is inside one of these explicitly configured roots.
    allowed_roots = [root.resolve() for root in SERVER_LIBRARY_ROOTS]
    allowed_roots.append(LIBRARY_PATHS["temp"].resolve())
    allowed_roots.extend(root.resolve() for root in PROCESSED_ROOTS)
    filtered = []
    for song in songs:
        stored_artifacts = dict(song.get("artifacts") or {})
        raw_path = str(
            song.get("final_audio_path") or stored_artifacts.get("original_audio")
            or song.get("working_path") or song.get("source_path") or ""
        )
        try:
            candidate = Path(raw_path).resolve()
            if not any(candidate == root or root in candidate.parents for root in allowed_roots):
                continue
        except Exception:
            continue
        filtered.append(song)
    songs = filtered
    for song in songs:
        source_path = str(song.get("source_path") or song.get("working_path") or "")
        song["metadata_artist"] = song.get("artist") or "未知歌手"
        song["artist"] = catalog_artist_name(song)
        saved_initial = str(song.get("artist_initial") or "")
        song["artist_initial"] = artist_initial_for(
            source_path, song["artist"], saved_initial,
            bool(song.get("artist_initial_locked")),
        )[0]
        track_id = int(song["id"])
        song.pop("source_path", None)
        song.pop("working_path", None)
        song["audio_url"] = str(request.url_for("library_mobile_audio", track_id=track_id))
        stored_artifacts = dict(song.get("artifacts") or {})
        audio_path = Path(str(
            song.get("final_audio_path") or stored_artifacts.get("original_audio")
            or source_path
        ))
        lyric_path = next(
            (candidate for candidate in (audio_path.with_suffix(".lrc"), audio_path.with_suffix(".LRC")) if candidate.is_file()),
            None,
        )
        timeline_path = Path(str(stored_artifacts.get("lyrics_timeline") or ""))
        if lyric_path is not None or timeline_path.is_file():
            song["lyrics_url"] = str(request.url_for("library_mobile_lyrics", track_id=track_id))
            song["lyrics_status"] = "完成"
        if song.get("cover_path"):
            song["cover_url"] = str(request.url_for("library_mobile_cover", track_id=track_id))
        song["artifacts"] = {
            key: str(request.url_for(
                "library_catalog_artifact", track_id=track_id, artifact_key=key,
            ))
            for key, value in stored_artifacts.items()
            if Path(str(value)).is_file()
        }
        song.pop("artifacts_json", None)
        song.pop("cover_path", None)
    public_fields = {
        "id", "title", "artist", "album", "year", "duration", "format", "quality",
        "bpm", "musical_key", "category", "artist_initial", "language", "genre",
        "mood", "scene", "region", "tags", "publish_status", "processing_status",
        "lyrics_status", "stems_status", "score_status", "arrangement_status",
        "audio_url", "cover_url", "lyrics_url", "artifacts", "is_featured",
    }
    songs = [{key: value for key, value in song.items() if key in public_fields} for song in songs]
    artists = {}
    for song in songs:
        name = song.get("artist") or "未知歌手"
        artists[name] = artists.get(name, 0) + 1
    deleted_ids: list[int] = []
    if incremental:
        connection = connect_catalog(LIBRARY_DB)
        try:
            deleted_ids = [
                int(row[0]) for row in connection.execute(
                    "SELECT DISTINCT track_id FROM catalog_changes "
                    "WHERE revision>? AND change_type='deleted'",
                    (int(since),),
                ).fetchall()
            ]
        finally:
            connection.close()
    return {
        "songs": songs, "count": len(songs),
        "incremental": incremental, "deleted_ids": deleted_ids,
        "artists": [{"name": name, "count": count} for name, count in sorted(artists.items())],
        "categories": taxonomy_payload()["categories"],
        "taxonomy": taxonomy_payload(),
        "catalog_version": current_version,
        "catalog_stats": catalog_facets(LIBRARY_DB),
        "source_scope": "server",
        "server_library_root": str(SERVER_LIBRARY_ROOTS[0]),
        "server_library_roots": [str(root) for root in SERVER_LIBRARY_ROOTS],
        "catalog_state": dict(catalog_state),
        "catalog_updated_at": float(catalog_state.get("updated_at", 0) or 0),
        "notice": "服务器曲库与客户端本地导入已分离",
    }


@app.post("/api/v1/library/mobile/catalog/scan")
@app.post("/api/v1/library/catalog/scan")
@app.post("/api/v1/library/scan")
def scan_library(_: None = Depends(authorize)) -> dict:
    try:
        return _scan_server_catalog()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/v1/library/mobile/import-url", status_code=201)
@app.post("/api/v1/library/import-url", status_code=201)
def import_library_url(payload: LinkImportPayload, _: None = Depends(authorize)) -> dict:
    destination = LIBRARY_PATHS["temp"] / "链接导入"
    path = download_public_audio(payload.url.strip(), destination, shutil.which("ffmpeg") or "")
    result = scan_catalog_roots([destination], LIBRARY_DB, LIBRARY_PATHS["covers"])
    return {"status": "imported", "file_name": path.name, "scan": result}


@app.get("/api/v1/library/mobile/catalog/{track_id}/audio", name="library_mobile_audio")
@app.get("/api/v1/library/{track_id}/audio", name="library_audio")
def library_audio(track_id: int, _: None = Depends(authorize)):
    song = catalog_track(LIBRARY_DB, track_id)
    artifacts = {}
    try:
        artifacts = json.loads(str(song.get("artifacts_json") or "{}")) if song else {}
    except Exception:
        artifacts = {}
    path = Path(str(
        (song or {}).get("final_audio_path") or artifacts.get("original_audio")
        or (song or {}).get("working_path") or (song or {}).get("source_path") or ""
    )) if song else None
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="歌曲文件不存在")
    return FileResponse(path, filename=path.name)


@app.get("/api/v1/library/mobile/catalog/{track_id}/cover", name="library_mobile_cover")
@app.get("/api/v1/library/{track_id}/cover", name="library_cover")
def library_cover(track_id: int, _: None = Depends(authorize)):
    song = catalog_track(LIBRARY_DB, track_id)
    path = Path(str(song.get("cover_path", ""))) if song else None
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="封面不存在")
    return FileResponse(path, filename=path.name)


@app.get("/api/v1/library/mobile/catalog/{track_id}/lyrics", name="library_mobile_lyrics")
@app.get("/api/v1/library/catalog/{track_id}/lyrics", name="library_lyrics")
@app.get("/api/v1/library/{track_id}/lyrics", name="library_legacy_lyrics")
def library_lyrics(track_id: int, _: None = Depends(authorize)):
    song = catalog_track(LIBRARY_DB, track_id)
    try:
        artifacts = json.loads(str(song.get("artifacts_json") or "{}")) if song else {}
    except Exception:
        artifacts = {}
    timeline_path = Path(str(artifacts.get("lyrics_timeline") or ""))
    if timeline_path.is_file():
        return FileResponse(timeline_path, filename="lyrics_timeline.json", media_type="application/json")
    audio_path = Path(str(song.get("working_path") or song.get("source_path"))) if song else None
    if not audio_path:
        raise HTTPException(status_code=404, detail="歌词不存在")
    path = next(
        (candidate for candidate in (audio_path.with_suffix(".lrc"), audio_path.with_suffix(".LRC")) if candidate.is_file()),
        None,
    )
    if path is None:
        raise HTTPException(status_code=404, detail="歌词不存在")
    return FileResponse(path, filename=f"{safe_file_stem(audio_path.stem)}.lrc", media_type="text/plain")


@app.get(
    "/api/v1/library/mobile/catalog/{track_id}/artifacts/{artifact_key}",
    name="library_catalog_artifact",
)
@app.get("/api/v1/library/catalog/{track_id}/artifacts/{artifact_key}")
def library_catalog_artifact(track_id: int, artifact_key: str, _: None = Depends(authorize)):
    song = catalog_track(LIBRARY_DB, track_id)
    try:
        artifacts = json.loads(str(song.get("artifacts_json") or "{}")) if song else {}
    except Exception:
        artifacts = {}
    path = Path(str(artifacts.get(artifact_key) or ""))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="歌曲成果不存在")
    return FileResponse(path, filename=path.name)


@app.post("/api/v1/library/mobile/catalog/{track_id}/process", status_code=202)
@app.post("/api/v1/library/{track_id}/process", status_code=202)
def process_library_song(track_id: int, payload: LibraryProcessPayload, _: None = Depends(authorize)) -> dict:
    song = catalog_track(LIBRARY_DB, track_id)
    if not song:
        raise HTTPException(status_code=404, detail="歌曲不存在")
    input_path = Path(str(song.get("working_path") or song.get("source_path")))
    if not input_path.is_file():
        raise HTTPException(status_code=404, detail="歌曲文件不存在")
    connection = connect_catalog(LIBRARY_DB)
    try:
        revision = max(int(time.time() * 1000), catalog_version(connection) + 1)
        connection.execute(
            "UPDATE tracks SET processing_status='排队中',catalog_updated_at=?,catalog_revision=? WHERE id=?",
            (time.time(), revision, track_id),
        )
        bump_catalog_version(connection, revision)
        connection.commit()
    finally:
        connection.close()
    queued_id = _queue_job(
        file_name=input_path.name, input_path=input_path,
        arrangement_mode=payload.arrangement_mode, transpose=payload.transpose,
        output=payload.output, library_track_id=track_id,
    )
    return {"job_id": queued_id, "status": "queued"}


@app.get("/api/v1/library/mobile/batch/status")
@app.get("/api/v1/library/batch/status")
def library_batch_status(_: None = Depends(authorize)) -> dict:
    with batch_lock:
        _, product_storage = _processed_storage_status()
        return {**batch_state, "counts": _batch_counts(), "processed_storage": product_storage}


@app.post("/api/v1/library/mobile/batch/start", status_code=202)
@app.post("/api/v1/library/batch/start", status_code=202)
def library_batch_start(
    retry_failed: bool = False,
    limit: int = 0,
    _: None = Depends(authorize),
) -> dict:
    global batch_thread
    if retry_failed:
        connection = connect_catalog(LIBRARY_DB)
        try:
            revision = max(int(time.time() * 1000), catalog_version(connection) + 1)
            connection.execute(
                "UPDATE tracks SET processing_status='待处理',catalog_revision=?,catalog_updated_at=? "
                "WHERE processing_status IN ('失败','成果待校验')"
                , (revision, time.time())
            )
            bump_catalog_version(connection, revision)
            connection.commit()
        finally:
            connection.close()
    with batch_lock:
        safe_limit = max(0, min(int(limit), 100_000))
        batch_state.update(
            running=True, paused=False, current_track_id=0, current_job_id="",
            submitted=0, completed=0, failed=0, limit=safe_limit,
            pause_reason="", updated_at=time.time(),
        )
        if batch_thread is None or not batch_thread.is_alive():
            batch_thread = threading.Thread(
                target=_library_batch_loop, name="library-batch", daemon=True,
            )
            batch_thread.start()
        _save_batch_state()
        return {**batch_state, "counts": _batch_counts()}


@app.post("/api/v1/library/mobile/batch/pause")
@app.post("/api/v1/library/batch/pause")
def library_batch_pause(_: None = Depends(authorize)) -> dict:
    with batch_lock:
        batch_state.update(paused=True, running=False, updated_at=time.time())
        _save_batch_state()
        return {**batch_state, "counts": _batch_counts(), "message": "当前歌曲完成后暂停"}


def _publish_validated_result(
    working_root: Path, song: dict, artifacts: dict[str, str],
) -> tuple[Path, dict[str, str]]:
    """Publish to the first safe product disk (G, then F) with one atomic rename."""

    total_bytes = sum(
        path.stat().st_size for path in working_root.rglob("*") if path.is_file()
    )
    processed_root, storage = _processed_storage_status(total_bytes)
    if processed_root is None:
        raise StorageCapacityError(capacity_message(storage))

    artist = to_simplified(catalog_artist_name(song))
    title = to_simplified(
        str(song.get("title") or Path(str(song.get("source_path") or "歌曲")).stem)
    )
    initial = str(song.get("artist_initial") or _artist_initial(artist, str(song.get("source_path") or "")))
    target = finished_song_dir(processed_root, initial, artist, title)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.publishing")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(working_root, staging)
    simplify_published_tree(staging)

    remapped: dict[str, str] = {}
    working_text = str(working_root.resolve())
    for key, value in artifacts.items():
        source = Path(str(value))
        try:
            relative = simplified_relative_path(
                source.resolve().relative_to(working_root.resolve())
            )
            remapped[key] = str(target / relative)
        except (ValueError, OSError):
            remapped[key] = str(value)
    atomic_write_json(staging / "published_manifest.json", {
        "version": VERSION,
        "artist": artist,
        "title": title,
        "artist_initial": initial,
        "source_path": str(song.get("source_path") or ""),
        "published_at": time.time(),
        "artifacts": remapped,
        "working_root": working_text,
    })

    if target.exists():
        backup = (
            processed_root / "04_Backup" / initial / safe_file_stem(artist, "未知歌手")
            / f"{safe_file_stem(title, '未知歌曲')}_{int(time.time())}"
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(backup))
    os.replace(staging, target)
    shutil.rmtree(working_root, ignore_errors=True)
    return target, remapped


def _run_job(job_id: str) -> None:
    job = jobs[job_id]
    input_path = Path(job["input_path"])
    # All heavy intermediate writes stay on the internal server disk.  Only a
    # fully validated result is copied into G: or F:\...\01_Ready atomically.
    output_root = OUTPUTS / job_id
    output_root.mkdir(parents=True, exist_ok=True)
    try:
        _update(job_id, status="processing", stage="检查 AI 处理环境", progress=5)
        _require_processing_runtime()
        _update(job_id, status="processing", stage="准备六轨模型与电吉他二次分离", progress=7)
        command = [
            sys.executable,
            "-m",
            "app.separation_worker_process",
            str(input_path),
            "--output",
            str(output_root / "stems"),
            "--device",
            "auto",
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=Path(__file__).resolve().parents[1],
            env={
                **os.environ,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
                "JUWEIER_UVR_MODEL_DIR": os.environ.get(
                    "JUWEIER_UVR_MODEL_DIR",
                    str(ROOT / "models" / "uvr"),
                ),
            },
        )
        stem_dir = ""
        last_error = ""
        if process.stdout is not None:
            for raw in iter(process.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace").strip()
                try:
                    message = json.loads(line)
                except Exception:
                    continue
                kind = message.get("type")
                if kind == "model_progress":
                    value = float(message.get("value", 0))
                    _update(job_id, stage=str(message.get("text", "准备模型")), progress=7 + value * 0.08)
                elif kind == "separation_progress":
                    value = float(message.get("value", 0))
                    _update(job_id, stage=str(message.get("text", "基础六轨分离")), progress=15 + value * 0.40)
                elif kind == "done":
                    stem_dir = str(message.get("stem_dir", ""))
                elif kind == "failed":
                    last_error = str(message.get("error", "六轨分离失败"))
        code = process.wait()
        if code != 0 or not stem_dir:
            raise RuntimeError(last_error or f"分轨 Worker 退出码 {code}")

        artifacts = {f"stem_{p.stem}": str(p) for p in Path(stem_dir).glob("*.wav")}
        original_folder = output_root / "audio"
        original_folder.mkdir(parents=True, exist_ok=True)
        original_copy = original_folder / f"original{input_path.suffix.casefold()}"
        shutil.copy2(input_path, original_copy)
        artifacts["original_audio"] = str(original_copy)
        guitar_report = Path(stem_dir) / "guitar_second_stage.json"
        if guitar_report.is_file():
            artifacts["electric_guitar_report"] = str(guitar_report)
        _update(job_id, stage="BPM / 调性 / 和弦 / 原唱歌词时间轴分析", progress=58, artifacts=artifacts)
        analysis, chord_rows = _analyze(input_path, Path(stem_dir) / "vocals.wav")
        analysis, chord_rows = _transpose_analysis(analysis, chord_rows, int(job.get("transpose", 0)))
        artifacts["chords"] = str(_write_chords(output_root, chord_rows))
        _update(job_id, stage="生成五线谱、六线谱及各乐手谱面", progress=72, key=analysis["key"], artifacts=artifacts)
        artifacts.update(_write_scores(output_root, job["file_name"], analysis, chord_rows))
        _update(job_id, stage="生成新 MIDI 编配", progress=88, artifacts=artifacts)
        midi = _write_arrangement(output_root, analysis, chord_rows)
        artifacts["arrangement_midi"] = str(midi)
        readiness = _validate_publish_artifacts(artifacts)
        artifacts["readiness_report"] = str(readiness["report_path"])
        if job.get("library_track_id"):
            connection = connect_catalog(LIBRARY_DB)
            try:
                song_row = connection.execute(
                    "SELECT * FROM tracks WHERE id=?", (int(job["library_track_id"]),),
                ).fetchone()
                if not song_row:
                    raise RuntimeError("待发布歌曲已从服务器索引删除")
                if not readiness["ready"]:
                    raise RuntimeError(
                        "成果校验未通过，禁止进入 App 成品曲库：" + "、".join(readiness["issues"])
                    )
                published_root, artifacts = _publish_validated_result(
                    output_root, dict(song_row), artifacts,
                )
                published_artist = to_simplified(catalog_artist_name(dict(song_row)))
                published_title = to_simplified(
                    str(song_row["title"] or Path(str(song_row["source_path"] or "歌曲")).stem)
                )
                published_initial = _artist_initial(
                    published_artist, str(song_row["source_path"] or "")
                )
                revision = max(int(time.time() * 1000), catalog_version(connection) + 1)
                connection.execute(
                    """UPDATE tracks SET bpm=?, musical_key=?, analysis_status='完成',
                       stems_status='完成', chords_status='完成', score_status='完成',
                       arrangement_status='完成',processing_status='已完成',publish_status='已发布',
                       lyrics_status=?,final_audio_path=?,title=?,artist=?,source_group=?,artist_initial=?,
                       artifacts_json=?,catalog_updated_at=?,catalog_revision=? WHERE id=?""",
                    (
                        analysis.get("bpm"), analysis.get("key"), readiness["lyrics_status"],
                        artifacts["original_audio"], published_title, published_artist,
                        published_artist, published_initial,
                        json.dumps(artifacts, ensure_ascii=False), time.time(), revision,
                        int(job["library_track_id"]),
                    ),
                )
                bump_catalog_version(connection, revision)
                connection.commit()
            finally:
                connection.close()
        _update(job_id, status="completed", stage="校验通过并已发布到成品曲库", progress=100, artifacts=artifacts)
    except StorageCapacityError:
        if job.get("library_track_id"):
            _set_track_processing_status(int(job["library_track_id"]), "待处理")
        _, storage = _processed_storage_status()
        reason = _pause_batch_for_storage(storage)
        _update(job_id, status="paused", stage="等待增加成品硬盘", error=reason)
    except Exception as exc:
        if job.get("library_track_id"):
            _set_track_processing_status(int(job["library_track_id"]), "失败")
        _update(job_id, status="failed", stage="失败", error=_friendly_job_error(exc))


def _validate_publish_artifacts(artifacts: dict[str, str]) -> dict:
    """Only mark AI results ready after electric-guitar and lyric/note assets validate."""
    required_audio = (
        "stem_vocals", "stem_drums", "stem_bass", "stem_guitar",
        "stem_electric_guitar", "stem_piano", "stem_other",
    )
    missing = [key for key in required_audio if not Path(str(artifacts.get(key) or "")).is_file()]
    durations: dict[str, float] = {}
    try:
        import soundfile as sf

        for key in required_audio:
            path = Path(str(artifacts.get(key) or ""))
            if not path.is_file():
                continue
            info = sf.info(str(path))
            if info.frames <= 0 or info.samplerate <= 0:
                missing.append(f"{key}:invalid")
            else:
                durations[key] = float(info.frames / info.samplerate)
    except Exception as exc:
        missing.append(f"audio-validation:{exc}")
    if durations:
        reference = max(durations.values())
        for key, duration in durations.items():
            if abs(reference - duration) > 1.0:
                missing.append(f"{key}:duration")

    score_path = Path(str(artifacts.get("score_data") or ""))
    lyric_path = Path(str(artifacts.get("lyrics_timeline") or ""))
    lyric_aligned = False
    if score_path.is_file() and lyric_path.is_file():
        try:
            score = json.loads(score_path.read_text(encoding="utf-8"))
            timeline = json.loads(lyric_path.read_text(encoding="utf-8"))
            units = list(timeline.get("units") or [])
            notes = list(score.get("staff_notes") or [])
            lyric_aligned = bool(units) and any(str(note.get("lyric") or "") for note in notes)
        except Exception:
            lyric_aligned = False
    if not score_path.is_file():
        missing.append("score_data")
    if not Path(str(artifacts.get("electric_guitar_tab") or "")).is_file():
        missing.append("electric_guitar_tab")
    guitar_method = ""
    guitar_report_path = Path(str(artifacts.get("electric_guitar_report") or ""))
    if guitar_report_path.is_file():
        try:
            guitar_method = str(json.loads(guitar_report_path.read_text(encoding="utf-8")).get("method") or "")
        except Exception:
            guitar_method = ""
    if not guitar_method:
        missing.append("electric_guitar_provenance")
    if not lyric_aligned:
        missing.append("lyrics_note_alignment")

    report_path = (score_path.parent if score_path.parent.is_dir() else ROOT) / "publish_readiness.json"
    report = {
        "ready": not missing,
        "electric_guitar_valid": "stem_electric_guitar" in durations,
        "electric_guitar_method": guitar_method,
        "lyrics_note_aligned": lyric_aligned,
        "durations": durations,
        "issues": list(dict.fromkeys(missing)),
    }
    atomic_write_json(report_path, report)
    return {
        "ready": not missing,
        "issues": list(dict.fromkeys(missing)),
        "processing_status": "已完成" if not missing else "成果待校验",
        "lyrics_status": "完成" if lyric_aligned else "待校对",
        "report_path": report_path,
    }


def _analyze(path: Path, vocals_path: Path | None = None) -> tuple[dict, list[dict]]:
    import librosa

    y, sample_rate = librosa.load(path, sr=22050, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sample_rate)
    bpm = float(np.asarray(tempo).reshape(-1)[0])
    beat_times = librosa.frames_to_time(beat_frames, sr=sample_rate)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sample_rate)
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    key = names[int(np.argmax(np.mean(chroma, axis=1)))]
    beat_chroma = librosa.util.sync(chroma, beat_frames, aggregate=np.median)
    templates = []
    for root in range(12):
        for suffix, intervals in (("", (0, 4, 7)), ("m", (0, 3, 7)), ("7", (0, 4, 7, 10)), ("maj7", (0, 4, 7, 11)), ("m7", (0, 3, 7, 10))):
            template = np.zeros(12, float)
            for interval in intervals:
                template[(root + interval) % 12] = 1.0
            templates.append((names[root] + suffix, template / (np.linalg.norm(template) + 1e-9)))
    chords = []
    for index in range(beat_chroma.shape[1]):
        vector = beat_chroma[:, index].astype(float)
        vector = vector / (np.linalg.norm(vector) + 1e-9)
        chords.append(max(((float(np.dot(vector, template)), name) for name, template in templates))[1])
    rows = []
    for start in range(0, min(len(chords), len(beat_times)), 4):
        compact = []
        for chord in chords[start : start + 4]:
            if not compact or compact[-1] != chord:
                compact.append(chord)
        ratio = start / max(1, len(chords) - 1)
        section = "前奏" if ratio < .1 else "主歌" if ratio < .45 else "副歌" if ratio < .72 else "间奏" if ratio < .88 else "尾奏"
        rows.append({"bar": len(rows) + 1, "seconds": float(beat_times[start]), "section": section, "chords": compact or [key]})
    melody_notes = []
    try:
        f0, _, _ = librosa.pyin(
            y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"),
            sr=sample_rate, frame_length=2048, hop_length=512,
        )
        times = librosa.times_like(f0, sr=sample_rate, hop_length=512)
        current = None
        start = 0
        for index, value in enumerate(f0):
            midi = int(round(float(librosa.hz_to_midi(value)))) if np.isfinite(value) else None
            if midi != current:
                if current is not None and start < index:
                    duration = float(times[index - 1] - times[start] + 512 / sample_rate)
                    if duration >= .08:
                        melody_notes.append({"start": float(times[start]), "duration": duration, "midi": current})
                current = midi
                start = index
        if current is not None and len(times) > start:
            melody_notes.append({"start": float(times[start]), "duration": max(.08, float(times[-1] - times[start])), "midi": current})
        melody_notes = melody_notes[:2000]
    except Exception:
        melody_notes = []
    duration = float(librosa.get_duration(y=y, sr=sample_rate))
    # First prefer a same-name LRC/embedded lyric beside the server original.
    # If it is absent, transcribe the isolated vocal stem for better Mandarin,
    # Cantonese and English recognition than the full instrumental mix.
    existing_lyrics = load_synced_lyrics(path, duration)
    if existing_lyrics:
        lyric_result = {
            "rows": existing_lyrics, "status": "ready", "source": "lrc_or_embedded",
            "language": "", "message": "已读取同名 LRC 或音频内嵌歌词",
        }
    else:
        lyric_result = transcribe_synced_lyrics(
            vocals_path if vocals_path and vocals_path.is_file() else path, duration,
        )
    return {
        "bpm": round(bpm, 1), "key": key,
        "duration": duration,
        "melody_notes": melody_notes,
        "lyrics": lyric_result["rows"],
        "lyrics_status": lyric_result["status"],
        "lyrics_source": lyric_result["source"],
        "lyrics_language": lyric_result["language"],
        "lyrics_message": lyric_result["message"],
    }, rows


def _write_chords(folder: Path, rows: list[dict]) -> Path:
    path = folder / "chords.json"
    atomic_write_json(path, rows)
    return path


def _transpose_chord(chord: str, semitones: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    match = re.match(r"^([A-G](?:#|b)?)(.*)$", chord)
    if not match:
        return chord
    aliases = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
    root = aliases.get(match.group(1), match.group(1))
    if root not in names:
        return chord
    return names[(names.index(root) + semitones) % 12] + match.group(2)


def _transpose_analysis(analysis: dict, rows: list[dict], semitones: int) -> tuple[dict, list[dict]]:
    if not semitones:
        return analysis, rows
    result = dict(analysis)
    result["key"] = _transpose_chord(str(result.get("key", "C")), semitones)
    result["melody_notes"] = [
        {**note, "midi": int(note.get("midi", 60)) + semitones}
        for note in result.get("melody_notes", [])
    ]
    transposed = []
    for row in rows:
        item = dict(row)
        item["chords"] = [_transpose_chord(str(chord), semitones) for chord in row.get("chords", [])]
        transposed.append(item)
    return result, transposed


def _write_musicxml(folder: Path, title: str, analysis: dict, rows: list[dict]) -> Path:
    pitch_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    fifths = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6,
              "F": -1, "A#": -2, "D#": -3, "G#": -4, "C#": -5}
    note_steps = {"C": ("C", 0), "C#": ("C", 1), "D": ("D", 0), "D#": ("D", 1),
                  "E": ("E", 0), "F": ("F", 0), "F#": ("F", 1), "G": ("G", 0),
                  "G#": ("G", 1), "A": ("A", 0), "A#": ("A", 1), "B": ("B", 0)}
    measures = []
    melody = list(analysis.get("melody_notes", []))
    lyrics = list(analysis.get("lyrics", []))
    measure_count = max(len(rows), (len(melody) + 3) // 4, 1)
    for index in range(1, measure_count + 1):
        row = rows[index - 1] if index <= len(rows) else {"chords": [analysis.get("key", "C")]}
        chord = str((row.get("chords") or [analysis.get("key", "C")])[0])
        match = re.match(r"^([A-G](?:#)?)(m|maj7|m7|7)?", chord)
        root = match.group(1) if match else "C"
        kind = (match.group(2) if match else "") or "major"
        kind = {"m": "minor", "7": "dominant", "maj7": "major-seventh", "m7": "minor-seventh"}.get(kind, kind)
        step, alter = note_steps.get(root, ("C", 0))
        attributes = ""
        if index == 1:
            attributes = (
                f"<attributes><divisions>1</divisions><key><fifths>{fifths.get(str(analysis.get('key', 'C')), 0)}</fifths></key>"
                "<time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>"
            )
        alter_xml = f"<root-alter>{alter}</root-alter>" if alter else ""
        measure_seconds = float(row.get("seconds", 0) or 0)
        lyric_text = ""
        for lyric_row in lyrics:
            if float(lyric_row.get("start", 0) or 0) <= measure_seconds:
                lyric_text = str(lyric_row.get("text", "") or "")
            else:
                break
        lyric_direction = (
            "<direction placement='below'><direction-type><words>"
            + html.escape(lyric_text) + "</words></direction-type></direction>"
            if lyric_text else ""
        )
        note_xml = []
        for event in melody[(index - 1) * 4:index * 4]:
            midi = int(event.get("midi", 60))
            pitch = pitch_names[midi % 12]
            note_step, note_alter = note_steps[pitch]
            octave = midi // 12 - 1
            alter_note_xml = f"<alter>{note_alter}</alter>" if note_alter else ""
            lyric = html.escape(str(event.get("lyric", "") or ""))
            lyric_xml = f"<lyric><syllabic>single</syllabic><text>{lyric}</text></lyric>" if lyric else ""
            note_xml.append(
                f"<note><pitch><step>{note_step}</step>{alter_note_xml}<octave>{octave}</octave></pitch>"
                f"<duration>1</duration><type>quarter</type>{lyric_xml}</note>"
            )
        if not note_xml:
            note_xml.append("<note><rest/><duration>4</duration><type>whole</type></note>")
        measures.append(
            f'<measure number="{index}">{attributes}<harmony><root><root-step>{step}</root-step>{alter_xml}</root>'
            f'<kind>{kind}</kind></harmony>{lyric_direction}{"".join(note_xml)}</measure>'
        )
    path = folder / "lead_sheet.musicxml"
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
        '"http://www.musicxml.org/dtds/partwise.dtd">'
        '<score-partwise version="4.0"><work><work-title>' + html.escape(title) + '</work-title></work>'
        '<part-list><score-part id="P1"><part-name>Juweier Lead Sheet</part-name></score-part></part-list>'
        '<part id="P1">' + "".join(measures) + '</part></score-partwise>'
    )
    path.write_text(document, encoding="utf-8")
    return path


def _write_scores(folder: Path, title: str, analysis: dict, rows: list[dict]) -> dict[str, str]:
    lyrics = list(analysis.get("lyrics", []))
    lyric_units = expand_lyric_units(lyrics)
    staff_notes = align_lyric_units_to_notes(analysis.get("melody_notes", []), lyric_units)
    score_analysis = dict(analysis)
    score_analysis["melody_notes"] = staff_notes
    score_analysis["lyric_units"] = lyric_units

    def lyric_at(seconds: float) -> str:
        current = ""
        for lyric_row in lyrics:
            if float(lyric_row.get("start", 0) or 0) <= seconds:
                current = str(lyric_row.get("text", "") or "")
            else:
                break
        return current

    def table(kind: str, hint: str) -> str:
        body = "".join(
            f"<tr><td>{row['bar']}</td><td>{html.escape(row['section'])}</td>"
            f"<td>{html.escape(' / '.join(row['chords']))}</td>"
            f"<td>{html.escape(lyric_at(float(row.get('seconds', 0) or 0)))}</td>"
            f"<td>{html.escape(hint)}</td></tr>"
            for row in rows
        )
        lyric_notice = html.escape(str(analysis.get("lyrics_message") or ""))
        return (
            "<!doctype html><meta charset='utf-8'><style>body{font-family:sans-serif;background:#090d18;color:#fff;padding:24px}"
            "table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #29354d}.notice{color:#ffb45e}</style>"
            f"<h1>{html.escape(title)} · {kind}</h1><p>BPM {analysis['bpm']} · {analysis['key']} 调</p>"
            f"<p class='notice'>歌词：{lyric_notice}</p>"
            f"<table><tr><th>小节</th><th>段落</th><th>和弦</th><th>同步歌词</th><th>演奏提示</th></tr>{body}</table>"
        )

    specs = {
        "lead_sheet": ("和弦谱", "按段落力度演奏"),
        "guitar_tab": ("吉他六线谱参考", "按和弦根音生成分解/扫弦"),
        "acoustic_guitar_tab": ("木吉他六线谱参考", "木吉他分解和弦/扫弦"),
        "electric_guitar_tab": ("电吉他六线谱参考", "电吉他节奏型、强拍与 Solo 提示"),
        "bass_score": ("贝斯谱参考", "根音、五度与八度连接"),
        "drum_score": ("鼓谱参考", "Kick / Snare / Hi-Hat，副歌加强"),
        "piano_score": ("键盘谱参考", "左手根音，右手和弦分解"),
    }
    result = {}
    for key, (name, hint) in specs.items():
        path = folder / f"{key}.html"
        path.write_text(table(name, hint), encoding="utf-8")
        result[key] = str(path)
    result["musicxml"] = str(_write_musicxml(folder, title, score_analysis, rows))
    tuning = [40, 45, 50, 55, 59, 64]
    tab_notes = []
    for note in staff_notes:
        midi = int(note.get("midi", 60))
        choices = [(midi - open_note, string + 1) for string, open_note in enumerate(tuning) if 0 <= midi - open_note <= 24]
        fret, string = min(choices, default=(0, 1), key=lambda item: (item[0], -item[1]))
        tab_notes.append({**note, "string": string, "fret": fret})
    score_data = folder / "score_data.json"
    atomic_write_json(score_data, {
        "title": title, "bpm": analysis.get("bpm", 120), "key": analysis.get("key", "C"),
        "duration": analysis.get("duration", 0), "bars": rows,
        "staff_notes": staff_notes, "tab_notes": tab_notes,
        "lyrics": analysis.get("lyrics", []),
        "lyric_units": lyric_units,
        "lyrics_note_aligned": True,
        "lyrics_status": analysis.get("lyrics_status", "empty"),
        "lyrics_source": analysis.get("lyrics_source", "none"),
        "lyrics_language": analysis.get("lyrics_language", ""),
        "lyrics_message": analysis.get("lyrics_message", ""),
    })
    result["score_data"] = str(score_data)
    lyrics_data = folder / "lyrics_timeline.json"
    atomic_write_json(lyrics_data, {
        "rows": analysis.get("lyrics", []),
        "units": lyric_units,
        "status": analysis.get("lyrics_status", "empty"),
        "source": analysis.get("lyrics_source", "none"),
        "language": analysis.get("lyrics_language", ""),
        "message": analysis.get("lyrics_message", ""),
    })
    result["lyrics_timeline"] = str(lyrics_data)
    return result


def _write_arrangement(folder: Path, analysis: dict, rows: list[dict]) -> Path:
    from mido import Message, MetaMessage, MidiFile, MidiTrack, bpm2tempo

    midi = MidiFile(ticks_per_beat=480)
    meta = MidiTrack()
    track = MidiTrack()
    midi.tracks.extend((meta, track))
    meta.append(MetaMessage("set_tempo", tempo=bpm2tempo(float(analysis["bpm"] or 120)), time=0))
    note_map = {"C": 60, "C#": 61, "D": 62, "D#": 63, "E": 64, "F": 65, "F#": 66, "G": 67, "G#": 68, "A": 69, "A#": 70, "B": 71}
    for row in rows:
        match = re.match(r"^([A-G](?:#)?)(m?)", (row.get("chords") or ["C"])[0])
        root = note_map.get(match.group(1) if match else "C", 60)
        minor = bool(match and match.group(2))
        for note in (root, root + (3 if minor else 4), root + 7):
            track.append(Message("note_on", note=note, velocity=72, time=0))
        track.append(Message("note_off", note=root, velocity=0, time=1920))
        track.append(Message("note_off", note=root + (3 if minor else 4), velocity=0, time=0))
        track.append(Message("note_off", note=root + 7, velocity=0, time=0))
    path = folder / "arrangement.mid"
    midi.save(path)
    return path


def _public_job(job: dict, request: Request) -> dict:
    result = copy.deepcopy(job)
    result.pop("input_path", None)
    public = {}
    for key, value in result.get("artifacts", {}).items():
        public[key] = str(request.url_for("library_mobile_artifact", job_id=result["id"], name=Path(value).name))
    result["artifacts"] = public
    return result


@app.get("/api/v1/jobs/{job_id}")
@app.get("/api/v1/library/jobs/{job_id}")
@app.get("/api/v1/library/mobile/jobs/{job_id}")
def get_job(job_id: str, request: Request, _: None = Depends(authorize)) -> dict:
    with lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        return _public_job(job, request)


@app.get("/api/v1/artifacts/{job_id}/{name}", name="artifact")
@app.get("/api/v1/library/artifacts/{job_id}/{name}", name="library_artifact")
@app.get("/api/v1/library/mobile/artifacts/{job_id}/{name}", name="library_mobile_artifact")
def artifact(job_id: str, name: str, _: None = Depends(authorize)):
    with lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        candidates = [Path(value) for value in job.get("artifacts", {}).values() if Path(value).name == name]
    if not candidates or not candidates[0].is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(candidates[0], filename=name)
