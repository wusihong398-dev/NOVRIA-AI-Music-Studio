"""Mobile API companion for 橘味儿音乐 v2.1.7.

Run this on the Windows/GPU computer. Android and iOS clients upload source
audio here; Demucs and the analysis pipeline remain on the capable computer.
"""

from __future__ import annotations

import copy
import html
import json
import os
import re
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

from app.project_utils import atomic_write_json, safe_file_stem


APP_NAME = "橘味儿音乐"
VERSION = "2.1.7"
ROOT = Path(os.environ.get("JUWEIER_DATA_DIR", Path.cwd() / "mobile_server_data")).resolve()
UPLOADS = ROOT / "uploads"
OUTPUTS = ROOT / "outputs"
STATE_FILE = ROOT / "jobs.json"
TOKEN = os.environ.get("JUWEIER_API_TOKEN", "").strip()
for folder in (UPLOADS, OUTPUTS):
    folder.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=f"{APP_NAME} Mobile API", version=VERSION)
lock = threading.RLock()
executor = ThreadPoolExecutor(max_workers=max(1, int(os.environ.get("JUWEIER_WORKERS", "1"))))


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


def authorize(authorization: str | None = Header(default=None)) -> None:
    if not TOKEN:
        return
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="无效的访问令牌")


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

    now = time.time()
    with lock:
        jobs[job_id] = {
            "id": job_id,
            "file_name": file.filename or upload_path.name,
            "input_path": str(upload_path),
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
    return {"job_id": job_id, "status": "queued"}


def _run_job(job_id: str) -> None:
    job = jobs[job_id]
    input_path = Path(job["input_path"])
    output_root = OUTPUTS / job_id
    output_root.mkdir(parents=True, exist_ok=True)
    try:
        _update(job_id, status="processing", stage="准备六轨模型", progress=7)
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
                    _update(job_id, stage=str(message.get("text", "六轨分离")), progress=15 + value * 0.40)
                elif kind == "done":
                    stem_dir = str(message.get("stem_dir", ""))
                elif kind == "failed":
                    last_error = str(message.get("error", "六轨分离失败"))
        code = process.wait()
        if code != 0 or not stem_dir:
            raise RuntimeError(last_error or f"六轨 Worker 退出码 {code}")

        artifacts = {f"stem_{p.stem}": str(p) for p in Path(stem_dir).glob("*.wav")}
        _update(job_id, stage="BPM / 调性 / 和弦分析", progress=58, artifacts=artifacts)
        analysis, chord_rows = _analyze(input_path)
        analysis, chord_rows = _transpose_analysis(analysis, chord_rows, int(job.get("transpose", 0)))
        artifacts["chords"] = str(_write_chords(output_root, chord_rows))
        _update(job_id, stage="生成各乐手谱面", progress=72, key=analysis["key"], artifacts=artifacts)
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
    return {"bpm": round(bpm, 1), "key": key}, rows


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
    for index, row in enumerate(rows or [{"chords": [analysis.get("key", "C")]}], start=1):
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
        measures.append(
            f'<measure number="{index}">{attributes}<harmony><root><root-step>{step}</root-step>{alter_xml}</root>'
            f'<kind>{kind}</kind></harmony><note><rest/><duration>4</duration><type>whole</type></note></measure>'
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
