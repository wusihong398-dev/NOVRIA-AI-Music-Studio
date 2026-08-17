"""Mobile API companion for 橘味儿音乐 v3.2.0.

Run this on the Windows/GPU computer. Android and iOS clients upload source
audio here; Demucs and the analysis pipeline remain on the capable computer.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import html
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

from app.project_utils import atomic_write_json, safe_file_stem
from app.library_catalog import (
    catalog_track,
    connect_catalog,
    default_library_root,
    ensure_library_layout,
    list_catalog,
    scan_catalog,
)


APP_NAME = "橘味儿音乐"
VERSION = "3.1.0"
ROOT = Path(os.environ.get("JUWEIER_DATA_DIR", Path.cwd() / "mobile_server_data")).resolve()
UPLOADS = ROOT / "uploads"
OUTPUTS = ROOT / "outputs"
STATE_FILE = ROOT / "jobs.json"
ACCOUNT_DB = ROOT / "accounts.sqlite3"
TOKEN = os.environ.get("JUWEIER_API_TOKEN", "").strip()
LIBRARY_PATHS = ensure_library_layout(default_library_root())
LIBRARY_DB = LIBRARY_PATHS["database"] / "juweier_music_library.sqlite3"
connect_catalog(LIBRARY_DB).close()
for folder in (UPLOADS, OUTPUTS):
    folder.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=f"{APP_NAME} Mobile API", version=VERSION)
lock = threading.RLock()
executor = ThreadPoolExecutor(max_workers=max(1, int(os.environ.get("JUWEIER_WORKERS", "1"))))


class AuthPayload(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    nickname: str = Field(default="", max_length=32)


class ChatPayload(BaseModel):
    content: str = Field(min_length=1, max_length=500)


class LibraryProcessPayload(BaseModel):
    arrangement_mode: str = "乐队现场版"
    transpose: int = Field(default=0, ge=-12, le=12)
    output: str = "wav_mp3"


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
            """
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
            """SELECT users.id,users.username,users.nickname
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


def _gpu_name() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return torch.cuda.get_device_name(0)
        return "CPU"
    except Exception:
        return "未检测到 PyTorch"


@app.get("/health")
@app.get("/api/health")
def health(_: None = Depends(authorize)) -> dict:
    return {"status": "healthy", "app": APP_NAME, "version": VERSION, "gpu": _gpu_name()}


@app.post("/api/v1/auth/register", status_code=201)
def register(payload: AuthPayload) -> dict:
    username = payload.username.strip()
    nickname = payload.nickname.strip() or username
    if not re.fullmatch(r"[A-Za-z0-9_\-\u4e00-\u9fff]{3,32}", username):
        raise HTTPException(status_code=400, detail="账号只能使用中文、字母、数字、下划线或短横线")
    connection = _db()
    try:
        try:
            cursor = connection.execute(
                "INSERT INTO users(username,nickname,password_hash,created_at) VALUES(?,?,?,?)",
                (username, nickname, _password_hash(payload.password), time.time()),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="该账号已经注册") from exc
        token = _new_session(connection, int(cursor.lastrowid))
        connection.commit()
        return {"token": token, "username": username, "nickname": nickname, "expires_in": 30 * 24 * 3600}
    finally:
        connection.close()


@app.post("/api/v1/auth/login")
def login(payload: AuthPayload) -> dict:
    connection = _db()
    try:
        row = connection.execute(
            "SELECT id,username,nickname,password_hash FROM users WHERE username=? COLLATE NOCASE",
            (payload.username.strip(),),
        ).fetchone()
        if not row or not _password_matches(payload.password, str(row["password_hash"])):
            raise HTTPException(status_code=401, detail="账号或密码错误")
        token = _new_session(connection, int(row["id"]))
        connection.commit()
        return {
            "token": token,
            "username": str(row["username"]),
            "nickname": str(row["nickname"]),
            "expires_in": 30 * 24 * 3600,
        }
    finally:
        connection.close()


@app.get("/api/v1/account/me")
def account_me(user: sqlite3.Row = Depends(current_user)) -> dict:
    return {"id": int(user["id"]), "username": str(user["username"]), "nickname": str(user["nickname"])}


@app.get("/api/v1/community/messages")
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
async def create_job(
    file: UploadFile = File(...),
    arrangement_mode: str = Form("乐队现场版"),
    transpose: int = Form(0),
    output: str = Form("wav_mp3"),
    _: None = Depends(authorize),
) -> dict:
    suffix = Path(file.filename or "audio.mp3").suffix.lower() or ".mp3"
    allowed = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif"}
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail="不支持的音频格式")
    job_id = uuid.uuid4().hex
    name = safe_file_stem(Path(file.filename or "audio").stem)
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
        file_name=file.filename or upload_path.name,
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
            "arrangement_mode": arrangement_mode,
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


@app.get("/api/v1/library")
def library(
    request: Request, q: str = "", category: str = "全部", limit: int = 500,
    _: None = Depends(authorize),
) -> dict:
    songs = list_catalog(LIBRARY_DB, q, category, limit)
    for song in songs:
        track_id = int(song["id"])
        song.pop("source_path", None)
        song.pop("working_path", None)
        song["audio_url"] = str(request.url_for("library_audio", track_id=track_id))
        if song.get("cover_path"):
            song["cover_url"] = str(request.url_for("library_cover", track_id=track_id))
        song.pop("cover_path", None)
    return {"songs": songs, "count": len(songs), "categories": ["全部", "本地导入", "抖音流行", "酷狗排行榜"]}


@app.post("/api/v1/library/scan")
def scan_library(_: None = Depends(authorize)) -> dict:
    result = scan_catalog(LIBRARY_PATHS["originals"], LIBRARY_DB, LIBRARY_PATHS["covers"])
    return {**result, "root": str(LIBRARY_PATHS["root"])}


@app.get("/api/v1/library/{track_id}/audio", name="library_audio")
def library_audio(track_id: int, _: None = Depends(authorize)):
    song = catalog_track(LIBRARY_DB, track_id)
    path = Path(str(song.get("working_path") or song.get("source_path"))) if song else None
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="歌曲文件不存在")
    return FileResponse(path, filename=path.name)


@app.get("/api/v1/library/{track_id}/cover", name="library_cover")
def library_cover(track_id: int, _: None = Depends(authorize)):
    song = catalog_track(LIBRARY_DB, track_id)
    path = Path(str(song.get("cover_path", ""))) if song else None
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="封面不存在")
    return FileResponse(path, filename=path.name)


@app.post("/api/v1/library/{track_id}/process", status_code=202)
def process_library_song(track_id: int, payload: LibraryProcessPayload, _: None = Depends(authorize)) -> dict:
    song = catalog_track(LIBRARY_DB, track_id)
    if not song:
        raise HTTPException(status_code=404, detail="歌曲不存在")
    input_path = Path(str(song.get("working_path") or song.get("source_path")))
    if not input_path.is_file():
        raise HTTPException(status_code=404, detail="歌曲文件不存在")
    queued_id = _queue_job(
        file_name=input_path.name, input_path=input_path,
        arrangement_mode=payload.arrangement_mode, transpose=payload.transpose,
        output=payload.output, library_track_id=track_id,
    )
    return {"job_id": queued_id, "status": "queued"}


def _run_job(job_id: str) -> None:
    job = jobs[job_id]
    input_path = Path(job["input_path"])
    output_root = (
        LIBRARY_PATHS["processed"] / f"{safe_file_stem(input_path.stem)}_{job_id[:8]}"
        if job.get("library_track_id") else OUTPUTS / job_id
    )
    output_root.mkdir(parents=True, exist_ok=True)
    try:
        _update(job_id, status="processing", stage="准备七轨兼容模型", progress=7)
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
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
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
        _update(job_id, stage="BPM / 调性 / 和弦分析", progress=58, artifacts=artifacts)
        analysis, chord_rows = _analyze(input_path)
        analysis, chord_rows = _transpose_analysis(analysis, chord_rows, int(job.get("transpose", 0)))
        artifacts["chords"] = str(_write_chords(output_root, chord_rows))
        _update(job_id, stage="生成五线谱、六线谱及各乐手谱面", progress=72, key=analysis["key"], artifacts=artifacts)
        artifacts.update(_write_scores(output_root, job["file_name"], analysis, chord_rows))
        _update(job_id, stage="生成新 MIDI 编配", progress=88, artifacts=artifacts)
        midi = _write_arrangement(output_root, analysis, chord_rows)
        artifacts["arrangement_midi"] = str(midi)
        _update(job_id, status="completed", stage="全部完成", progress=100, artifacts=artifacts)
    except Exception as exc:
        _update(job_id, status="failed", stage="失败", error=f"{type(exc).__name__}: {exc}")


def _analyze(path: Path) -> tuple[dict, list[dict]]:
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
    return {
        "bpm": round(bpm, 1), "key": key,
        "duration": float(librosa.get_duration(y=y, sr=sample_rate)),
        "melody_notes": melody_notes,
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
    fifths = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6,
              "F": -1, "A#": -2, "D#": -3, "G#": -4, "C#": -5}
    note_steps = {"C": ("C", 0), "C#": ("C", 1), "D": ("D", 0), "D#": ("D", 1),
                  "E": ("E", 0), "F": ("F", 0), "F#": ("F", 1), "G": ("G", 0),
                  "G#": ("G", 1), "A": ("A", 0), "A#": ("A", 1), "B": ("B", 0)}
    measures = []
    melody = list(analysis.get("melody_notes", []))
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
        note_xml = []
        for event in melody[(index - 1) * 4:index * 4]:
            midi = int(event.get("midi", 60))
            pitch = names[midi % 12]
            note_step, note_alter = note_steps[pitch]
            octave = midi // 12 - 1
            alter_note_xml = f"<alter>{note_alter}</alter>" if note_alter else ""
            note_xml.append(
                f"<note><pitch><step>{note_step}</step>{alter_note_xml}<octave>{octave}</octave></pitch>"
                "<duration>1</duration><type>quarter</type></note>"
            )
        if not note_xml:
            note_xml.append("<note><rest/><duration>4</duration><type>whole</type></note>")
        measures.append(
            f'<measure number="{index}">{attributes}<harmony><root><root-step>{step}</root-step>{alter_xml}</root>'
            f'<kind>{kind}</kind></harmony>{"".join(note_xml)}</measure>'
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
    def table(kind: str, hint: str) -> str:
        body = "".join(
            f"<tr><td>{row['bar']}</td><td>{html.escape(row['section'])}</td><td>{html.escape(' / '.join(row['chords']))}</td><td>{html.escape(hint)}</td></tr>"
            for row in rows
        )
        return (
            "<!doctype html><meta charset='utf-8'><style>body{font-family:sans-serif;background:#090d18;color:#fff;padding:24px}"
            "table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #29354d}</style>"
            f"<h1>{html.escape(title)} · {kind}</h1><p>BPM {analysis['bpm']} · {analysis['key']} 调</p>"
            f"<table><tr><th>小节</th><th>段落</th><th>和弦</th><th>演奏提示</th></tr>{body}</table>"
        )

    specs = {
        "lead_sheet": ("和弦谱", "按段落力度演奏"),
        "guitar_tab": ("吉他六线谱参考", "按和弦根音生成分解/扫弦"),
        "bass_score": ("贝斯谱参考", "根音、五度与八度连接"),
        "drum_score": ("鼓谱参考", "Kick / Snare / Hi-Hat，副歌加强"),
        "piano_score": ("键盘谱参考", "左手根音，右手和弦分解"),
    }
    result = {}
    for key, (name, hint) in specs.items():
        path = folder / f"{key}.html"
        path.write_text(table(name, hint), encoding="utf-8")
        result[key] = str(path)
    result["musicxml"] = str(_write_musicxml(folder, title, analysis, rows))
    tuning = [40, 45, 50, 55, 59, 64]
    tab_notes = []
    for note in analysis.get("melody_notes", []):
        midi = int(note.get("midi", 60))
        choices = [(midi - open_note, string + 1) for string, open_note in enumerate(tuning) if 0 <= midi - open_note <= 24]
        fret, string = min(choices, default=(0, 1), key=lambda item: (item[0], -item[1]))
        tab_notes.append({**note, "string": string, "fret": fret})
    score_data = folder / "score_data.json"
    atomic_write_json(score_data, {
        "title": title, "bpm": analysis.get("bpm", 120), "key": analysis.get("key", "C"),
        "duration": analysis.get("duration", 0), "bars": rows,
        "staff_notes": analysis.get("melody_notes", []), "tab_notes": tab_notes,
    })
    result["score_data"] = str(score_data)
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
        public[key] = str(request.url_for("artifact", job_id=result["id"], name=Path(value).name))
    result["artifacts"] = public
    return result


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str, request: Request, _: None = Depends(authorize)) -> dict:
    with lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        return _public_job(job, request)


@app.get("/api/v1/artifacts/{job_id}/{name}", name="artifact")
def artifact(job_id: str, name: str, _: None = Depends(authorize)):
    with lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        candidates = [Path(value) for value in job.get("artifacts", {}).values() if Path(value).name == name]
    if not candidates or not candidates[0].is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(candidates[0], filename=name)
