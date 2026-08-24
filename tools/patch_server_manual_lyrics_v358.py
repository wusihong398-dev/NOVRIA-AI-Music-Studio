from pathlib import Path

path = Path('server/mobile_api.py')
text = path.read_text(encoding='utf-8')
text = text.replace('VERSION = "3.5.0"', 'VERSION = "3.5.8"', 1)

anchor = '@app.get("/api/v1/library/mobile/catalog/{track_id}/lyrics", name="library_mobile_lyrics")'
if anchor not in text:
    raise SystemExit('lyrics route anchor not found')

block = r'''
def _manual_lyrics_text(filename: str, payload: bytes) -> str:
    suffix = Path(filename or "manual.txt").suffix.lower()
    if suffix == ".docx":
        import io
        import zipfile
        import xml.etree.ElementTree as ET
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                xml = archive.read("word/document.xml")
            root = ET.fromstring(xml)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = []
            for p in root.findall(".//w:p", ns):
                value = "".join((node.text or "") for node in p.findall(".//w:t", ns)).strip()
                if value:
                    paragraphs.append(value)
            return "\n".join(paragraphs)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"DOCX 歌词读取失败：{exc}") from exc
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise HTTPException(status_code=400, detail="歌词文件编码无法识别，请使用 UTF-8 TXT/LRC 或 DOCX")


def _manual_lyrics_rows(raw: str, existing: list[dict]) -> list[dict]:
    timestamp = re.compile(r"\[(\d{1,2}):(\d{1,2}(?:\.\d+)?)\](.*)")
    lrc = []
    plain = []
    for source in raw.replace("\r", "\n").split("\n"):
        line = source.strip()
        if not line:
            continue
        match = timestamp.match(line)
        if match:
            start = int(match.group(1)) * 60 + float(match.group(2))
            lyric = match.group(3).strip()
            if lyric:
                lrc.append({"start": start, "text": lyric})
        elif not line.startswith("["):
            plain.append(line)
    if lrc:
        lrc.sort(key=lambda row: float(row["start"]))
        fallback_end = max([float(row.get("end", row.get("start", 0))) for row in existing] or [float(lrc[-1]["start"]) + 4.0])
        rows = []
        for index, row in enumerate(lrc):
            end = float(lrc[index + 1]["start"]) if index + 1 < len(lrc) else max(fallback_end, float(row["start"]) + 2.0)
            rows.append({"start": float(row["start"]), "end": end, "text": str(row["text"])})
        return rows
    if not plain:
        raise HTTPException(status_code=400, detail="歌词文件没有可用歌词文字")
    if existing:
        starts = [float(row.get("start", 0)) for row in existing]
        ends = [float(row.get("end", row.get("start", 0) + 2)) for row in existing]
        total_start = min(starts or [0.0])
        total_end = max(ends or [max(4.0, len(plain) * 3.0)])
    else:
        total_start, total_end = 0.0, max(4.0, len(plain) * 3.0)
    span = max(1.0, total_end - total_start)
    rows = []
    for index, lyric in enumerate(plain):
        start = total_start + span * index / len(plain)
        end = total_start + span * (index + 1) / len(plain)
        rows.append({"start": start, "end": end, "text": lyric})
    return rows


def _manual_lyric_units(rows: list[dict]) -> list[dict]:
    units = []
    for line_index, row in enumerate(rows):
        chars = [char for char in str(row.get("text", "")) if not char.isspace()]
        if not chars:
            continue
        start = float(row.get("start", 0))
        end = max(start + 0.05, float(row.get("end", start + 2)))
        step = (end - start) / len(chars)
        for index, char in enumerate(chars):
            units.append({"line": line_index, "index": index, "text": char, "start": start + step * index, "end": start + step * (index + 1)})
    return units


@app.post("/api/v1/library/mobile/catalog/{track_id}/manual-lyrics")
async def library_manual_lyrics(
    track_id: int,
    file: UploadFile = File(...),
    x_admin_key: str = Header(default="", alias="X-Admin-Key"),
):
    expected = os.environ.get("ADMIN_KEY", "").strip() or TOKEN
    if not expected or not hmac.compare_digest(x_admin_key.strip(), expected):
        raise HTTPException(status_code=401, detail="管理员密钥错误")
    payload = await file.read()
    if not payload or len(payload) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="歌词文件为空或超过 2MB")
    song = catalog_track(LIBRARY_DB, track_id)
    if not song:
        raise HTTPException(status_code=404, detail="歌曲不存在")
    artifacts = _recover_published_artifacts(song)
    timeline_path = Path(str(artifacts.get("lyrics_timeline") or ""))
    score_path = Path(str(artifacts.get("score_data") or ""))
    if not timeline_path.is_file():
        raise HTTPException(status_code=409, detail="该歌曲还没有可用于对齐的歌词时间轴")
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    existing = list(timeline.get("rows") or [])
    raw = _manual_lyrics_text(file.filename or "manual.txt", payload)
    rows = _manual_lyrics_rows(raw, existing)
    units = _manual_lyric_units(rows)
    backup = timeline_path.with_suffix(timeline_path.suffix + ".ai.bak")
    if not backup.exists():
        shutil.copy2(timeline_path, backup)
    atomic_write_json(timeline_path, {
        "rows": rows,
        "units": units,
        "status": "manual",
        "source": "manual",
        "language": "人工校正",
        "message": "人工歌词优先；时间轴已同步",
    })
    if score_path.is_file():
        score = json.loads(score_path.read_text(encoding="utf-8"))
        score_backup = score_path.with_suffix(score_path.suffix + ".ai.bak")
        if not score_backup.exists():
            shutil.copy2(score_path, score_backup)
        score["lyrics"] = rows
        score["lyric_units"] = units
        score["lyrics_status"] = "manual"
        score["lyrics_source"] = "manual"
        score["lyrics_language"] = "人工校正"
        score["lyrics_message"] = "人工歌词优先；时间轴已同步"
        atomic_write_json(score_path, score)
    bump_catalog_version(LIBRARY_DB)
    return {"ok": True, "track_id": track_id, "rows": len(rows), "units": len(units), "source": "manual", "filename": file.filename}


'''
text = text.replace(anchor, block + anchor, 1)
path.write_text(text, encoding='utf-8')
print('PATCH_SERVER_MANUAL_LYRICS_V358_OK')
