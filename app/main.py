
import sys
import sqlite3
import shutil
import shlex
import mimetypes
import urllib.request
import urllib.parse
import hashlib
import os
import subprocess
import webbrowser
import html
import re
import queue
import wave
import math
import threading
import time, json, subprocess, traceback, platform, urllib.request, hashlib, io, os
from pathlib import Path

from app.project_utils import (
    atomic_write_json,
    normalized_path,
    repair_text,
    safe_file_stem,
    unique_import_candidates,
    load_synced_lyrics,
    split_guitar_stem,
)
from app.library_catalog import (
    AUDIO_EXTENSIONS,
    connect_catalog,
    default_library_root,
    ensure_library_layout,
    list_catalog,
    scan_catalog,
    scan_catalog_roots,
    download_public_audio,
)

import numpy as np
import sounddevice as sd
import soundfile as sf

from PySide6.QtCore import QFileInfo, Qt, QSize, QThread, Signal, QTimer, QPointF, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QCloseEvent, QIcon, QPixmap, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QSlider, QGroupBox, QMessageBox, QProgressBar,
    QListWidget, QListWidgetItem, QStackedWidget, QGridLayout, QDialogButtonBox, QTableWidget, QTableWidgetItem, QTabWidget, QRadioButton, QFileSystemModel, QTreeWidgetItem, QTreeWidget, QPlainTextEdit, QButtonGroup, QTextBrowser, QSpinBox, QDoubleSpinBox, QDialog, QFormLayout, QLineEdit, QComboBox, QCheckBox, QInputDialog
)

APP_NAME = "橘味儿音乐"
VERSION = "3.2.0"
STEM_ORDER = [
    ("vocals", "🎤", "人声 Vocal"),
    ("drums", "🥁", "鼓 Drums"),
    ("bass", "🎸", "贝斯 Bass"),
    ("guitar", "🎸", "木吉他 A.Guitar"),
    ("electric_guitar", "🎸", "电吉他 E.Guitar"),
    ("piano", "🎹", "钢琴 Piano"),
    ("other", "🎻", "其他 Other"),
]

BASE_DIR = Path(__file__).resolve().parent.parent
STEMS_DIR = BASE_DIR / "stems"
PROJECTS_DIR = BASE_DIR / "projects"
EXPORTS_DIR = BASE_DIR / "exports"

ASSETS_DIR = BASE_DIR / "assets"
ICONS_DIR = ASSETS_DIR / "icons"

def asset_path(*parts):
    return str(ASSETS_DIR.joinpath(*parts))

def icon_path(name):
    return str(ICONS_DIR / f"{name}.png")

def apply_button_accent(button, accent):
    button.setProperty("accent", accent)
    button.style().unpolish(button)
    button.style().polish(button)


class SeparationWorker(QThread):
    log = Signal(str)
    model_progress = Signal(int, str)
    separation_progress = Signal(int, str)
    done = Signal(str)
    failed = Signal(str)

    MODEL_URL = "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/5c90dfd2-34c22ccb.th"
    MODEL_FILE = "5c90dfd2-34c22ccb.th"
    MODEL_HASH_PREFIX = "34c22ccb"

    def __init__(self, input_file: str):
        super().__init__()
        self.input_file = input_file

    def _safe_streams(self):
        # PyInstaller windowed EXE 中 sys.stdout/sys.stderr 可能为 None。
        # 某些三方库仍会尝试 write()，因此提供安全的内存输出流兜底。
        if sys.stdout is None:
            sys.stdout = io.StringIO()
        if sys.stderr is None:
            sys.stderr = io.StringIO()

    def _sha256_ok(self, path: Path) -> bool:
        sha = hashlib.sha256()
        with path.open('rb') as f:
            while True:
                b = f.read(1024 * 1024)
                if not b:
                    break
                sha.update(b)
        return sha.hexdigest().startswith(self.MODEL_HASH_PREFIX)

    def _ensure_model(self):
        import torch
        cache_dir = Path(torch.hub.get_dir()) / "checkpoints"
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / self.MODEL_FILE

        if target.exists():
            self.model_progress.emit(5, "检测本地 AI 模型...")
            try:
                if self._sha256_ok(target):
                    self.model_progress.emit(100, "AI 六轨模型已安装，无需重复下载")
                    return target
            except Exception:
                pass
            try:
                target.unlink()
            except Exception:
                pass

        part = target.with_suffix(target.suffix + ".part")
        if part.exists():
            try:
                part.unlink()
            except Exception:
                pass

        self.log.emit("首次使用：正在下载 Demucs htdemucs_6s AI 六轨模型...")
        self.model_progress.emit(0, "连接 AI 模型服务器...")

        req = urllib.request.Request(
            self.MODEL_URL,
            headers={"User-Agent": "Juweier-Music/3.2.0"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp, part.open("wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            while True:
                chunk = resp.read(1024 * 512)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = min(99, int(downloaded * 100 / total))
                    mb1 = downloaded / 1024 / 1024
                    mb2 = total / 1024 / 1024
                    self.model_progress.emit(pct, f"下载 AI 模型 {pct}%  ({mb1:.1f}/{mb2:.1f} MB)")
                else:
                    self.model_progress.emit(0, f"已下载 {downloaded/1024/1024:.1f} MB")

        self.model_progress.emit(99, "正在校验 AI 模型完整性...")
        if not self._sha256_ok(part):
            try:
                part.unlink()
            except Exception:
                pass
            raise RuntimeError("AI 模型校验失败，下载文件可能不完整，请重新下载。")

        os.replace(part, target)
        self.model_progress.emit(100, "AI 六轨模型下载完成")
        return target

    def _separation_callback(self, info: dict):
        try:
            audio_length = max(1, int(info.get("audio_length", 1)))
            offset = max(0, int(info.get("segment_offset", 0)))
            state = info.get("state", "start")
            pct = int(min(98, max(0, offset * 100 / audio_length)))
            if state == "end":
                pct = min(99, pct + 1)
            self.separation_progress.emit(pct, f"AI 六轨分离中 {pct}%")
        except Exception:
            pass

    def run(self):
        try:
            self._safe_streams()
            out_dir = STEMS_DIR
            out_dir.mkdir(parents=True, exist_ok=True)

            # 1) 模型下载由 NOVRIA 自己管理，因此 GUI EXE 不再触发
            # torch.hub 在 None stdout 上写进度导致的崩溃。
            self._ensure_model()

            self.separation_progress.emit(0, "正在初始化六轨 AI 引擎...")
            self.log.emit("正在加载 Demucs htdemucs_6s 六轨模型...")

            import torch
            from demucs.api import Separator, save_audio

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.log.emit(f"AI 运算设备：{device.upper()}")

            separator = Separator(
                model="htdemucs_6s",
                device=device,
                shifts=1,
                overlap=0.25,
                split=True,
                jobs=0,
                progress=False,
                callback=self._separation_callback,
            )

            self.separation_progress.emit(1, "正在读取歌曲并开始六轨分离...")
            _, separated = separator.separate_audio_file(Path(self.input_file))

            song_name = Path(self.input_file).stem
            stem_dir = out_dir / "htdemucs_6s" / song_name
            stem_dir.mkdir(parents=True, exist_ok=True)

            # 推理结束后保存六条独立 WAV；保存阶段占最后约 10%。
            stems = list(separated.items())
            count = max(1, len(stems))
            for i, (stem, source) in enumerate(stems, start=1):
                pct = 90 + int((i - 1) * 9 / count)
                self.separation_progress.emit(pct, f"正在保存 {stem}.wav ({i}/{count})")
                save_audio(
                    source,
                    str(stem_dir / f"{stem}.wav"),
                    samplerate=separator.samplerate,
                    bits_per_sample=24,
                )

            expected = ["vocals", "drums", "bass", "guitar", "piano", "other"]
            missing = [x for x in expected if not (stem_dir / f"{x}.wav").exists()]
            if missing:
                raise RuntimeError("分轨结果缺少：" + ", ".join(missing))

            self.separation_progress.emit(97, "正在二次识别木吉他与电吉他...")
            guitar_diagnostics = split_guitar_stem(stem_dir)
            self.separation_progress.emit(100, "六轨基础分离 + 电吉他二次分离完成")
            self.log.emit(
                "AI 六轨模型处理完成；已从吉他轨生成独立木吉他与电吉他轨。"
                f" 电吉他活跃度 {guitar_diagnostics['electric_activity']:.0%}。"
            )
            self.done.emit(str(stem_dir))
        except Exception as e:
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")


class PipelineStageWorker(QThread):
    """Run CPU-heavy non-Qt stages without freezing the interface."""

    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    def run(self):
        try:
            self.operation()
            self.succeeded.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")


class LinkDownloadWorker(QThread):
    progress = Signal(int, str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, url, destination, ffmpeg_path=""):
        super().__init__()
        self.url = str(url).strip()
        self.destination = Path(destination)
        self.ffmpeg_path = str(ffmpeg_path or "")

    def run(self):
        try:
            path = download_public_audio(
                self.url, self.destination, self.ffmpeg_path,
                lambda value, text: self.progress.emit(int(value), str(text)),
            )
            self.done.emit(str(path))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MultiStemEngine:
    def __init__(self):
        self.files = {}
        self.stream = None
        self.sample_rate = 44100
        self.channels = 2
        self.playing = False
        self.paused = False
        self.mute = {k: False for k, _, _ in STEM_ORDER}
        self.solo = {k: False for k, _, _ in STEM_ORDER}
        self.volume = {k: 0.9 for k, _, _ in STEM_ORDER}
        self.frames_played = 0
        self.total_frames = 0
        self.speed = 1.0
        self._io_lock = threading.RLock()

    def load(self, stem_dir: Path):
        self.close()
        paths = {}
        for key, _, _ in STEM_ORDER:
            p = stem_dir / f"{key}.wav"
            if not p.exists():
                if key == "electric_guitar":
                    continue
                raise FileNotFoundError(f"缺少音轨：{p.name}")
            paths[key] = p

        info = sf.info(str(paths["vocals"]))
        self.sample_rate = info.samplerate
        self.channels = info.channels
        self.total_frames = info.frames
        self.frames_played = 0

        for key, p in paths.items():
            f = sf.SoundFile(str(p), "r")
            if f.samplerate != self.sample_rate or f.channels != self.channels:
                f.close()
                raise RuntimeError(f"{key}.wav 的采样率或声道与其他音轨不一致")
            self.files[key] = f

    def _callback(self, outdata, frames, time_info, status):
        if self.paused or not self.playing:
            outdata.fill(0)
            return

        solos = [k for k, v in self.solo.items() if v]
        active = set(solos) if solos else {k for k in self.files if not self.mute[k]}

        source_frames = max(1, int(math.ceil(frames * self.speed)))
        mix = np.zeros((frames, self.channels), dtype=np.float32)
        valid_frames = frames

        with self._io_lock:
            for key, f in self.files.items():
                data = f.read(source_frames, dtype="float32", always_2d=True)
                n = len(data)
                output_count = min(frames, max(0, int(n / self.speed)))
                valid_frames = min(valid_frames, output_count)
                if key in active and n and output_count:
                    if n == output_count:
                        rendered = data
                    else:
                        old_positions = np.arange(n, dtype=np.float32)
                        new_positions = np.linspace(0, max(0, n - 1), output_count, dtype=np.float32)
                        rendered = np.column_stack([
                            np.interp(new_positions, old_positions, data[:, channel])
                            for channel in range(self.channels)
                        ]).astype(np.float32)
                    mix[:output_count] += rendered * float(self.volume[key])
            if self.files:
                self.frames_played = min(int(f.tell()) for f in self.files.values())

        if valid_frames <= 0:
            outdata.fill(0)
            self.playing = False
            raise sd.CallbackStop()

        # 简单防削波。后续版本会换成 limiter / master bus。
        peak = float(np.max(np.abs(mix))) if mix.size else 0.0
        if peak > 1.0:
            mix /= peak

        outdata[:] = mix
        if valid_frames < frames:
            outdata[valid_frames:] = 0
            self.playing = False
            raise sd.CallbackStop()

    def play(self):
        if not self.files:
            raise RuntimeError("还没有加载分轨。")
        if self.stream is None:
            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                blocksize=1024,
                callback=self._callback
            )
            self.stream.start()
        self.playing = True
        self.paused = False

    def pause(self):
        self.paused = True

    def resume(self):
        if not self.files:
            return
        if self.stream is None:
            self.play()
        else:
            self.playing = True
            self.paused = False

    def stop(self):
        self.playing = False
        self.paused = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        for f in self.files.values():
            try:
                f.seek(0)
            except Exception:
                pass
        self.frames_played = 0

    def close(self):
        self.stop()
        for f in self.files.values():
            try:
                f.close()
            except Exception:
                pass
        self.files = {}

    def seek_ratio(self, ratio: float):
        if not self.files or self.total_frames <= 0:
            return
        pos = int(max(0.0, min(1.0, ratio)) * self.total_frames)
        with self._io_lock:
            for f in self.files.values():
                f.seek(pos)
            self.frames_played = pos

    def set_speed(self, value: float):
        self.speed = max(0.5, min(1.5, float(value)))

    def position_seconds(self):
        return self.frames_played / self.sample_rate if self.sample_rate else 0

    def duration_seconds(self):
        return self.total_frames / self.sample_rate if self.sample_rate else 0

class TrackRow(QWidget):
    changed = Signal()
    def __init__(self, key, icon, name):
        super().__init__()
        self.key = key
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)

        label = QLabel(f"{icon}  {name}")
        track_colors = {"vocals":"#B071FF","drums":"#FF8B3D","bass":"#3CA8FF","guitar":"#75E44C","electric_guitar":"#FF5B65","piano":"#35D6D0","other":"#F4C04C"}
        label.setStyleSheet(f"font-weight:700;color:{track_colors.get(key, '#EAF0FF')};")
        label.setMinimumWidth(170)
        self.mute = QPushButton("M")
        self.mute.setCheckable(True)
        self.mute.setFixedWidth(42)
        self.solo = QPushButton("S")
        self.solo.setCheckable(True)
        self.solo.setFixedWidth(42)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 120)
        self.volume.setValue(90)
        self.value_label = QLabel("90%")
        self.value_label.setFixedWidth(45)

        self.mute.toggled.connect(lambda _: self.changed.emit())
        self.solo.toggled.connect(lambda _: self.changed.emit())
        self.volume.valueChanged.connect(self.on_volume)

        layout.addWidget(label)
        layout.addWidget(self.mute)
        layout.addWidget(self.solo)
        layout.addWidget(QLabel("音量"))
        layout.addWidget(self.volume, 1)
        layout.addWidget(self.value_label)

    def on_volume(self, v):
        self.value_label.setText(f"{v}%")
        self.changed.emit()

class StudioPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        layout = QVBoxLayout(self)

        title = QLabel("AI 六轨分离 + 电吉他二次分离 / 多轨工作台")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        file_row = QHBoxLayout()
        self.file_label = QLabel("尚未导入歌曲")
        btn_import = QPushButton(QIcon(icon_path("import")), "导入歌曲")
        btn_import.clicked.connect(main.import_song)
        self.btn_split = QPushButton(QIcon(icon_path("split")), "AI 六轨分离 + 电吉他二次分离")
        apply_button_accent(self.btn_split, "primary")
        self.btn_split.clicked.connect(main.start_separation)
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(btn_import)
        file_row.addWidget(self.btn_split)
        layout.addLayout(file_row)

        transport = QHBoxLayout()
        self.play_btn = QPushButton(QIcon(icon_path("play")), "播放")
        apply_button_accent(self.play_btn, "primary")
        self.play_btn.clicked.connect(main.play_pause)
        stop_btn = QPushButton(QIcon(icon_path("stop")), "停止")
        apply_button_accent(stop_btn, "danger")
        stop_btn.clicked.connect(main.stop)
        self.timeline = QSlider(Qt.Horizontal)
        self.timeline.setRange(0, 1000)
        self.timeline.sliderPressed.connect(main.begin_timeline_seek)
        self.timeline.sliderMoved.connect(main.preview_timeline_seek)
        self.timeline.sliderReleased.connect(main.seek_from_slider)
        self.time_label = QLabel("00:00 / 00:00")
        transport.addWidget(self.play_btn)
        transport.addWidget(stop_btn)
        transport.addWidget(self.timeline, 1)
        transport.addWidget(self.time_label)
        layout.addLayout(transport)

        self.waveform = WaveformWidget()
        self.waveform.seekRequested.connect(main.seek_ratio_direct)
        layout.addWidget(self.waveform)

        analysis_row = QHBoxLayout()
        self.bpm_label = QLabel("BPM：未分析")
        self.key_label = QLabel("调性：未分析")
        analyze_btn = QPushButton("分析 BPM / 调性")
        analyze_btn.clicked.connect(main.analyze_music)
        add_marker_btn = QPushButton("当前位置添加 Marker")
        add_marker_btn.clicked.connect(main.add_marker)
        analysis_row.addWidget(self.bpm_label)
        analysis_row.addWidget(self.key_label)
        analysis_row.addWidget(analyze_btn)
        analysis_row.addWidget(add_marker_btn)
        analysis_row.addStretch(1)
        layout.addLayout(analysis_row)


        box = QGroupBox("真实独立 Stem 混音器")
        box_l = QVBoxLayout(box)
        self.rows = {}
        for key, icon, name in STEM_ORDER:
            row = TrackRow(key, icon, name)
            row.changed.connect(main.sync_mix_controls)
            self.rows[key] = row
            box_l.addWidget(row)
        layout.addWidget(box)

        model_box = QGroupBox("AI 模型")
        model_l = QVBoxLayout(model_box)
        self.model_status = QLabel("首次使用时会下载 htdemucs_6s；电吉他轨支持二次识别结果")
        self.model_progress = QProgressBar()
        self.model_progress.setRange(0, 100)
        self.model_progress.setValue(0)
        self.model_progress.setFormat("模型下载 %p%")
        model_l.addWidget(self.model_status)
        model_l.addWidget(self.model_progress)
        layout.addWidget(model_box)

        split_box = QGroupBox("六轨基础分离与电吉他二次识别进度")
        split_l = QVBoxLayout(split_box)
        self.split_status = QLabel("等待开始")
        self.split_progress = QProgressBar()
        self.split_progress.setRange(0, 100)
        self.split_progress.setValue(0)
        self.split_progress.setFormat("分轨处理 %p%")
        split_l.addWidget(self.split_status)
        split_l.addWidget(self.split_progress)
        layout.addWidget(split_box)

        self.log = QLabel("等待任务...")
        self.log.setWordWrap(True)
        self.log.setMinimumHeight(60)
        layout.addWidget(self.log)

        bottom = QHBoxLayout()
        save = QPushButton("保存工程")
        save.clicked.connect(main.save_project)
        export = QPushButton(QIcon(icon_path("export")), "导出当前混音 WAV")
        apply_button_accent(export, "success")
        export.clicked.connect(main.export_mix)
        bottom.addWidget(save)
        bottom.addWidget(export)
        bottom.addStretch(1)
        layout.addLayout(bottom)

class LivePage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        layout = QVBoxLayout(self)

        title = QLabel("现场演出模式")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        info = QLabel(
            "AI 分轨只在演出前完成；正式演出时直接读取本地 Stem。\n"
            "选择演出身份后，对应乐器会立即静音，其他轨道继续保持同一时间轴同步播放。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        grid = QGridLayout()
        presets = [
            ("🎸 吉他弹唱", "guitar"),
            ("🎹 钢琴弹唱", "piano"),
            ("🥁 鼓手演出", "drums"),
            ("🎸 贝斯演出", "bass"),
            ("🎤 纯伴奏/KTV", "vocals"),
            ("🎼 全部恢复", None),
        ]
        for i, (text, key) in enumerate(presets):
            b = QPushButton(text)
            b.setMinimumHeight(60)
            b.clicked.connect(lambda checked=False, k=key: main.apply_live_preset(k))
            grid.addWidget(b, i//2, i%2)
        layout.addLayout(grid)

        
        count_box = QGroupBox("起奏辅助")
        cl = QHBoxLayout(count_box)
        self.count_in = QCheckBox("4拍 Count-in（界面倒计时）")
        self.count_in.setChecked(True)
        self.count_label = QLabel("READY")
        self.count_label.setStyleSheet("font-size:28px;font-weight:900")
        count_btn = QPushButton("4拍倒计时后开始")
        count_btn.clicked.connect(self.start_count_in)
        cl.addWidget(self.count_in)
        cl.addWidget(self.count_label)
        cl.addWidget(count_btn)
        layout.addWidget(count_box)

        self.status = QLabel("当前预设：全部音轨开启")
        self.status.setObjectName("StatusGood")
        layout.addWidget(self.status)

        play = QPushButton("▶ 开始 / 暂停现场播放")
        play.setMinimumHeight(60)
        play.clicked.connect(main.play_pause)
        layout.addWidget(play)
        layout.addStretch(1)


    def start_count_in(self):
        if not self.count_in.isChecked():
            self.main.play_pause()
            return
        self._count = 4
        self.count_label.setText(str(self._count))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(700)

    def _tick(self):
        self._count -= 1
        if self._count <= 0:
            self._timer.stop()
            self.count_label.setText("GO")
            self.main.play_pause()
            QTimer.singleShot(1200, lambda: self.count_label.setText("READY"))
        else:
            self.count_label.setText(str(self._count))


class Placeholder(QWidget):
    def __init__(self, text):
        super().__init__()
        l = QVBoxLayout(self)
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size:22px")
        l.addWidget(label)


class SettingsPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        layout = QVBoxLayout(self)
        title = QLabel("音频 / GPU / 现场设置")
        title.setStyleSheet("font-size:24px;font-weight:800")
        layout.addWidget(title)

        gpu_box = QGroupBox("AI 运算设备")
        gl = QVBoxLayout(gpu_box)
        self.gpu_status = QLabel("尚未检测")
        detect = QPushButton("检测 NVIDIA GPU / CUDA")
        detect.clicked.connect(self.detect_gpu)
        gl.addWidget(self.gpu_status)
        gl.addWidget(detect)
        layout.addWidget(gpu_box)

        audio_box = QGroupBox("现场音频设备")
        al = QGridLayout(audio_box)
        self.output_combo = QComboBox()
        self.refresh_audio_devices()
        refresh = QPushButton("刷新设备")
        refresh.clicked.connect(self.refresh_audio_devices)
        self.block_combo = QComboBox()
        self.block_combo.addItems(["256", "512", "1024", "2048"])
        self.block_combo.setCurrentText("1024")
        al.addWidget(QLabel("主输出设备"), 0, 0)
        al.addWidget(self.output_combo, 0, 1)
        al.addWidget(refresh, 0, 2)
        al.addWidget(QLabel("音频缓冲 Blocksize"), 1, 0)
        al.addWidget(self.block_combo, 1, 1)
        layout.addWidget(audio_box)

        live_box = QGroupBox("现场安全")
        ll = QVBoxLayout(live_box)
        self.offline = QCheckBox("演出模式优先使用本地 Stem，不依赖网络")
        self.offline.setChecked(True)
        self.prevent_sleep = QCheckBox("演出时建议关闭系统睡眠/自动休眠")
        self.prevent_sleep.setChecked(True)
        ll.addWidget(self.offline)
        ll.addWidget(self.prevent_sleep)
        layout.addWidget(live_box)
        layout.addStretch(1)

    def refresh_audio_devices(self):
        current = self.output_combo.currentText() if hasattr(self, "output_combo") else ""
        if hasattr(self, "output_combo"):
            self.output_combo.clear()
        try:
            devices = sd.query_devices()
            for i, d in enumerate(devices):
                if d["max_output_channels"] > 0:
                    self.output_combo.addItem(f'{i}: {d["name"]}', i)
            if current:
                idx = self.output_combo.findText(current)
                if idx >= 0:
                    self.output_combo.setCurrentIndex(idx)
        except Exception as e:
            self.output_combo.addItem("设备读取失败")

    def detect_gpu(self):
        lines = [f"系统：{platform.system()} {platform.release()}"]
        try:
            p = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                                "--format=csv,noheader"], capture_output=True, text=True, timeout=8)
            if p.returncode == 0 and p.stdout.strip():
                lines.append("NVIDIA GPU：" + p.stdout.strip())
            else:
                lines.append("未检测到可用的 nvidia-smi。")
        except Exception:
            lines.append("未检测到 NVIDIA 驱动或 nvidia-smi。")
        try:
            import torch
            lines.append(f"PyTorch：{torch.__version__}")
            lines.append(f"CUDA可用：{'是' if torch.cuda.is_available() else '否'}")
            if torch.cuda.is_available():
                lines.append(f"CUDA设备：{torch.cuda.get_device_name(0)}")
        except Exception:
            lines.append("PyTorch：尚未安装/无法读取")
        self.gpu_status.setText("\n".join(lines))


class WaveformWidget(QWidget):
    """轻量波形显示，不依赖额外绘图库。"""
    seekRequested = Signal(float)

    def __init__(self):
        super().__init__()
        self.samples = []
        self.position = 0.0
        self.markers = []
        self.setMinimumHeight(120)

    def set_waveform_from_wav(self, path):
        self.samples = []
        try:
            data, sr = sf.read(str(path), dtype="float32", always_2d=True)
            if len(data) == 0:
                return
            mono = np.mean(data, axis=1)
            target = 1200
            step = max(1, len(mono)//target)
            for i in range(0, len(mono), step):
                chunk = mono[i:i+step]
                if len(chunk):
                    self.samples.append(float(np.max(np.abs(chunk))))
        except Exception:
            self.samples = []
        self.update()

    def set_position(self, ratio):
        self.position = max(0.0, min(1.0, ratio))
        self.update()

    def set_markers(self, markers):
        self.markers = markers or []
        self.update()

    def mousePressEvent(self, event):
        if self.width() > 0:
            ratio = max(0.0, min(1.0, event.position().x()/self.width()))
            self.seekRequested.emit(ratio)

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(24, 27, 33))
        mid = h/2
        if self.samples:
            pen = QPen(QColor(120, 180, 240))
            p.setPen(pen)
            n = len(self.samples)
            for x in range(w):
                idx = min(n-1, int(x*n/max(1,w)))
                amp = self.samples[idx] * (h*0.42)
                p.drawLine(x, int(mid-amp), x, int(mid+amp))
        # markers
        for m in self.markers:
            try:
                ratio = float(m.get("ratio", 0))
                x = int(ratio*w)
                p.setPen(QPen(QColor(240, 190, 80)))
                p.drawLine(x, 0, x, h)
                p.drawText(x+3, 14, str(m.get("name","")))
            except Exception:
                pass
        # playhead
        p.setPen(QPen(QColor(255,255,255), 2))
        x = int(self.position*w)
        p.drawLine(x, 0, x, h)


class MarkerDialog(QDialog):
    def __init__(self, parent=None, default_name="副歌"):
        super().__init__(parent)
        self.setWindowTitle("添加段落 Marker")
        lay = QFormLayout(self)
        self.name_edit = QLineEdit(default_name)
        lay.addRow("名称", self.name_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addRow(buttons)

    def name(self):
        return self.name_edit.text().strip() or "Marker"




class MetronomeEngine:
    """独立耳返节拍器，可输出到指定声卡，不进入主扩。"""
    def __init__(self):
        self.stream = None
        self.device = None
        self.bpm = 120.0
        self.sample_rate = 44100
        self.enabled = False
        self.frame_pos = 0
        self.click_frames = int(self.sample_rate * 0.035)

    def start(self, device=None, bpm=120.0):
        self.stop()
        self.device = device
        self.bpm = max(30.0, min(300.0, float(bpm or 120.0)))
        self.enabled = True
        self.frame_pos = 0
        self.stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=2,
            dtype="float32",
            blocksize=512,
            device=device,
            callback=self._callback
        )
        self.stream.start()

    def _callback(self, outdata, frames, time_info, status):
        outdata.fill(0)
        if not self.enabled:
            return
        beat_interval = int(self.sample_rate * 60.0 / self.bpm)
        for i in range(frames):
            absolute = self.frame_pos + i
            phase = absolute % beat_interval
            if phase < self.click_frames:
                # 短衰减 click；只送耳返设备。
                env = 1.0 - (phase / max(1, self.click_frames))
                tone = math.sin(2.0 * math.pi * 1200.0 * phase / self.sample_rate)
                v = float(0.24 * env * tone)
                outdata[i,0] = v
                outdata[i,1] = v
        self.frame_pos += frames

    def stop(self):
        self.enabled = False
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
        self.stream = None


class MidiWorker(QThread):
    action = Signal(str)
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        try:
            import mido
            names = mido.get_input_names()
            if not names:
                self.status.emit("未检测到 MIDI 输入设备")
                return
            self.status.emit("MIDI 已连接：" + names[0])
            # 默认采用第一个输入设备。后续可增加设备选择。
            with mido.open_input(names[0]) as port:
                while self._running:
                    msg = port.poll()
                    if msg is not None and getattr(msg, "type", "") in ("note_on", "control_change"):
                        if msg.type == "note_on" and getattr(msg, "velocity", 0) == 0:
                            continue
                        code = getattr(msg, "note", None)
                        if code is None:
                            code = getattr(msg, "control", None)
                        mapping = {
                            36: "play_pause",
                            37: "stop",
                            38: "next",
                            39: "previous",
                        }
                        if code in mapping:
                            self.action.emit(mapping[code])
                    self.msleep(10)
        except Exception as e:
            self.status.emit("MIDI 监听失败：" + str(e))


class SetlistPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.items = []
        layout = QVBoxLayout(self)

        title = QLabel("Setlist 演出歌单")
        title.setStyleSheet("font-size:24px;font-weight:800")
        layout.addWidget(title)

        bar = QHBoxLayout()
        add_btn = QPushButton("添加歌曲")
        add_btn.clicked.connect(self.add_song)
        remove_btn = QPushButton("删除所选")
        remove_btn.clicked.connect(self.remove_selected)
        up_btn = QPushButton("上移")
        up_btn.clicked.connect(lambda: self.move_selected(-1))
        down_btn = QPushButton("下移")
        down_btn.clicked.connect(lambda: self.move_selected(1))
        load_btn = QPushButton("载入所选歌曲")
        load_btn.clicked.connect(self.load_selected)
        self.auto_next = QCheckBox("播放结束自动下一首")
        self.auto_next.setChecked(True)
        for w in [add_btn, remove_btn, up_btn, down_btn, load_btn, self.auto_next]:
            bar.addWidget(w)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["序号","歌曲","模式","调性","速度"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        tips = QLabel("建议演出前先把所有歌曲完成 AI 分轨并保存工程，现场只读取本地 Stem。")
        tips.setWordWrap(True)
        layout.addWidget(tips)

    def add_song(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "添加演出歌曲", "", "音频 (*.mp3 *.wav *.flac *.m4a *.aac)"
        )
        for p in files:
            if p not in [x["path"] for x in self.items]:
                self.items.append({"path":p,"mode":"全部开启","key":"原调","speed":"100%"})
        self.refresh()

    def refresh(self):
        self.table.setRowCount(len(self.items))
        for i, item in enumerate(self.items):
            vals = [str(i+1), Path(item["path"]).name, item["mode"], item["key"], item["speed"]]
            for c,v in enumerate(vals):
                self.table.setItem(i,c,QTableWidgetItem(v))

    def remove_selected(self):
        r = self.table.currentRow()
        if 0 <= r < len(self.items):
            self.items.pop(r)
            self.refresh()

    def move_selected(self, delta):
        r = self.table.currentRow()
        nr = r + delta
        if 0 <= r < len(self.items) and 0 <= nr < len(self.items):
            self.items[r], self.items[nr] = self.items[nr], self.items[r]
            self.refresh()
            self.table.selectRow(nr)

    def load_selected(self):
        r = self.table.currentRow()
        if 0 <= r < len(self.items):
            self.main.song_file = self.items[r]["path"]
            self.main.studio.file_label.setText(Path(self.main.song_file).name)
            self.main.nav.setCurrentRow(2)
            QMessageBox.information(self, "Setlist", "歌曲已载入。若该歌曲尚未分轨，请先执行 AI 六轨分离。")

    def current_index(self):
        r = self.table.currentRow()
        return r if 0 <= r < len(self.items) else -1

    def select_index(self, index):
        if 0 <= index < len(self.items):
            self.table.selectRow(index)
            return True
        return False

    def next_index(self):
        if not self.items:
            return -1
        r = self.current_index()
        return 0 if r < 0 else (r + 1 if r + 1 < len(self.items) else -1)

    def previous_index(self):
        if not self.items:
            return -1
        r = self.current_index()
        return 0 if r <= 0 else r - 1


class LiveProPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        layout = QVBoxLayout(self)

        title = QLabel("现场演出 Pro")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        top = QHBoxLayout()
        self.lock_btn = QPushButton("🔓 演出未锁定")
        self.lock_btn.setCheckable(True)
        self.lock_btn.toggled.connect(self.toggle_lock)
        self.panic_btn = QPushButton("■ 紧急停止")
        self.panic_btn.setMinimumHeight(52)
        self.panic_btn.clicked.connect(main.stop)
        top.addWidget(self.lock_btn)
        top.addWidget(self.panic_btn)
        top.addStretch(1)
        layout.addLayout(top)

        preset = QGroupBox("演出身份")
        pg = QGridLayout(preset)
        modes = [
            ("🎸 木吉他弹唱","guitar"),("🎸 电吉他手","electric_guitar"),
            ("🎹 钢琴弹唱","piano"),
            ("🥁 鼓手","drums"),("🎸 贝斯手","bass"),
            ("🎤 KTV/纯伴奏","vocals"),("🎼 全部恢复",None)
        ]
        for i,(txt,key) in enumerate(modes):
            b = QPushButton(txt)
            b.setMinimumHeight(56)
            b.clicked.connect(lambda checked=False,k=key: main.apply_live_preset(k))
            pg.addWidget(b,i//2,i%2)
        layout.addWidget(preset)

        trans = QGroupBox("现场速度 / 调性")
        tg = QGridLayout(trans)
        self.transpose = QSpinBox()
        self.transpose.setRange(-12,12)
        self.transpose.setValue(0)
        self.transpose.setSuffix(" 半音")
        self.transpose.valueChanged.connect(self.update_capo_label)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.50,1.50)
        self.speed.setSingleStep(0.05)
        self.speed.setValue(1.00)
        self.speed.setSuffix(" x")
        self.speed.valueChanged.connect(main.engine.set_speed)
        self.delay_ms = QSpinBox()
        self.delay_ms.setRange(0,1000)
        self.delay_ms.setSingleStep(10)
        self.delay_ms.setSuffix(" ms")
        self.capo_label=QLabel("推荐变调夹：0 品")
        apply_transpose=QPushButton("应用变调到全部音轨")
        apply_transpose.clicked.connect(main.apply_live_transpose)
        tg.addWidget(QLabel("升降调"),0,0)
        tg.addWidget(self.transpose,0,1)
        tg.addWidget(QLabel("速度"),1,0)
        tg.addWidget(self.speed,1,1)
        tg.addWidget(QLabel("节拍/谱面延时"),2,0)
        tg.addWidget(self.delay_ms,2,1)
        tg.addWidget(self.capo_label,3,0)
        tg.addWidget(apply_transpose,3,1)
        tg.addWidget(QLabel("速度实时作用于全部分轨；变调会生成并载入保持同步的新音轨。"),4,0,1,2)
        layout.addWidget(trans)

        met = QGroupBox("耳返 / 节拍器")
        mg = QGridLayout(met)
        self.metronome = QCheckBox("耳返开启节拍器")
        self.metronome.setChecked(False)
        self.metronome.toggled.connect(self.toggle_metronome_output)
        self.countin = QCheckBox("演出前 4 拍 Count-in")
        self.countin.setChecked(True)
        self.main_out = QComboBox()
        self.monitor_out = QComboBox()
        self.refresh_devices()
        ref = QPushButton("刷新声卡")
        ref.clicked.connect(self.refresh_devices)
        mg.addWidget(self.metronome,0,0)
        mg.addWidget(self.countin,0,1)
        mg.addWidget(QLabel("主输出"),1,0)
        mg.addWidget(self.main_out,1,1)
        mg.addWidget(QLabel("耳返输出"),2,0)
        mg.addWidget(self.monitor_out,2,1)
        mg.addWidget(ref,3,1)
        layout.addWidget(met)

        midi = QGroupBox("USB / MIDI 脚踏板")
        ml = QVBoxLayout(midi)
        self.midi_status = QLabel("尚未检测 MIDI 设备")
        scan = QPushButton("扫描 MIDI")
        scan.clicked.connect(self.scan_midi)
        ml.addWidget(self.midi_status)
        ml.addWidget(scan)
        ml.addWidget(QLabel("默认映射：播放/暂停、下一首、上一首、停止。"))
        layout.addWidget(midi)

        self.status = QLabel("现场状态：待机")
        self.status.setObjectName("StatusGood")
        layout.addWidget(self.status)
        layout.addStretch(1)

    def update_capo_label(self,value):
        semitones=int(value)
        capo=semitones if 0 <= semitones <= 7 else 0
        self.capo_label.setText(f"推荐变调夹：{capo} 品" if capo else "推荐变调夹：0 品/调整和弦指法")

    def toggle_lock(self, checked):
        if checked:
            self.lock_btn.setText("🔒 演出已锁定")
            self.status.setText("现场状态：已锁定，避免误触")
        else:
            self.lock_btn.setText("🔓 演出未锁定")
            self.status.setText("现场状态：待机")

    def refresh_devices(self):
        for combo in [self.main_out, self.monitor_out]:
            combo.clear()
        try:
            devices = sd.query_devices()
            outs = []
            for i,d in enumerate(devices):
                if d["max_output_channels"] > 0:
                    outs.append((i,d["name"]))
            for combo in [self.main_out,self.monitor_out]:
                for i,name in outs:
                    combo.addItem(f"{i}: {name}",i)
            if self.monitor_out.count() > 1:
                self.monitor_out.setCurrentIndex(1)
        except Exception as e:
            self.main_out.addItem("设备读取失败")
            self.monitor_out.addItem("设备读取失败")

    def scan_midi(self):
        try:
            import mido
            names = mido.get_input_names()
            if not names:
                self.midi_status.setText("未检测到 MIDI 输入设备")
                return
            self.main.start_midi_worker()
            self.midi_status.setText("正在监听 MIDI：\n" + "\n".join(names) +
                                     "\n\n36=播放/暂停  37=停止  38=下一首  39=上一首")
        except Exception as e:
            self.midi_status.setText("MIDI 初始化失败：" + str(e))

    def toggle_metronome_output(self):
        if self.metronome.isChecked():
            bpm = self.main.analysis_result.get("bpm", 120) if getattr(self.main, "analysis_result", None) else 120
            device = self.monitor_out.currentData()
            try:
                self.main.metronome_engine.start(device=device, bpm=bpm)
                self.status.setText(f"现场状态：耳返节拍器 {float(bpm):.1f} BPM")
            except Exception as e:
                self.metronome.setChecked(False)
                QMessageBox.critical(self, "耳返节拍器失败", str(e))
        else:
            self.main.metronome_engine.stop()



class ArrangementScorePage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        layout = QVBoxLayout(self)

        title = QLabel("AI 改编 / 乐谱中心")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        hint = QLabel("先分析歌曲的 BPM、调性、和弦与段落，再生成演奏参考谱和新的 MIDI 伴奏编配。原始录音仅作为分析参考。")
        hint.setWordWrap(True)
        hint.setObjectName("SectionHint")
        layout.addWidget(hint)

        analysis_box = QGroupBox("① 音乐分析与和弦时间线")
        al = QVBoxLayout(analysis_box)
        row = QHBoxLayout()
        self.song_label = QLabel("尚未分析歌曲")
        analyze = QPushButton(QIcon(icon_path("split")), "分析和弦 / BPM / 调性")
        apply_button_accent(analyze, "primary")
        analyze.clicked.connect(main.analyze_full_score)
        row.addWidget(self.song_label, 1)
        row.addWidget(analyze)
        al.addLayout(row)
        self.analysis_status = QLabel("等待分析")
        self.analysis_status.setWordWrap(True)
        al.addWidget(self.analysis_status)
        self.chord_table = QTableWidget(0, 4)
        self.chord_table.setHorizontalHeaderLabels(["小节", "时间", "和弦", "段落"])
        self.chord_table.horizontalHeader().setStretchLastSection(True)
        al.addWidget(self.chord_table)
        layout.addWidget(analysis_box)

        trans_box = QGroupBox("② 升降调")
        tl = QHBoxLayout(trans_box)
        self.transpose = QSpinBox()
        self.transpose.setRange(-12, 12)
        self.transpose.setValue(0)
        self.transpose.setSuffix(" 半音")
        self.target_key = QLabel("目标调：—")
        self.transpose.valueChanged.connect(main.update_target_key_label)
        transpose_btn = QPushButton("生成升降调六轨演出版")
        apply_button_accent(transpose_btn, "success")
        transpose_btn.clicked.connect(main.generate_transposed_stems)
        tl.addWidget(QLabel("升降调"))
        tl.addWidget(self.transpose)
        tl.addWidget(self.target_key)
        tl.addStretch(1)
        tl.addWidget(transpose_btn)
        layout.addWidget(trans_box)

        arrange_box = QGroupBox("③ AI 改编方案")
        rl = QGridLayout(arrange_box)
        self.arrange_mode = QComboBox()
        self.arrange_mode.addItems([
            "乐队现场版", "木吉他弹唱版", "钢琴弹唱版", "不插电版", "流行改编版", "摇滚改编版"
        ])
        self.use_player_settings = QCheckBox("使用“乐手演奏中心”参数参与编配")
        self.use_player_settings.setChecked(True)
        self.musical_intelligence = QCheckBox("启用段落音乐性智能编排")
        self.musical_intelligence.setChecked(True)
        self.energy_curve = QComboBox()
        self.energy_curve.addItems(["自动判断","渐进增强","平稳现场","强弱对比","抒情克制"])
        self.arrange_note = QLabel("生成的是新的 MIDI 伴奏结构，不直接复制原录音中的乐器音频。")
        self.arrange_note.setWordWrap(True)
        midi_btn = QPushButton("生成音乐性智能编配 MIDI")
        apply_button_accent(midi_btn, "primary")
        midi_btn.clicked.connect(main.generate_musical_intelligence_midi)
        rl.addWidget(QLabel("改编模式"),0,0)
        rl.addWidget(self.arrange_mode,0,1)
        rl.addWidget(midi_btn,0,2)
        rl.addWidget(self.use_player_settings,1,0,1,3)
        rl.addWidget(self.musical_intelligence,2,0,1,2)
        rl.addWidget(self.energy_curve,2,2)
        rl.addWidget(self.arrange_note,3,0,1,3)
        layout.addWidget(arrange_box)

        smart_box = QGroupBox("智能编配参数预览")
        sbl = QVBoxLayout(smart_box)
        self.smart_summary = QLabel("尚未读取乐手参数")
        self.smart_summary.setWordWrap(True)
        refresh_smart = QPushButton("读取当前乐手设置")
        refresh_smart.clicked.connect(main.refresh_smart_arranger_summary)
        sbl.addWidget(self.smart_summary)
        sbl.addWidget(refresh_smart)
        layout.addWidget(smart_box)

        intelligence_box = QGroupBox("段落音乐性预览")
        ibl = QVBoxLayout(intelligence_box)
        self.intelligence_summary = QLabel("尚未分析段落能量")
        self.intelligence_summary.setWordWrap(True)
        analyze_music_btn = QPushButton("分析段落并生成编配策略")
        analyze_music_btn.clicked.connect(main.refresh_musical_intelligence_preview)
        ibl.addWidget(self.intelligence_summary)
        ibl.addWidget(analyze_music_btn)
        layout.addWidget(intelligence_box)

        manual_box = QGroupBox("人工微调 / A-B 版本")
        mbl = QGridLayout(manual_box)
        self.manual_section = QComboBox()
        self.manual_section.currentIndexChanged.connect(main.load_manual_section_settings)

        self.manual_guitar = QSlider(Qt.Horizontal)
        self.manual_guitar.setRange(-50,50); self.manual_guitar.setValue(0)
        self.manual_bass = QSlider(Qt.Horizontal)
        self.manual_bass.setRange(-50,50); self.manual_bass.setValue(0)
        self.manual_drums = QSlider(Qt.Horizontal)
        self.manual_drums.setRange(-50,50); self.manual_drums.setValue(0)
        self.manual_piano = QSlider(Qt.Horizontal)
        self.manual_piano.setRange(-50,50); self.manual_piano.setValue(0)
        self.manual_fill = QSlider(Qt.Horizontal)
        self.manual_fill.setRange(-50,50); self.manual_fill.setValue(0)
        self.manual_space = QSlider(Qt.Horizontal)
        self.manual_space.setRange(-50,50); self.manual_space.setValue(0)

        self.manual_label = QLabel("调整范围：-50% ～ +50%，0 表示沿用橘味儿音乐自动策略")
        self.manual_label.setObjectName("SectionHint")
        self.manual_label.setWordWrap(True)

        save_a = QPushButton("保存版本 A")
        save_b = QPushButton("保存版本 B")
        apply_button_accent(save_a,"primary")
        apply_button_accent(save_b,"success")
        save_a.clicked.connect(lambda: main.save_arrangement_variant("A"))
        save_b.clicked.connect(lambda: main.save_arrangement_variant("B"))

        gen_a = QPushButton("生成 A 版 MIDI")
        gen_b = QPushButton("生成 B 版 MIDI")
        gen_a.clicked.connect(lambda: main.generate_variant_midi("A"))
        gen_b.clicked.connect(lambda: main.generate_variant_midi("B"))

        mbl.addWidget(QLabel("段落"),0,0); mbl.addWidget(self.manual_section,0,1,1,3)
        mbl.addWidget(QLabel("吉他"),1,0); mbl.addWidget(self.manual_guitar,1,1,1,3)
        mbl.addWidget(QLabel("Bass"),2,0); mbl.addWidget(self.manual_bass,2,1,1,3)
        mbl.addWidget(QLabel("鼓"),3,0); mbl.addWidget(self.manual_drums,3,1,1,3)
        mbl.addWidget(QLabel("键盘"),4,0); mbl.addWidget(self.manual_piano,4,1,1,3)
        mbl.addWidget(QLabel("Fill"),5,0); mbl.addWidget(self.manual_fill,5,1,1,3)
        mbl.addWidget(QLabel("留白"),6,0); mbl.addWidget(self.manual_space,6,1,1,3)
        mbl.addWidget(self.manual_label,7,0,1,4)
        mbl.addWidget(save_a,8,0); mbl.addWidget(gen_a,8,1)
        mbl.addWidget(save_b,8,2); mbl.addWidget(gen_b,8,3)
        layout.addWidget(manual_box)

        compare_box = QGroupBox("A/B 实时试听与版本历史")
        cbl = QGridLayout(compare_box)

        self.compare_section = QComboBox()
        self.compare_section.setMinimumWidth(220)

        render_a = QPushButton("渲染 A")
        render_b = QPushButton("渲染 B")
        render_a.clicked.connect(lambda: main.render_variant_audio("A"))
        render_b.clicked.connect(lambda: main.render_variant_audio("B"))

        play_a = QPushButton("试听 A")
        play_b = QPushButton("试听 B")
        apply_button_accent(play_a,"primary")
        apply_button_accent(play_b,"success")
        play_a.clicked.connect(lambda: main.preview_variant("A"))
        play_b.clicked.connect(lambda: main.preview_variant("B"))

        stop_ab = QPushButton("停止试听")
        stop_ab.clicked.connect(main.stop_variant_preview)

        self.loop_compare = QCheckBox("只循环当前段落对比")
        self.loop_compare.setChecked(True)

        adopt_a = QPushButton("采用 A")
        adopt_b = QPushButton("采用 B")
        adopt_a.clicked.connect(lambda: main.adopt_variant("A"))
        adopt_b.clicked.connect(lambda: main.adopt_variant("B"))

        undo = QPushButton("Undo")
        redo = QPushButton("Redo")
        undo.clicked.connect(main.undo_arrangement_change)
        redo.clicked.connect(main.redo_arrangement_change)

        snapshot = QPushButton("保存历史快照")
        snapshot.clicked.connect(main.save_arrangement_snapshot)
        restore_history = QPushButton("恢复所选历史")
        restore_history.clicked.connect(main.restore_selected_history)

        self.history_table = QTableWidget(0,4)
        self.history_table.setHorizontalHeaderLabels(["时间","版本","说明","文件"])
        self.history_table.horizontalHeader().setStretchLastSection(True)

        cbl.addWidget(QLabel("对比段落"),0,0)
        cbl.addWidget(self.compare_section,0,1)
        cbl.addWidget(self.loop_compare,0,2,1,2)
        cbl.addWidget(render_a,1,0); cbl.addWidget(play_a,1,1)
        cbl.addWidget(render_b,1,2); cbl.addWidget(play_b,1,3)
        cbl.addWidget(stop_ab,2,0)
        cbl.addWidget(adopt_a,2,1)
        cbl.addWidget(adopt_b,2,2)
        cbl.addWidget(snapshot,2,3)
        cbl.addWidget(undo,3,0)
        cbl.addWidget(redo,3,1)
        cbl.addWidget(restore_history,3,2,1,2)
        cbl.addWidget(self.history_table,4,0,1,4)
        layout.addWidget(compare_box)

        pro_compare = QGroupBox("A/B 专业对比")
        pcl = QGridLayout(pro_compare)

        self.ab_wave_a = WaveformWidget()
        self.ab_wave_b = WaveformWidget()
        self.ab_wave_a.setMinimumHeight(90)
        self.ab_wave_b.setMinimumHeight(90)

        self.loudness_match = QCheckBox("自动响度匹配")
        self.loudness_match.setChecked(True)
        self.instant_switch = QCheckBox("瞬时 A/B 切换")
        self.instant_switch.setChecked(True)

        switch_a = QPushButton("切到 A")
        switch_b = QPushButton("切到 B")
        apply_button_accent(switch_a,"primary")
        apply_button_accent(switch_b,"success")
        switch_a.clicked.connect(lambda: main.instant_switch_variant("A"))
        switch_b.clicked.connect(lambda: main.instant_switch_variant("B"))

        analyze_diff = QPushButton("分析 A/B 差异")
        analyze_diff.clicked.connect(main.analyze_ab_difference)

        self.diff_label = QLabel("A/B 差异：尚未分析")
        self.diff_label.setWordWrap(True)
        self.diff_label.setObjectName("SectionHint")

        pcl.addWidget(QLabel("A 波形"),0,0)
        pcl.addWidget(self.ab_wave_a,0,1,1,4)
        pcl.addWidget(QLabel("B 波形"),1,0)
        pcl.addWidget(self.ab_wave_b,1,1,1,4)
        pcl.addWidget(self.loudness_match,2,0)
        pcl.addWidget(self.instant_switch,2,1)
        pcl.addWidget(switch_a,2,2)
        pcl.addWidget(switch_b,2,3)
        pcl.addWidget(analyze_diff,2,4)
        pcl.addWidget(self.diff_label,3,0,1,5)

        layout.addWidget(pro_compare)

        render_box = QGroupBox("④ 新编配音源渲染")
        rbl = QGridLayout(render_box)
        self.soundfont_edit = QLineEdit()
        self.soundfont_edit.setPlaceholderText("选择 .sf2 / .sf3 SoundFont")
        sf_btn = QPushButton("选择 SoundFont")
        sf_btn.clicked.connect(main.choose_soundfont)
        render_wav_btn = QPushButton("渲染新编配 WAV")
        apply_button_accent(render_wav_btn, "success")
        render_wav_btn.clicked.connect(main.render_arrangement_wav)
        render_mp3_btn = QPushButton("渲染新编配 MP3")
        render_mp3_btn.clicked.connect(main.render_arrangement_mp3)
        rbl.addWidget(QLabel("SoundFont"),0,0)
        rbl.addWidget(self.soundfont_edit,0,1)
        rbl.addWidget(sf_btn,0,2)
        rbl.addWidget(render_wav_btn,1,1)
        rbl.addWidget(render_mp3_btn,1,2)
        layout.addWidget(render_box)

        score_box = QGroupBox("⑤ 乐手演奏谱")
        sl = QHBoxLayout(score_box)
        lead = QPushButton("导出 Lead Sheet / 和弦谱")
        lead.clicked.connect(main.export_lead_sheet)
        guitar = QPushButton("吉他演奏参考谱")
        guitar.clicked.connect(lambda: main.export_instrument_score("guitar"))
        bass = QPushButton("贝斯演奏参考谱")
        bass.clicked.connect(lambda: main.export_instrument_score("bass"))
        drums = QPushButton("鼓手演奏参考谱")
        drums.clicked.connect(lambda: main.export_instrument_score("drums"))
        piano = QPushButton("键盘演奏参考谱")
        piano.clicked.connect(lambda: main.export_instrument_score("piano"))
        musicxml = QPushButton("导出 MusicXML")
        musicxml.clicked.connect(main.export_musicxml)
        melody = QPushButton("主旋律参考转写")
        melody.clicked.connect(main.export_melody_reference)
        for b in [lead,guitar,bass,drums,piano,musicxml,melody]:
            sl.addWidget(b)
        xml_row = QHBoxLayout()
        for label,inst in [("吉他 MusicXML","guitar"),("Bass MusicXML","bass"),("鼓 MusicXML","drums"),("键盘 MusicXML","piano")]:
            b=QPushButton(label)
            b.clicked.connect(lambda checked=False, x=inst: main.export_instrument_musicxml(x))
            xml_row.addWidget(b)
        layout.addLayout(xml_row)
        layout.addWidget(score_box)

        self.progress = QProgressBar()
        self.progress.setRange(0,100)
        self.progress.setValue(0)
        self.progress.setFormat("改编 / 出谱 %p%")
        layout.addWidget(self.progress)



class DesktopScoreCanvas(QWidget):
    def __init__(self,main):
        super().__init__()
        self.main=main
        self.mode="五线谱"
        self.position=0.0
        self.setMinimumHeight(230)

    def set_mode(self,mode):
        self.mode=str(mode)
        self.update()

    def set_position(self,seconds):
        self.position=max(0,float(seconds))
        self.update()

    def _midi(self,note):
        if "midi" in note:
            return int(note.get("midi",60))
        match=re.match(r"^([A-G])([#b]?)(-?\d+)$",str(note.get("note","C4")))
        if not match:
            return 60
        pitch={"C":0,"D":2,"E":4,"F":5,"G":7,"A":9,"B":11}[match.group(1)]
        pitch += 1 if match.group(2)=="#" else -1 if match.group(2)=="b" else 0
        return 12*(int(match.group(3))+1)+pitch

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(),QColor("#0d1018"))
        width=max(100,self.width())
        top=40
        gap=22
        tablature=self.mode=="六线谱"
        line_count=6 if tablature else 5
        painter.setPen(QPen(QColor("#BDAAB5"),1))
        for index in range(line_count):
            y=top+index*gap
            painter.drawLine(24,y,width-24,y)
        painter.setPen(QPen(QColor("#FF7A18"),2))
        painter.drawLine(34,top-18,34,top+(line_count-1)*gap+18)

        notes=[
            note for note in getattr(self.main,"melody_reference",[])
            if self.position-1 <= float(note.get("start",0)) <= self.position+15
        ][:32]
        tuning=[64,59,55,50,45,40]
        for note in notes:
            start=float(note.get("start",0))
            x=52+(start-(self.position-1))/16*max(20,width-92)
            midi=self._midi(note)
            if tablature:
                choices=[(midi-open_note,index) for index,open_note in enumerate(tuning) if 0<=midi-open_note<=24]
                fret,string=min(choices,default=(0,0),key=lambda item:item[0])
                painter.setPen(QColor("#FF9A2A"))
                painter.drawText(QRectF(x-11,top+string*gap-11,24,22),Qt.AlignCenter,str(fret))
            else:
                y=max(18,min(top+4*gap+18,top+4*gap-(midi-60)*gap/3.5))
                painter.setBrush(QColor("#FF7A18")); painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPointF(x,y),7,5)
                painter.setPen(QPen(QColor("#FF7A18"),2)); painter.drawLine(QPointF(x+6,y),QPointF(x+6,y-30))

        lyric=""
        for row in getattr(self.main,"lyric_reference",[]):
            if self.position>=float(row.get("start",0)):
                lyric=str(row.get("text",""))
            else:
                break
        painter.setPen(QColor("#FFFFFF"))
        font=painter.font(); font.setPointSize(15); font.setBold(True); painter.setFont(font)
        painter.drawText(QRectF(24,self.height()-55,width-48,42),Qt.AlignCenter,lyric or "歌词将随播放位置同步显示")
        if not notes:
            painter.setPen(QColor("#A995A6"))
            painter.drawText(QRectF(24,top+line_count*gap+5,width-48,30),Qt.AlignCenter,"请先运行乐谱分析，自动生成主旋律五线谱和六线谱")


class ScorePerformancePage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.current_bar = -1

        layout = QVBoxLayout(self)
        title = QLabel("演出谱面 / 自动翻谱")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        top = QHBoxLayout()
        self.score_type = QComboBox()
        self.score_type.addItems(["Lead Sheet","五线谱","六线谱","贝斯谱","鼓谱","键盘谱"])
        self.score_type.currentIndexChanged.connect(self.refresh_score)
        self.auto_follow = QCheckBox("跟随播放头自动翻谱")
        self.auto_follow.setChecked(True)
        self.big_mode = QCheckBox("演出大字模式")
        self.big_mode.setChecked(True)
        self.big_mode.toggled.connect(self.refresh_score)
        refresh = QPushButton("刷新谱面")
        refresh.clicked.connect(self.refresh_score)
        top.addWidget(QLabel("谱面"))
        top.addWidget(self.score_type)
        top.addWidget(self.auto_follow)
        top.addWidget(self.big_mode)
        top.addWidget(refresh)
        top.addStretch(1)
        layout.addLayout(top)

        self.now = QLabel("当前小节：—")
        self.now.setObjectName("StatusGood")
        layout.addWidget(self.now)

        self.canvas=DesktopScoreCanvas(main)
        layout.addWidget(self.canvas)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        layout.addWidget(self.browser, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.follow_playback)
        self.timer.start(250)

    def _tab_for_chord(self, chord):
        # Practical chord-shape reference, not a melody transcription.
        shapes = {
            "C":"x32010","C#":"x46664","D":"xx0232","D#":"x68886",
            "E":"022100","F":"133211","F#":"244322","G":"320003",
            "G#":"466544","A":"x02220","A#":"x13331","B":"x24442",
            "Cm":"x35543","C#m":"x46654","Dm":"xx0231","D#m":"x68876",
            "Em":"022000","Fm":"133111","F#m":"244222","Gm":"355333",
            "G#m":"466444","Am":"x02210","A#m":"x13321","Bm":"x24432",
        }
        import re as _re
        m=_re.match(r"^([A-G](?:#|b)?m?)", chord or "")
        key=m.group(1) if m else chord
        return shapes.get(key, "按和弦根音/转位选择把位")

    def _html(self):
        rows=self.main._score_rows_transposed() if hasattr(self.main,"_score_rows_transposed") else []
        if not rows:
            return "<h2>尚无谱面</h2><p>请先在“AI 改编 / 乐谱”中分析歌曲。</p>"

        mode=self.score_type.currentText()
        font="24px" if self.big_mode.isChecked() else "16px"
        blocks=[]
        for row_index,row in enumerate(rows):
            chord=" / ".join(row.get("chords") or ["N"])
            extra=""
            notes=[n for n in getattr(self.main,"melody_reference",[]) if row["seconds"] <= float(n.get("start",n.get("seconds",0))) < row["seconds"]+12]
            next_seconds=rows[row_index+1]["seconds"] if row_index+1<len(rows) else row["seconds"]+12
            lyric_lines=[
                str(item.get("text","")) for item in getattr(self.main,"lyric_reference",[])
                if row["seconds"] <= float(item.get("start",0)) < next_seconds
            ]
            if mode=="五线谱":
                pitches="  ".join(html.escape(str(n.get("note",""))) for n in notes[:16]) or "请点击“主旋律参考转写”生成实际音符"
                extra=f"<div class='staff'><div>𝄞 ─────────────────────────</div><div>　──────── {pitches} ────────</div><div>　─────────────────────────</div><div>　─────────────────────────</div><div>　─────────────────────────</div></div>"
            elif mode=="六线谱":
                tuning=[("e",64),("B",59),("G",55),("D",50),("A",45),("E",40)]
                lanes={name:[] for name,_ in tuning}
                for note in notes[:16]:
                    raw=str(note.get("note","C4"))
                    match=re.match(r"^([A-G])([#b]?)(-?\d+)$",raw)
                    pitch={"C":0,"D":2,"E":4,"F":5,"G":7,"A":9,"B":11}.get(match.group(1),0) if match else 0
                    if match and match.group(2)=="#": pitch+=1
                    if match and match.group(2)=="b": pitch-=1
                    midi=int(note.get("midi",12*(int(match.group(3))+1)+pitch if match else 60))
                    choices=[(midi-open_note,name) for name,open_note in tuning if 0<=midi-open_note<=24]
                    fret,string=min(choices,default=(0,"e"),key=lambda x:x[0])
                    for name,_ in tuning:
                        lanes[name].append(str(fret) if name==string else "-")
                tab="<br>".join(f"{name}|"+"-".join(lanes[name] or ["-"])+"|" for name,_ in tuning)
                extra=f"<div class='tab'>{tab}</div>"
            elif mode=="吉他 TAB":
                first=(row.get("chords") or ["C"])[0]
                extra=f"<div class='tab'>Chord Shape: {self._tab_for_chord(first)}<br>E A D G B e</div>"
            elif mode=="贝斯谱":
                first=(row.get("chords") or ["C"])[0]
                extra=f"<div class='hint'>根音：{html.escape(first)} · 强拍根音，弱拍可用五度/经过音</div>"
            elif mode=="鼓谱":
                extra="<div class='tab'>HH x-x-x-x-x-x-x-x-<br>SD ----o-------o---<br>BD o-------o-------</div>"
            elif mode=="键盘谱":
                extra="<div class='hint'>左手：根音/五度 · 右手：和弦转位/分解</div>"
            if lyric_lines:
                extra += "<div class='lyrics'>"+"<br>".join(html.escape(line) for line in lyric_lines)+"</div>"
            blocks.append(
                f"<div id='bar{row['bar']}' class='bar'>"
                f"<div class='sec'>{html.escape(row.get('section',''))}</div>"
                f"<div class='num'>#{row['bar']} &nbsp; {self.main._format_time(row['seconds'])}</div>"
                f"<div class='chord'>{html.escape(chord)}</div>{extra}</div>"
            )
        return f"""<html><style>
        body{{background:#08101d;color:#eaf0ff;font-family:'Microsoft YaHei UI';font-size:{font};}}
        .bar{{padding:18px;margin:10px 2px;border:1px solid #243551;border-radius:12px;background:#0d1728;}}
        .sec{{color:#8ca0c5;font-size:0.65em}} .num{{color:#6f82a5;font-size:0.6em}}
        .chord{{color:#65e1ce;font-weight:800;font-size:1.35em;margin:8px 0}}
        .tab{{font-family:Consolas,monospace;color:#f4c04c;font-size:0.75em}}
        .staff{{font-family:'Segoe UI Symbol',Consolas,monospace;color:#f4c04c;font-size:0.72em;line-height:1.0}}
        .hint{{color:#b8c4dc;font-size:0.72em}}
        .lyrics{{color:#fff;font-size:0.9em;text-align:center;margin-top:12px;padding:8px;background:#251721;border-radius:8px}}
        .active{{border:2px solid #8b6cff;background:#21194a}}
        </style><body>{''.join(blocks)}</body></html>"""

    def refresh_score(self):
        self.canvas.set_mode(self.score_type.currentText())
        self.browser.setHtml(self._html())

    def follow_playback(self):
        if not self.auto_follow.isChecked():
            return
        rows=getattr(self.main,"chord_timeline",[])
        if not rows:
            return
        delay=(self.main.live_pro.delay_ms.value()/1000 if hasattr(self.main,"live_pro") else 0)
        pos=max(0,self.main.engine.position_seconds()-delay)
        self.canvas.set_position(pos)
        current=rows[0]["bar"]
        for row in rows:
            if pos >= row["seconds"]:
                current=row["bar"]
            else:
                break
        if current != self.current_bar:
            self.current_bar=current
            lyric=""
            for item in getattr(self.main,"lyric_reference",[]):
                if pos >= float(item.get("start",0)):
                    lyric=str(item.get("text",""))
                else:
                    break
            self.now.setText(f"当前小节：{current}" + (f"　歌词：{lyric}" if lyric else ""))
            self.browser.scrollToAnchor(f"bar{current}")


class VoiceLabPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main=main
        layout=QVBoxLayout(self)
        title=QLabel("AI 歌声转换")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        notice=QLabel(
            "v1.0.0 先建立独立歌声转换工作流：选择参考人声、选择待转换 Vocal Stem、"
            "生成任务配置。模型推理引擎与主播放器解耦，后续可接本地 Seed-VC/RVC 或云端 GPU。"
        )
        notice.setWordWrap(True)
        notice.setObjectName("SectionHint")
        layout.addWidget(notice)

        box=QGroupBox("歌声转换任务")
        gl=QGridLayout(box)
        self.reference=QLineEdit()
        self.source=QLineEdit()
        ref_btn=QPushButton("选择参考人声")
        src_btn=QPushButton("选择 Vocal Stem")
        ref_btn.clicked.connect(self.pick_reference)
        src_btn.clicked.connect(self.pick_source)
        self.engine=QComboBox()
        self.engine.addItems(["Seed-VC 接口","RVC 接口","云端 GPU 接口"])
        self.strength=QSlider(Qt.Horizontal)
        self.strength.setRange(0,100)
        self.strength.setValue(75)
        save=QPushButton("生成歌声转换任务")
        apply_button_accent(save,"primary")
        save.clicked.connect(self.save_job)
        gl.addWidget(QLabel("参考人声"),0,0); gl.addWidget(self.reference,0,1); gl.addWidget(ref_btn,0,2)
        gl.addWidget(QLabel("待转换人声"),1,0); gl.addWidget(self.source,1,1); gl.addWidget(src_btn,1,2)
        gl.addWidget(QLabel("引擎"),2,0); gl.addWidget(self.engine,2,1)
        gl.addWidget(QLabel("音色强度"),3,0); gl.addWidget(self.strength,3,1)
        gl.addWidget(save,4,2)
        layout.addWidget(box)

        rights=QLabel("使用真实人物声音前应确认拥有必要授权/同意；橘味儿音乐保存任务来源信息，便于后续授权管理。")
        rights.setWordWrap(True)
        layout.addWidget(rights)
        layout.addStretch(1)

    def pick_reference(self):
        p,_=QFileDialog.getOpenFileName(self,"参考人声","","音频 (*.wav *.mp3 *.flac *.m4a)")
        if p: self.reference.setText(p)

    def pick_source(self):
        default=""
        if self.main.stem_dir:
            p=Path(self.main.stem_dir)/"vocals.wav"
            if p.exists(): default=str(p)
        p,_=QFileDialog.getOpenFileName(self,"Vocal Stem",default,"音频 (*.wav *.mp3 *.flac)")
        if p: self.source.setText(p)

    def save_job(self):
        ref=self.reference.text().strip()
        src=self.source.text().strip()
        if not ref or not Path(ref).exists() or not src or not Path(src).exists():
            QMessageBox.warning(self,"提示","请选择有效的参考人声与 Vocal Stem。")
            return
        jobs=BASE_DIR/"voice_jobs"
        jobs.mkdir(parents=True,exist_ok=True)
        job={
            "version":VERSION,
            "engine":self.engine.currentText(),
            "reference_audio":ref,
            "source_vocal":src,
            "timbre_strength":self.strength.value()/100.0,
            "created_at":time.time(),
            "authorization_note":"User is responsible for having necessary rights/consent for the target voice."
        }
        name=f"voice_job_{int(time.time())}.json"
        p=jobs/name
        p.write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding="utf-8")
        QMessageBox.information(self,"任务已创建",f"歌声转换任务配置已保存：\n{p}")



class InstrumentExperiencePage(QWidget):
    """
    乐手友好控制中心：
    每种乐器只显示最相关的设置，把复杂工作站参数转成可理解的演奏选项。
    """
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.loop_section_index = -1

        layout = QVBoxLayout(self)
        title = QLabel("乐手演奏中心")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        hint = QLabel("选择你现场演奏的乐器，橘味儿音乐自动关闭对应原乐器轨，并显示该乐手最需要的谱面、排练和演奏参数。")
        hint.setObjectName("SectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # One-tap performer mode
        quick = QGroupBox("一键进入演奏模式")
        ql = QHBoxLayout(quick)
        self.instrument_buttons = {}
        items = [
            ("🎸 木吉他手","guitar"),
            ("🎸 电吉他手","electric_guitar"),
            ("🎸 贝斯手","bass"),
            ("🥁 鼓手","drums"),
            ("🎹 键盘手","piano"),
        ]
        for text,key in items:
            b=QPushButton(text)
            b.setCheckable(True)
            b.setMinimumHeight(48)
            b.clicked.connect(lambda checked=False,k=key: self.select_instrument(k))
            self.instrument_buttons[key]=b
            ql.addWidget(b)
        layout.addWidget(quick)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_guitar_tab(), "木吉他")
        self.tabs.addTab(self._build_electric_guitar_tab(), "电吉他")
        self.tabs.addTab(self._build_bass_tab(), "贝斯")
        self.tabs.addTab(self._build_drums_tab(), "鼓")
        self.tabs.addTab(self._build_piano_tab(), "键盘")
        layout.addWidget(self.tabs, 1)

        practice = QGroupBox("排练助手")
        pl = QGridLayout(practice)
        self.section_combo = QComboBox()
        self.refresh_sections_btn = QPushButton("刷新段落")
        self.refresh_sections_btn.clicked.connect(self.refresh_sections)
        self.loop_checkbox = QCheckBox("循环当前段落")
        self.loop_checkbox.toggled.connect(self.toggle_section_loop)
        self.countin_checkbox = QCheckBox("每次开始前 4 拍 Count-in")
        self.countin_checkbox.setChecked(True)
        self.practice_speed = QComboBox()
        self.practice_speed.addItems(["70% 慢练","85% 排练","100% 原速"])
        self.practice_speed.setCurrentIndex(2)
        self.current_bar = QLabel("当前：—")
        self.current_bar.setObjectName("StatusGood")
        jump_btn = QPushButton("跳到所选段落")
        jump_btn.clicked.connect(self.jump_to_section)
        pl.addWidget(QLabel("段落"),0,0)
        pl.addWidget(self.section_combo,0,1)
        pl.addWidget(self.refresh_sections_btn,0,2)
        pl.addWidget(jump_btn,0,3)
        pl.addWidget(self.loop_checkbox,1,0)
        pl.addWidget(self.countin_checkbox,1,1)
        pl.addWidget(QLabel("练习速度预设"),1,2)
        pl.addWidget(self.practice_speed,1,3)
        pl.addWidget(self.current_bar,2,0,1,4)
        layout.addWidget(practice)

        bottom = QHBoxLayout()
        save = QPushButton("保存本歌曲乐手设置")
        apply_button_accent(save,"primary")
        save.clicked.connect(self.save_instrument_profile)
        score = QPushButton("打开演出谱面")
        score.clicked.connect(self.open_score_page)
        play = QPushButton("开始 / 暂停")
        apply_button_accent(play,"success")
        play.clicked.connect(self.play_with_countin)
        bottom.addWidget(save)
        bottom.addWidget(score)
        bottom.addStretch(1)
        bottom.addWidget(play)
        layout.addLayout(bottom)

        self.timer=QTimer(self)
        self.timer.timeout.connect(self.update_practice_status)
        self.timer.start(200)

    def _common_difficulty(self):
        combo=QComboBox()
        combo.addItems(["简化","标准","丰富","专业"])
        combo.setCurrentText("标准")
        return combo

    def _build_guitar_tab(self):
        w=QWidget()
        l=QGridLayout(w)
        self.guitar_difficulty=self._common_difficulty()
        self.guitar_tuning=QComboBox()
        self.guitar_tuning.addItems(["标准 EADGBE","Drop D","降半音 Eb","自定义"])
        self.guitar_capo=QSpinBox()
        self.guitar_capo.setRange(0,12)
        self.guitar_capo.setSuffix(" 品")
        self.guitar_style=QComboBox()
        self.guitar_style.addItems(["自动推荐","扫弦","分解和弦","Power Chord","拨片节奏","Fingerstyle参考"])
        self.guitar_density=QSlider(Qt.Horizontal)
        self.guitar_density.setRange(1,10); self.guitar_density.setValue(5)
        l.addWidget(QLabel("演奏难度"),0,0); l.addWidget(self.guitar_difficulty,0,1)
        l.addWidget(QLabel("调弦"),1,0); l.addWidget(self.guitar_tuning,1,1)
        l.addWidget(QLabel("Capo"),2,0); l.addWidget(self.guitar_capo,2,1)
        l.addWidget(QLabel("伴奏方式"),3,0); l.addWidget(self.guitar_style,3,1)
        l.addWidget(QLabel("演奏密度"),4,0); l.addWidget(self.guitar_density,4,1)
        tips=QLabel("建议：歌手自弹吉他时可选择“简化 + 扫弦”；乐队双吉他时可降低密度，避免与键盘/另一把吉他抢频段。")
        tips.setWordWrap(True); tips.setObjectName("SectionHint")
        l.addWidget(tips,5,0,1,2)
        return w

    def _build_bass_tab(self):
        w=QWidget()
        l=QGridLayout(w)
        self.bass_difficulty=self._common_difficulty()
        self.bass_strings=QComboBox()
        self.bass_strings.addItems(["4弦标准 EADG","5弦 BEADG"])
        self.bass_pattern=QComboBox()
        self.bass_pattern.addItems(["根音优先","根音+五度","根音+八度","Walking参考","更旋律化"])
        self.bass_density=QSlider(Qt.Horizontal)
        self.bass_density.setRange(1,10); self.bass_density.setValue(5)
        self.bass_octave=QComboBox()
        self.bass_octave.addItems(["正常音区","低音更稳","高把位更多"])
        l.addWidget(QLabel("演奏难度"),0,0); l.addWidget(self.bass_difficulty,0,1)
        l.addWidget(QLabel("乐器"),1,0); l.addWidget(self.bass_strings,1,1)
        l.addWidget(QLabel("Bass Line"),2,0); l.addWidget(self.bass_pattern,2,1)
        l.addWidget(QLabel("音符密度"),3,0); l.addWidget(self.bass_density,3,1)
        l.addWidget(QLabel("音区"),4,0); l.addWidget(self.bass_octave,4,1)
        tips=QLabel("建议：现场伴唱优先“根音+五度”，稳定低频；需要更现代的感觉时再增加八度和经过音。")
        tips.setWordWrap(True); tips.setObjectName("SectionHint")
        l.addWidget(tips,5,0,1,2)
        return w

    def _build_electric_guitar_tab(self):
        w=QWidget()
        l=QGridLayout(w)
        self.electric_difficulty=self._common_difficulty()
        self.electric_tuning=QComboBox()
        self.electric_tuning.addItems(["标准 EADGBE","Drop D","降半音 Eb","Drop C"])
        self.electric_role=QComboBox()
        self.electric_role.addItems(["自动识别","节奏吉他","主音吉他","Power Chord","清音铺底","Solo"])
        self.electric_tone=QComboBox()
        self.electric_tone.addItems(["跟随原曲","Clean","Crunch","Overdrive","High Gain"])
        self.electric_density=QSlider(Qt.Horizontal)
        self.electric_density.setRange(1,10); self.electric_density.setValue(5)
        l.addWidget(QLabel("演奏难度"),0,0); l.addWidget(self.electric_difficulty,0,1)
        l.addWidget(QLabel("调弦"),1,0); l.addWidget(self.electric_tuning,1,1)
        l.addWidget(QLabel("演奏角色"),2,0); l.addWidget(self.electric_role,2,1)
        l.addWidget(QLabel("音色建议"),3,0); l.addWidget(self.electric_tone,3,1)
        l.addWidget(QLabel("演奏密度"),4,0); l.addWidget(self.electric_density,4,1)
        tips=QLabel("六轨模型先分离综合吉他轨，再通过二次频谱识别生成独立木吉他与电吉他轨；排练时选择电吉他手会自动关闭电吉他原轨。")
        tips.setWordWrap(True); tips.setObjectName("SectionHint")
        l.addWidget(tips,5,0,1,2)
        return w

    def _build_drums_tab(self):
        w=QWidget()
        l=QGridLayout(w)
        self.drums_difficulty=self._common_difficulty()
        self.drums_groove=QComboBox()
        self.drums_groove.addItems(["自动推荐","Pop 8Beat","Rock 8Beat","Ballad","Funk参考","Shuffle参考"])
        self.drums_hihat=QComboBox()
        self.drums_hihat.addItems(["八分音符","十六分音符","开闭镲混合","Ride为主"])
        self.drums_fill=QComboBox()
        self.drums_fill.addItems(["少量 Fill","段落前 Fill","副歌加强","丰富 Fill"])
        self.drums_strength=QSlider(Qt.Horizontal)
        self.drums_strength.setRange(1,10); self.drums_strength.setValue(5)
        l.addWidget(QLabel("演奏难度"),0,0); l.addWidget(self.drums_difficulty,0,1)
        l.addWidget(QLabel("Groove"),1,0); l.addWidget(self.drums_groove,1,1)
        l.addWidget(QLabel("Hi-Hat/Ride"),2,0); l.addWidget(self.drums_hihat,2,1)
        l.addWidget(QLabel("Fill"),3,0); l.addWidget(self.drums_fill,3,1)
        l.addWidget(QLabel("力度"),4,0); l.addWidget(self.drums_strength,4,1)
        tips=QLabel("建议：鼓手排练时优先看段落和小节提示；副歌、间奏前的 Fill 用 Marker 对齐会比单纯看时间更方便。")
        tips.setWordWrap(True); tips.setObjectName("SectionHint")
        l.addWidget(tips,5,0,1,2)
        return w

    def _build_piano_tab(self):
        w=QWidget()
        l=QGridLayout(w)
        self.piano_difficulty=self._common_difficulty()
        self.piano_left=QComboBox()
        self.piano_left.addItems(["根音","根音+五度","八度低音","分解和弦"])
        self.piano_right=QComboBox()
        self.piano_right.addItems(["三和弦","转位优先","分解和弦","Pad铺底","Rhodes节奏型"])
        self.piano_sustain=QComboBox()
        self.piano_sustain.addItems(["自动推荐","少延音","中等延音","氛围长延音"])
        self.piano_density=QSlider(Qt.Horizontal)
        self.piano_density.setRange(1,10); self.piano_density.setValue(5)
        l.addWidget(QLabel("演奏难度"),0,0); l.addWidget(self.piano_difficulty,0,1)
        l.addWidget(QLabel("左手"),1,0); l.addWidget(self.piano_left,1,1)
        l.addWidget(QLabel("右手"),2,0); l.addWidget(self.piano_right,2,1)
        l.addWidget(QLabel("延音"),3,0); l.addWidget(self.piano_sustain,3,1)
        l.addWidget(QLabel("织体密度"),4,0); l.addWidget(self.piano_density,4,1)
        tips=QLabel("建议：钢琴弹唱可用“左手根音+右手转位”；乐队里则降低左手密度，把低频空间留给 Bass。")
        tips.setWordWrap(True); tips.setObjectName("SectionHint")
        l.addWidget(tips,5,0,1,2)
        return w

    def select_instrument(self,key):
        index={"guitar":0,"electric_guitar":1,"bass":2,"drums":3,"piano":4}.get(key,0)
        self.tabs.setCurrentIndex(index)
        for k,b in self.instrument_buttons.items():
            b.setChecked(k==key)
        self.main.apply_live_preset(key)
        if hasattr(self.main,"score_performance"):
            mapping={"guitar":"六线谱","electric_guitar":"六线谱","bass":"贝斯谱","drums":"鼓谱","piano":"键盘谱"}
            idx=self.main.score_performance.score_type.findText(mapping[key])
            if idx>=0:
                self.main.score_performance.score_type.setCurrentIndex(idx)
                self.main.score_performance.refresh_score()

    def refresh_sections(self):
        self.section_combo.clear()
        sections=getattr(self.main,"section_timeline",[]) or []
        for i,s in enumerate(sections):
            self.section_combo.addItem(f"{i+1}. {s.get('name','段落')}  {self.main._format_time(s.get('seconds',0))}",i)

    def jump_to_section(self):
        idx=self.section_combo.currentData()
        sections=getattr(self.main,"section_timeline",[]) or []
        dur=self.main.engine.duration_seconds()
        if idx is None or not sections or dur<=0:
            return
        sec=float(sections[int(idx)].get("seconds",0))
        self.main.engine.seek_ratio(sec/dur)

    def toggle_section_loop(self,checked):
        idx=self.section_combo.currentData()
        self.loop_section_index=int(idx) if checked and idx is not None else -1

    def update_practice_status(self):
        rows=getattr(self.main,"chord_timeline",[]) or []
        pos=self.main.engine.position_seconds()
        current=None
        for row in rows:
            if pos>=row.get("seconds",0):
                current=row
            else:
                break
        if current:
            self.current_bar.setText(
                f"当前：{current.get('section','')} · 第 {current.get('bar','-')} 小节 · "
                f"{' / '.join(current.get('chords') or [])}"
            )

        if self.loop_checkbox.isChecked() and self.loop_section_index>=0:
            sections=getattr(self.main,"section_timeline",[]) or []
            i=self.loop_section_index
            if i < len(sections):
                start=float(sections[i].get("seconds",0))
                end=float(sections[i+1].get("seconds",self.main.engine.duration_seconds())) if i+1<len(sections) else self.main.engine.duration_seconds()
                if end>start and pos>=end-0.05:
                    dur=self.main.engine.duration_seconds()
                    if dur>0:
                        self.main.engine.seek_ratio(start/dur)

    def play_with_countin(self):
        if self.countin_checkbox.isChecked() and hasattr(self.main,"live"):
            try:
                self.main.live.start_count_in()
                return
            except Exception:
                pass
        self.main.play_pause()

    def open_score_page(self):
        # Navigation order: import 0, AI split 1, arrange 2, score 3
        self.main.nav.setCurrentRow(4)
        self.main.score_performance.refresh_score()

    def _profile_data(self):
        key=["guitar","electric_guitar","bass","drums","piano"][self.tabs.currentIndex()]
        data={"instrument":key,"practice_speed":self.practice_speed.currentText()}
        if key=="guitar":
            data.update({
                "difficulty":self.guitar_difficulty.currentText(),
                "tuning":self.guitar_tuning.currentText(),
                "capo":self.guitar_capo.value(),
                "style":self.guitar_style.currentText(),
                "density":self.guitar_density.value()
            })
        elif key=="electric_guitar":
            data.update({
                "difficulty":self.electric_difficulty.currentText(),
                "tuning":self.electric_tuning.currentText(),
                "role":self.electric_role.currentText(),
                "tone":self.electric_tone.currentText(),
                "density":self.electric_density.value()
            })
        elif key=="bass":
            data.update({
                "difficulty":self.bass_difficulty.currentText(),
                "strings":self.bass_strings.currentText(),
                "pattern":self.bass_pattern.currentText(),
                "density":self.bass_density.value(),
                "range":self.bass_octave.currentText()
            })
        elif key=="drums":
            data.update({
                "difficulty":self.drums_difficulty.currentText(),
                "groove":self.drums_groove.currentText(),
                "hihat":self.drums_hihat.currentText(),
                "fill":self.drums_fill.currentText(),
                "strength":self.drums_strength.value()
            })
        else:
            data.update({
                "difficulty":self.piano_difficulty.currentText(),
                "left":self.piano_left.currentText(),
                "right":self.piano_right.currentText(),
                "sustain":self.piano_sustain.currentText(),
                "density":self.piano_density.value()
            })
        return data

    def save_instrument_profile(self):
        if not self.main.song_file:
            QMessageBox.warning(self,"提示","请先导入歌曲。")
            return
        song=Path(self.main.song_file).stem
        folder=BASE_DIR/"instrument_profiles"
        folder.mkdir(parents=True,exist_ok=True)
        data=self._profile_data()
        data["song"]=self.main.song_file
        data["saved_at"]=time.time()
        p=folder/f"{song}_{data['instrument']}.json"
        p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        QMessageBox.information(self,"保存成功",f"本歌曲的乐手设置已保存：\n{p}")



class UniversalImportPage(QWidget):
    SUPPORTED_EXTS = {
        ".mp3",".wav",".flac",".m4a",".aac",".ogg",".opus",".wma",
        ".aiff",".aif",".alac",".ac3",".ape",".mka",".caf"
    }

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.queue = []
        self.clipboard_timer = None

        layout = QVBoxLayout(self)
        title = QLabel("统一音乐导入中心")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "支持本地多格式、批量文件、分享文本/链接、剪贴板导入。"
            "导入后统一转为橘味儿音乐工作 WAV，不修改原文件。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("SectionHint")
        layout.addWidget(hint)

        tabs = QTabWidget()
        tabs.addTab(self._build_local_tab(), "本地 / 批量")
        tabs.addTab(self._build_link_tab(), "分享链接")
        tabs.addTab(self._build_queue_tab(), "导入队列")
        layout.addWidget(tabs, 1)

    def _build_local_tab(self):
        w=QWidget()
        l=QVBoxLayout(w)

        bar=QHBoxLayout()
        one=QPushButton("选择音乐文件")
        many=QPushButton("批量选择")
        folder=QPushButton("导入整个文件夹")
        one.clicked.connect(self.pick_one)
        many.clicked.connect(self.pick_many)
        folder.clicked.connect(self.pick_folder)
        bar.addWidget(one); bar.addWidget(many); bar.addWidget(folder); bar.addStretch(1)
        l.addLayout(bar)

        self.local_list=QTableWidget(0,5)
        self.local_list.setHorizontalHeaderLabels(["文件","格式","大小","状态","目标工作文件"])
        self.local_list.horizontalHeader().setStretchLastSection(True)
        self.local_list.cellDoubleClicked.connect(self.open_local_item)
        l.addWidget(self.local_list)

        opts=QHBoxLayout()
        self.auto_convert=QCheckBox("自动转换为 WAV 工作格式")
        self.auto_convert.setChecked(True)
        self.auto_fingerprint=QCheckBox("自动音频指纹去重")
        self.auto_fingerprint.setChecked(True)
        self.auto_preanalyze=QCheckBox("导入后加入 BPM/调性预分析")
        self.auto_preanalyze.setChecked(True)
        start=QPushButton("开始导入")
        apply_button_accent(start,"primary")
        start.clicked.connect(self.process_local_queue)
        opts.addWidget(self.auto_convert)
        opts.addWidget(self.auto_fingerprint)
        opts.addWidget(self.auto_preanalyze)
        opts.addStretch(1)
        opts.addWidget(start)
        l.addLayout(opts)
        return w

    def _build_link_tab(self):
        w=QWidget()
        l=QVBoxLayout(w)

        self.share_text=QPlainTextEdit()
        self.share_text.setPlaceholderText(
            "粘贴音乐分享链接或整段分享文字，例如：\n"
            "歌曲：XXXX\nhttps://example.com/audio.mp3"
        )
        l.addWidget(self.share_text)

        bar=QHBoxLayout()
        paste=QPushButton("从剪贴板粘贴")
        parse=QPushButton("提取链接")
        download=QPushButton("下载并导入")
        paste.clicked.connect(self.paste_clipboard)
        parse.clicked.connect(self.parse_share_text)
        download.clicked.connect(self.download_selected_link)
        self.clip_watch=QCheckBox("监听剪贴板中的音乐链接")
        self.clip_watch.toggled.connect(self.toggle_clipboard_watch)
        bar.addWidget(paste); bar.addWidget(parse); bar.addWidget(download)
        bar.addWidget(self.clip_watch); bar.addStretch(1)
        l.addLayout(bar)

        self.link_table=QTableWidget(0,4)
        self.link_table.setHorizontalHeaderLabels(["URL","类型判断","状态","说明"])
        self.link_table.horizontalHeader().setStretchLastSection(True)
        l.addWidget(self.link_table)

        notice=QLabel(
            "橘味儿音乐只下载普通可直接访问的媒体/文件链接。"
            "不会绕过 DRM、会员、付费下载、登录验证或平台访问控制。"
        )
        notice.setWordWrap(True)
        notice.setObjectName("SectionHint")
        l.addWidget(notice)
        return w

    def _build_queue_tab(self):
        w=QWidget()
        l=QVBoxLayout(w)
        self.queue_table=QTableWidget(0,6)
        self.queue_table.setHorizontalHeaderLabels(["来源","文件","指纹","转换","预分析","状态"])
        self.queue_table.horizontalHeader().setStretchLastSection(True)
        l.addWidget(self.queue_table)
        return w

    def _audio_filter(self):
        return (
            "音频文件 (*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus *.wma "
            "*.aiff *.aif *.alac *.ac3 *.ape *.mka *.caf);;所有文件 (*.*)"
        )


    def open_local_item(self,row,col):
        local=[x for x in self.queue if x.get("kind")=="local"]
        if row<0 or row>=len(local):
            return
        item=local[row]
        path=item.get("working") or item.get("source")
        if path and Path(path).exists():
            self.main.load_imported_working_file(path)

    def pick_one(self):
        p,_=QFileDialog.getOpenFileName(self,"选择音乐文件","",self._audio_filter())
        if p: self.add_local_files([p])

    def pick_many(self):
        files,_=QFileDialog.getOpenFileNames(self,"批量选择音乐文件","",self._audio_filter())
        if files: self.add_local_files(files)

    def pick_folder(self):
        folder=QFileDialog.getExistingDirectory(self,"选择音乐文件夹")
        if not folder: return
        files=[]
        for p in Path(folder).rglob("*"):
            if p.is_file() and p.suffix.lower() in self.SUPPORTED_EXTS:
                files.append(str(p))
        self.add_local_files(files)

    def add_local_files(self, files):
        existing={x.get("source") for x in self.queue}
        for f in files:
            p=Path(f)
            if not p.exists() or p.suffix.lower() not in self.SUPPORTED_EXTS:
                continue
            if str(p) in existing:
                continue
            item={"source":str(p),"kind":"local","status":"等待导入"}
            self.queue.append(item)
            existing.add(str(p))
        self.refresh_tables()

    def _fingerprint(self, path):
        h=hashlib.sha256()
        with open(path,"rb") as f:
            while True:
                b=f.read(1024*1024)
                if not b: break
                h.update(b)
        return h.hexdigest()

    def _working_dir(self):
        if hasattr(self.main,"music_library"):
            d=self.main.music_library.library_paths["temp"]/"working"
        else:
            d=BASE_DIR/"imports"/"working"
        d.mkdir(parents=True,exist_ok=True)
        return d

    def _original_dir(self):
        if hasattr(self.main,"music_library"):
            d=self.main.music_library.library_paths["originals"]/"本地导入"
        else:
            d=BASE_DIR/"imports"/"originals"
        d.mkdir(parents=True,exist_ok=True)
        return d

    def _convert_to_wav(self, src):
        src=Path(src)
        try:
            fingerprint=self._fingerprint(src)[:12]
        except Exception:
            fingerprint=hashlib.sha256(normalized_path(src).encode("utf-8")).hexdigest()[:12]
        out=self._working_dir()/(safe_file_stem(src.stem)+f"_{fingerprint}_work.wav")
        ffmpeg=self.main._find_ffmpeg() if hasattr(self.main,"_find_ffmpeg") else ""
        if not ffmpeg:
            # WAV can be used directly when ffmpeg isn't available.
            if src.suffix.lower()==".wav":
                return str(src)
            raise RuntimeError("未找到 FFmpeg，无法把该格式转换成统一工作 WAV。")
        cmd=[
            ffmpeg,"-y","-i",str(src),
            "-vn","-ac","2","-ar","44100","-c:a","pcm_s24le",str(out)
        ]
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=600)
        if p.returncode!=0 or not out.exists():
            raise RuntimeError((p.stderr or "FFmpeg 转换失败")[-1800:])
        return str(out)

    def process_local_queue(self):
        if not self.queue:
            QMessageBox.information(self,"导入","当前没有待导入文件。")
            return

        fingerprint_db=BASE_DIR/"imports"/"fingerprints.json"
        fingerprint_db.parent.mkdir(parents=True,exist_ok=True)
        try:
            fpdb=json.loads(fingerprint_db.read_text(encoding="utf-8")) if fingerprint_db.exists() else {}
        except Exception:
            fpdb={}

        completed=0
        for idx,item in enumerate(self.queue):
            if item.get("status") in ("已导入", "已去重/复用"):
                continue
            src=item["source"]
            try:
                item["status"]="处理中"
                self.refresh_tables()
                QApplication.processEvents()

                fp=""
                if self.auto_fingerprint.isChecked():
                    fp=self._fingerprint(src)
                    item["fingerprint"]=fp
                    if fp in fpdb and Path(fpdb[fp].get("working","")).exists():
                        item["working"]=fpdb[fp]["working"]
                        item["status"]="已去重/复用"
                        completed+=1
                        continue

                # preserve original
                op=Path(src)
                original_dst=self._original_dir()/op.name
                if not original_dst.exists():
                    try:
                        shutil.copy2(op, original_dst)
                    except Exception:
                        original_dst=op

                working=str(op)
                if self.auto_convert.isChecked():
                    working=self._convert_to_wav(op)
                item["working"]=working

                if fp:
                    fpdb[fp]={
                        "source":str(op),
                        "original":str(original_dst),
                        "working":working,
                        "imported_at":time.time()
                    }

                item["preanalyze"]="待分析" if self.auto_preanalyze.isChecked() else "关闭"
                item["status"]="已导入"
                completed+=1
            except Exception as e:
                item["status"]="失败："+str(e)[:120]
            finally:
                self.refresh_tables()
                QApplication.processEvents()

        atomic_write_json(fingerprint_db, fpdb)
        if hasattr(self.main,"music_library"):
            self.main.music_library.scan_imports()
        QMessageBox.information(self,"导入完成",f"已处理 {completed} 个音乐素材，并同步到音乐库。")

    def paste_clipboard(self):
        text=QApplication.clipboard().text()
        if text:
            self.share_text.setPlainText(text)
            self.parse_share_text()

    def _extract_urls(self, text):
        import re as _re
        urls=_re.findall(r'https?://[^\s<>"\']+',text or "")
        clean=[]
        for u in urls:
            u=u.rstrip("，。；;）)]}")
            if u not in clean:
                clean.append(u)
        return clean

    def _classify_url(self,url):
        path=urllib.parse.urlparse(url).path.lower()
        ext=Path(path).suffix.lower()
        if ext in self.SUPPORTED_EXTS:
            return "直接音频链接","可尝试直接下载"
        if ext in {".zip",".7z",".rar"}:
            return "压缩包链接","不自动解压为音乐"
        host=urllib.parse.urlparse(url).netloc.lower()
        if host:
            return "分享/网页链接","需要平台提供公开可下载媒体地址"
        return "未知",""

    def parse_share_text(self):
        urls=self._extract_urls(self.share_text.toPlainText())
        self.link_table.setRowCount(len(urls))
        for r,u in enumerate(urls):
            kind,note=self._classify_url(u)
            vals=[u,kind,"待处理",note]
            for c,v in enumerate(vals):
                self.link_table.setItem(r,c,QTableWidgetItem(v))

    def _selected_url(self):
        r=self.link_table.currentRow()
        if r<0 and self.link_table.rowCount()==1:
            r=0
        if r<0: return ""
        item=self.link_table.item(r,0)
        return item.text().strip() if item else ""

    def download_selected_link(self):
        url=self._selected_url()
        if not url:
            QMessageBox.information(self,"链接导入","请先提取并选择一个链接。")
            return
        kind,note=self._classify_url(url)
        if kind!="直接音频链接":
            QMessageBox.information(
                self,"暂不直接下载",
                "该链接不是明确的公开音频直链。\n\n"
                "橘味儿音乐不会绕过登录、DRM、会员、付费或平台访问控制。"
                "如果平台能提供公开下载地址或用户自己的文件直链，可再粘贴该直链。"
            )
            return
        try:
            downloads=(
                self.main.music_library.library_paths["temp"]/"链接导入"
                if hasattr(self.main,"music_library")
                else BASE_DIR/"imports"/"downloads"
            )
            downloads.mkdir(parents=True,exist_ok=True)
            parsed=urllib.parse.urlparse(url)
            name=Path(parsed.path).name or "downloaded_audio"
            dest=downloads/name
            req=urllib.request.Request(url,headers={"User-Agent":"Juweier-Music/3.2.0"})
            with urllib.request.urlopen(req,timeout=30) as resp, open(dest,"wb") as f:
                total=int(resp.headers.get("Content-Length") or 0)
                read=0
                while True:
                    chunk=resp.read(256*1024)
                    if not chunk: break
                    f.write(chunk); read+=len(chunk)
                    if total>0:
                        pct=int(read/total*100)
                        self.link_table.setItem(self.link_table.currentRow() if self.link_table.currentRow()>=0 else 0,2,QTableWidgetItem(f"下载 {pct}%"))
                        QApplication.processEvents()
            self.add_local_files([str(dest)])
            if hasattr(self.main,"music_library"):
                self.main.music_library.scan_imports()
            QMessageBox.information(self,"下载完成",f"已下载并加入本地导入队列：\n{dest}")
        except Exception as e:
            QMessageBox.critical(self,"链接下载失败",str(e))

    def toggle_clipboard_watch(self,checked):
        if checked:
            if self.clipboard_timer is None:
                self.clipboard_timer=QTimer(self)
                self.clipboard_timer.timeout.connect(self.check_clipboard)
            self._last_clipboard=""
            self.clipboard_timer.start(1200)
        else:
            if self.clipboard_timer:
                self.clipboard_timer.stop()

    def check_clipboard(self):
        text=QApplication.clipboard().text().strip()
        if not text or text==getattr(self,"_last_clipboard",""):
            return
        self._last_clipboard=text
        urls=self._extract_urls(text)
        if not urls:
            return
        direct=[u for u in urls if self._classify_url(u)[0]=="直接音频链接"]
        if direct:
            self.share_text.setPlainText(text)
            self.parse_share_text()

    def refresh_tables(self):
        local=[x for x in self.queue if x.get("kind")=="local"]
        self.local_list.setRowCount(len(local))
        for r,item in enumerate(local):
            p=Path(item["source"])
            try:
                size=f"{p.stat().st_size/1024/1024:.1f} MB"
            except Exception:
                size="-"
            vals=[
                p.name,p.suffix.lower().lstrip(".").upper(),size,
                item.get("status",""),
                item.get("working","")
            ]
            for c,v in enumerate(vals):
                self.local_list.setItem(r,c,QTableWidgetItem(str(v)))

        self.queue_table.setRowCount(len(self.queue))
        for r,item in enumerate(self.queue):
            vals=[
                item.get("kind",""),
                Path(item.get("source","")).name,
                (item.get("fingerprint","")[:12] if item.get("fingerprint") else "-"),
                ("完成" if item.get("working") else "待处理"),
                item.get("preanalyze","-"),
                item.get("status","")
            ]
            for c,v in enumerate(vals):
                self.queue_table.setItem(r,c,QTableWidgetItem(str(v)))



class MusicLibraryPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.library_paths = ensure_library_layout(default_library_root())
        self.db_path = self.library_paths["database"]/"juweier_music_library.sqlite3"
        self.cover_dir = self.library_paths["covers"]
        self.scan_roots_file = self.library_paths["database"]/"scan_roots.json"
        self.scan_roots = self._load_scan_roots()
        self.link_worker = None
        self.batch_queue = []
        self.batch_index = -1
        self.batch_worker = None
        self.batch_running = False
        self.batch_paused = False
        self.batch_retry_failed = True
        self.batch_completed = 0
        self.batch_failed = 0
        self.pipeline_jobs = []
        self.pipeline_running = False
        self.pipeline_paused = False
        self.pipeline_job_index = -1
        self.pipeline_stage = ""
        self.pipeline_batch_worker = None
        self.pipeline_stage_worker = None
        self.pipeline_stage_order = [
            "stems","analysis","chords","score","arrangement","render","library"
        ]
        self.scheduler_backoff_seconds = 15
        self.scheduler_last_gpu_state = {}
        self.scheduler_timer = QTimer(self)
        self.scheduler_timer.timeout.connect(self._scheduler_tick)
        self.scheduler_timer.start(5000)
        self.cover_dir.mkdir(parents=True,exist_ok=True)
        self._ensure_db()

        layout=QVBoxLayout(self)
        title=QLabel("音乐库 / 自动分析")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        hint=QLabel(
            f"主歌曲目录：{self.library_paths['originals']}。递归读取 MP3/FLAC 并按 G 盘歌手文件夹显示；"
            "基础模型保持六轨，吉他轨完成后再二次识别木吉他与电吉他。"
        )
        hint.setObjectName("SectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        top=QHBoxLayout()
        scan=QPushButton("扫描全部歌曲目录")
        choose_root=QPushButton("选择/增加歌曲目录")
        import_local=QPushButton("导入本地音乐")
        import_link=QPushButton("粘贴分享链接")
        analyze=QPushButton("批量 BPM / 调性分析")
        stems=QPushButton("建立六轨+电吉他队列")
        refresh=QPushButton("刷新音乐库")
        apply_button_accent(scan,"primary")
        scan.clicked.connect(self.scan_imports)
        choose_root.clicked.connect(self.choose_scan_folder)
        import_local.clicked.connect(self.import_local_music)
        import_link.clicked.connect(self.import_share_link)
        analyze.clicked.connect(self.batch_analyze)
        stems.clicked.connect(self.enqueue_stems)
        refresh.clicked.connect(self.refresh_library)
        for b in [scan,choose_root,import_local,import_link,analyze,stems,refresh]:
            top.addWidget(b)
        top.addStretch(1)
        layout.addLayout(top)

        search_row=QHBoxLayout()
        self.library_search=QLineEdit()
        self.library_search.setPlaceholderText("搜索歌曲、歌手或专辑")
        self.library_category=QComboBox()
        self.library_category.addItems(["全部","本地导入","临时歌曲库","抖音流行","酷狗排行榜"])
        search_button=QPushButton("🔍 搜索")
        clear_button=QPushButton("清空")
        apply_button_accent(search_button,"primary")
        self.library_search.returnPressed.connect(self.refresh_library)
        self.library_category.currentTextChanged.connect(self.refresh_library)
        search_button.clicked.connect(self.refresh_library)
        clear_button.clicked.connect(lambda: (self.library_search.clear(), self.refresh_library()))
        search_row.addWidget(self.library_search,1)
        search_row.addWidget(self.library_category)
        search_row.addWidget(search_button)
        search_row.addWidget(clear_button)
        layout.addLayout(search_row)

        self.library_scan_status=QLabel(
            "扫描目录：" + "；".join(str(path) for path in self.scan_roots)
        )
        self.library_scan_status.setObjectName("SectionHint")
        self.library_scan_status.setWordWrap(True)
        layout.addWidget(self.library_scan_status)

        batch_box=QGroupBox("批量 AI 处理器")
        bgl=QGridLayout(batch_box)

        self.device_mode=QComboBox()
        self.device_mode.addItems(["自动 GPU/CPU","优先 NVIDIA GPU","仅 CPU"])
        self.after_analysis=QCheckBox("分轨完成后自动 BPM/调性分析")
        self.after_analysis.setChecked(True)
        self.after_score=QCheckBox("分轨完成后标记为待出谱")
        self.after_score.setChecked(True)
        self.retry_failed=QCheckBox("失败任务自动重试 1 次")
        self.retry_failed.setChecked(True)

        self.btn_batch_start=QPushButton("▶ 开始批处理")
        self.btn_batch_pause=QPushButton("⏸ 暂停")
        self.btn_batch_retry=QPushButton("↻ 重试失败")
        apply_button_accent(self.btn_batch_start,"success")
        self.btn_batch_start.clicked.connect(self.start_batch_processing)
        self.btn_batch_pause.clicked.connect(self.toggle_batch_pause)
        self.btn_batch_retry.clicked.connect(self.retry_failed_tasks)

        self.batch_status=QLabel("批处理：待机")
        self.batch_status.setObjectName("StatusGood")
        self.total_progress=QProgressBar()
        self.total_progress.setRange(0,100)
        self.total_progress.setValue(0)
        self.current_progress=QProgressBar()
        self.current_progress.setRange(0,100)
        self.current_progress.setValue(0)

        bgl.addWidget(QLabel("运算模式"),0,0)
        bgl.addWidget(self.device_mode,0,1)
        bgl.addWidget(self.after_analysis,0,2)
        bgl.addWidget(self.after_score,0,3)
        bgl.addWidget(self.retry_failed,0,4)
        bgl.addWidget(self.btn_batch_start,1,0)
        bgl.addWidget(self.btn_batch_pause,1,1)
        bgl.addWidget(self.btn_batch_retry,1,2)
        bgl.addWidget(self.batch_status,1,3,1,2)
        bgl.addWidget(QLabel("当前歌曲"),2,0)
        bgl.addWidget(self.current_progress,2,1,1,4)
        bgl.addWidget(QLabel("总进度"),3,0)
        bgl.addWidget(self.total_progress,3,1,1,4)
        layout.addWidget(batch_box)

        pipeline_box=QGroupBox("v2.0 自动生产流水线")
        pgl=QGridLayout(pipeline_box)

        self.pipeline_executor=QComboBox()
        self.pipeline_executor.addItems(["本地执行器","云端执行器（接口预留）"])
        self.pipeline_output=QComboBox()
        self.pipeline_output.addItems(["WAV","WAV + MP3"])

        self.pipe_stems=QCheckBox("六轨+电吉他")
        self.pipe_analysis=QCheckBox("BPM/调性")
        self.pipe_chords=QCheckBox("和弦/段落")
        self.pipe_score=QCheckBox("乐谱")
        self.pipe_arrange=QCheckBox("智能编配")
        self.pipe_render=QCheckBox("渲染")
        for cb in [self.pipe_stems,self.pipe_analysis,self.pipe_chords,self.pipe_score,self.pipe_arrange,self.pipe_render]:
            cb.setChecked(True)

        self.pipe_start=QPushButton("开始自动流水线")
        self.pipe_pause=QPushButton("暂停流水线")
        self.pipe_resume_failed=QPushButton("继续失败任务")
        apply_button_accent(self.pipe_start,"primary")
        self.pipe_start.clicked.connect(self.start_auto_pipeline)
        self.pipe_pause.clicked.connect(self.toggle_pipeline_pause)
        self.pipe_resume_failed.clicked.connect(self.resume_failed_pipeline_jobs)

        self.pipeline_status=QLabel("流水线：待机")
        self.pipeline_status.setObjectName("StatusGood")
        self.pipeline_progress=QProgressBar()
        self.pipeline_progress.setRange(0,100)
        self.pipeline_progress.setValue(0)

        self.pipeline_table=QTableWidget(0,10)
        self.pipeline_table.setHorizontalHeaderLabels(
            ["优先级","歌曲","六轨+电吉他","分析","和弦","乐谱","改编","渲染","入库","状态"]
        )
        self.pipeline_table.horizontalHeader().setStretchLastSection(True)

        pgl.addWidget(QLabel("执行器"),0,0)
        pgl.addWidget(self.pipeline_executor,0,1)
        pgl.addWidget(QLabel("输出"),0,2)
        pgl.addWidget(self.pipeline_output,0,3)

        pgl.addWidget(self.pipe_stems,1,0)
        pgl.addWidget(self.pipe_analysis,1,1)
        pgl.addWidget(self.pipe_chords,1,2)
        pgl.addWidget(self.pipe_score,1,3)
        pgl.addWidget(self.pipe_arrange,1,4)
        pgl.addWidget(self.pipe_render,1,5)

        pgl.addWidget(self.pipe_start,2,0)
        pgl.addWidget(self.pipe_pause,2,1)
        pgl.addWidget(self.pipe_resume_failed,2,2)
        pgl.addWidget(self.pipeline_status,2,3,1,3)
        pgl.addWidget(self.pipeline_progress,3,0,1,6)
        pgl.addWidget(self.pipeline_table,4,0,1,6)

        layout.addWidget(pipeline_box)

        scheduler_box=QGroupBox("专业任务调度")
        sgl=QGridLayout(scheduler_box)

        self.gpu_selector=QComboBox()
        self.refresh_gpu_btn=QPushButton("刷新 GPU")
        self.refresh_gpu_btn.clicked.connect(self.refresh_gpu_list)
        self.gpu_memory_limit=QSpinBox()
        self.gpu_memory_limit.setRange(0,100)
        self.gpu_memory_limit.setValue(85)
        self.gpu_memory_limit.setSuffix("%")
        self.gpu_temp_limit=QSpinBox()
        self.gpu_temp_limit.setRange(50,95)
        self.gpu_temp_limit.setValue(82)
        self.gpu_temp_limit.setSuffix(" °C")

        self.night_mode=QCheckBox("启用夜间批处理")
        self.night_start=QComboBox()
        self.night_end=QComboBox()
        for h in range(24):
            self.night_start.addItem(f"{h:02d}:00",h)
            self.night_end.addItem(f"{h:02d}:00",h)
        self.night_start.setCurrentIndex(23)
        self.night_end.setCurrentIndex(7)

        self.default_priority=QComboBox()
        self.default_priority.addItems(["高","普通","低"])
        self.default_priority.setCurrentText("普通")

        self.scheduler_status=QLabel("调度器：待机")
        self.scheduler_status.setObjectName("StatusGood")

        self.queue_sort_btn=QPushButton("按优先级重排")
        self.queue_sort_btn.clicked.connect(self.sort_pipeline_by_priority)
        self.refresh_gpu_list()

        sgl.addWidget(QLabel("GPU"),0,0)
        sgl.addWidget(self.gpu_selector,0,1)
        sgl.addWidget(self.refresh_gpu_btn,0,2)
        sgl.addWidget(QLabel("最大显存占用"),0,3)
        sgl.addWidget(self.gpu_memory_limit,0,4)
        sgl.addWidget(QLabel("温度上限"),0,5)
        sgl.addWidget(self.gpu_temp_limit,0,6)

        sgl.addWidget(self.night_mode,1,0)
        sgl.addWidget(QLabel("开始"),1,1)
        sgl.addWidget(self.night_start,1,2)
        sgl.addWidget(QLabel("结束"),1,3)
        sgl.addWidget(self.night_end,1,4)
        sgl.addWidget(QLabel("默认优先级"),1,5)
        sgl.addWidget(self.default_priority,1,6)

        sgl.addWidget(self.queue_sort_btn,2,0)
        sgl.addWidget(self.scheduler_status,2,1,1,6)

        layout.addWidget(scheduler_box)

        body=QHBoxLayout()
        self.tree=QTreeWidget()
        self.tree.setHeaderLabels(["歌手分类 / 歌曲","分类 · 专辑 · 音质"])
        self.tree.itemSelectionChanged.connect(self.show_selected)
        self.tree.itemDoubleClicked.connect(lambda item,col: self.load_selected_to_workspace())
        body.addWidget(self.tree,1)

        right=QVBoxLayout()
        self.cover=QLabel("无封面")
        self.cover.setFixedSize(220,220)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("border:1px solid #293957;border-radius:12px;background:#0c1424;")
        right.addWidget(self.cover)

        self.detail=QLabel("请选择歌曲")
        self.detail.setWordWrap(True)
        right.addWidget(self.detail)

        self.task_table=QTableWidget(0,6)
        self.task_table.setHorizontalHeaderLabels(["序号","歌曲","设备","状态","进度","失败原因"])
        self.task_table.horizontalHeader().setStretchLastSection(True)
        right.addWidget(QLabel("批量任务"))
        right.addWidget(self.task_table,1)
        body.addLayout(right,1)
        layout.addLayout(body,1)

        self.progress=QProgressBar()
        self.progress.setRange(0,100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.refresh_library()
        self._load_batch_queue()
        self.refresh_task_table()
        self._load_pipeline_jobs()
        self.refresh_pipeline_table()

    def _load_scan_roots(self):
        defaults=[self.library_paths["originals"],self.library_paths["temp"]]
        try:
            rows=json.loads(self.scan_roots_file.read_text(encoding="utf-8"))
            saved=[Path(row) for row in rows if str(row).strip()]
        except Exception:
            saved=[]
        result=[]
        for path in [*defaults,*saved]:
            key=normalized_path(path)
            if key not in {normalized_path(item) for item in result}:
                result.append(Path(path))
        return result

    def _save_scan_roots(self):
        atomic_write_json(self.scan_roots_file,[str(path) for path in self.scan_roots])

    def choose_scan_folder(self):
        selected=QFileDialog.getExistingDirectory(
            self,"选择包含歌手分类的音乐目录",str(self.library_paths["originals"])
        )
        if not selected:
            return
        path=Path(selected)
        if normalized_path(path) not in {normalized_path(item) for item in self.scan_roots}:
            self.scan_roots.append(path)
            self._save_scan_roots()
        self.library_scan_status.setText("扫描目录："+"；".join(str(item) for item in self.scan_roots))
        self.scan_imports()

    def import_local_music(self):
        files,_=QFileDialog.getOpenFileNames(
            self,"导入本地音乐","",
            "音频文件 (*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus *.wma *.aiff *.aif *.alac)"
        )
        if not files:
            return
        target=self.library_paths["originals"]/"本地导入"
        target.mkdir(parents=True,exist_ok=True)
        copied=0
        for raw in files:
            source=Path(raw)
            destination=target/source.name
            if destination.exists() and source.resolve()!=destination.resolve():
                destination=target/f"{safe_file_stem(source.stem)}_{int(time.time()*1000)}{source.suffix}"
            if source.resolve()!=destination.resolve():
                shutil.copy2(source,destination)
            copied+=1
        self.scan_imports()
        self.library_scan_status.setText(f"本地导入完成：{copied} 首 · 保存到 {target}")

    def import_share_link(self):
        value,ok=QInputDialog.getMultiLineText(
            self,"粘贴分享链接",
            "支持公开音频直链及平台公开分享页；不会绕过登录、会员、付费或 DRM。",
            QApplication.clipboard().text().strip(),
        )
        if not ok or not value.strip():
            return
        match=re.search(r"https?://[^\s<>\"']+",value)
        if not match:
            QMessageBox.warning(self,"分享链接","没有识别到 http/https 链接。")
            return
        url=match.group(0).rstrip("，。；;）)]}")
        if self.link_worker and self.link_worker.isRunning():
            QMessageBox.information(self,"分享链接","已有下载任务正在进行。")
            return
        self.progress.setValue(1)
        self.link_worker=LinkDownloadWorker(
            url,self.library_paths["temp"]/"链接导入",self.main._find_ffmpeg()
        )
        self.link_worker.progress.connect(self._link_progress)
        self.link_worker.done.connect(self._link_done)
        self.link_worker.failed.connect(self._link_failed)
        self.link_worker.start()

    def _link_progress(self,value,text):
        self.progress.setValue(max(0,min(100,int(value))))
        self.library_scan_status.setText(text)

    def _link_done(self,path):
        self.library_scan_status.setText(f"分享歌曲已下载到临时歌曲库：{path}")
        self.scan_imports()

    def _link_failed(self,error):
        self.progress.setValue(0)
        self.library_scan_status.setText("分享链接导入失败")
        QMessageBox.critical(self,"分享链接导入失败",str(error))

    def _db(self):
        return connect_catalog(self.db_path)

    def _ensure_db(self):
        self.db_path.parent.mkdir(parents=True,exist_ok=True)
        con=self._db()
        con.executescript("""
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
            imported_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_tracks_artist_album ON tracks(artist,album);
        """)
        # Lightweight migrations for v2 pipeline state.
        cols={row["name"] for row in con.execute("PRAGMA table_info(tracks)").fetchall()}
        for col,ddl in {
            "chords_status":"TEXT DEFAULT '未处理'",
            "score_status":"TEXT DEFAULT '未处理'",
            "arrangement_status":"TEXT DEFAULT '未处理'",
            "render_status":"TEXT DEFAULT '未处理'",
            "final_audio_path":"TEXT DEFAULT ''"
        }.items():
            if col not in cols:
                con.execute(f"ALTER TABLE tracks ADD COLUMN {col} {ddl}")
        con.commit()
        con.close()

    def _tag_first(self,tags,keys,default=""):
        if not tags:
            return default
        for k in keys:
            try:
                v=tags.get(k)
                if v:
                    if isinstance(v,(list,tuple)):
                        v=v[0]
                    return repair_text(v, default)
            except Exception:
                pass
        return repair_text(default, default)

    def _extract_metadata(self,path):
        p=Path(path)
        data={
            "title":repair_text(p.stem,p.stem),"artist":"未知歌手","album":"未分类专辑","year":"",
            "duration":0.0,"bitrate":0,"samplerate":0,"channels":0,
            "format":p.suffix.lower().lstrip(".").upper(),"cover_path":""
        }
        try:
            import mutagen
            audio=mutagen.File(str(p),easy=False)
            if audio is not None:
                info=getattr(audio,"info",None)
                if info:
                    data["duration"]=float(getattr(info,"length",0) or 0)
                    data["bitrate"]=int(getattr(info,"bitrate",0) or 0)
                    data["samplerate"]=int(getattr(info,"sample_rate",getattr(info,"samplerate",0)) or 0)
                    data["channels"]=int(getattr(info,"channels",0) or 0)

                tags=getattr(audio,"tags",None)
                if tags:
                    try:
                        if "TIT2" in tags: data["title"]=repair_text(tags["TIT2"],p.stem)
                        if "TPE1" in tags: data["artist"]=repair_text(tags["TPE1"],"未知歌手")
                        if "TALB" in tags: data["album"]=repair_text(tags["TALB"],"未分类专辑")
                        if "TDRC" in tags: data["year"]=repair_text(tags["TDRC"],"")
                    except Exception:
                        pass

                    data["title"]=self._tag_first(tags,["title","TITLE"],data["title"])
                    data["artist"]=self._tag_first(tags,["artist","ARTIST"],data["artist"])
                    data["album"]=self._tag_first(tags,["album","ALBUM"],data["album"])
                    data["year"]=self._tag_first(tags,["date","year","DATE"],data["year"])

                    cover_bytes=None
                    try:
                        for key in tags.keys():
                            obj=tags[key]
                            if str(key).startswith("APIC"):
                                cover_bytes=getattr(obj,"data",None)
                                if cover_bytes:
                                    break
                    except Exception:
                        pass
                    try:
                        pics=getattr(audio,"pictures",[])
                        if pics and not cover_bytes:
                            cover_bytes=pics[0].data
                    except Exception:
                        pass
                    try:
                        covr=tags.get("covr") if hasattr(tags,"get") else None
                        if covr and not cover_bytes:
                            cover_bytes=bytes(covr[0])
                    except Exception:
                        pass

                    if cover_bytes:
                        import hashlib as _hashlib
                        cp=self.cover_dir/(_hashlib.md5(str(p).encode("utf-8")).hexdigest()+".jpg")
                        cp.write_bytes(cover_bytes)
                        data["cover_path"]=str(cp)
        except Exception:
            pass

        br=data["bitrate"]
        sr=data["samplerate"]
        ext=p.suffix.lower()
        if ext in (".wav",".flac",".aiff",".aif",".alac"):
            q="无损/PCM"
        elif br>=320000:
            q="高码率"
        elif br>=192000:
            q="标准"
        elif br>0:
            q="较低码率"
        else:
            q="待检测"
        if sr and sr<32000:
            q+=" · 低采样率"
        data["quality"]=q
        return data

    def _fingerprint(self,path):
        h=hashlib.sha256()
        with open(path,"rb") as f:
            while True:
                b=f.read(1024*1024)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()

    def scan_imports(self):
        self.progress.setValue(2)
        QApplication.processEvents()
        result=scan_catalog(
            self.library_paths["originals"], self.db_path, self.cover_dir,
            lambda i,total,path: (
                self.progress.setValue(int(i/max(1,total)*95)),
                QApplication.processEvents(),
            ),
        )
        self.progress.setValue(100)
        self.refresh_library()
        QMessageBox.information(
            self,"歌曲库扫描完成",
            f"目录：{self.library_paths['originals']}\n新增 {result['added']} 首，更新 {result['updated']} 首，跳过 {result['skipped']} 首，失败 {result['failed']} 首。"
        )
        return
        candidates=[]
        fpfile=BASE_DIR/"imports"/"fingerprints.json"
        if fpfile.exists():
            try:
                fpdb=json.loads(fpfile.read_text(encoding="utf-8"))
                workdir=BASE_DIR/"imports"/"working"
                candidates=unique_import_candidates(
                    fpdb,
                    workdir.glob("*.wav") if workdir.exists() else [],
                    self._fingerprint,
                )
            except Exception:
                pass
        else:
            workdir=BASE_DIR/"imports"/"working"
            if workdir.exists():
                candidates=unique_import_candidates({},workdir.glob("*.wav"),self._fingerprint)

        total=max(1,len(candidates))
        con=self._db()
        added=0
        # Clean legacy duplicates created when a converted work WAV was scanned
        # once as an original source and once as a generated work file.
        existing_rows=con.execute(
            "SELECT id,source_path,working_path FROM tracks ORDER BY id"
        ).fetchall()
        keep_by_work={}
        for row in existing_rows:
            raw_work=row["working_path"] or row["source_path"] or ""
            if not raw_work:
                continue
            key=normalized_path(raw_work)
            current=keep_by_work.get(key)
            source_diff=normalized_path(row["source_path"] or "") != normalized_path(raw_work)
            if current is None:
                keep_by_work[key]=(int(row["id"]),source_diff)
            elif source_diff and not current[1]:
                con.execute("DELETE FROM tracks WHERE id=?",(current[0],))
                keep_by_work[key]=(int(row["id"]),True)
            else:
                con.execute("DELETE FROM tracks WHERE id=?",(row["id"],))
        for i,(fp,src,work,imported) in enumerate(candidates):
            self.progress.setValue(int(i/total*95))
            QApplication.processEvents()
            meta=self._extract_metadata(src if Path(src).exists() else work)
            try:
                same_work=con.execute(
                    "SELECT id,fingerprint FROM tracks WHERE working_path=? LIMIT 1",(work,)
                ).fetchone()
                if same_work and same_work["fingerprint"] != fp:
                    con.execute("DELETE FROM tracks WHERE id=?",(same_work["id"],))
                con.execute("""
                INSERT INTO tracks(
                    fingerprint,source_path,working_path,title,artist,album,year,
                    duration,bitrate,samplerate,channels,format,quality,cover_path,imported_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    source_path=excluded.source_path,
                    working_path=excluded.working_path,
                    title=excluded.title,
                    artist=excluded.artist,
                    album=excluded.album,
                    year=excluded.year,
                    duration=excluded.duration,
                    bitrate=excluded.bitrate,
                    samplerate=excluded.samplerate,
                    channels=excluded.channels,
                    format=excluded.format,
                    quality=excluded.quality,
                    cover_path=CASE WHEN excluded.cover_path<>'' THEN excluded.cover_path ELSE tracks.cover_path END
                """,(
                    fp,src,work,meta["title"],meta["artist"],meta["album"],meta["year"],
                    meta["duration"],meta["bitrate"],meta["samplerate"],meta["channels"],
                    meta["format"],meta["quality"],meta["cover_path"],imported
                ))
                added+=1
            except Exception:
                pass
        con.commit()
        con.close()
        self.progress.setValue(100)
        self.refresh_library()
        QMessageBox.information(self,"音乐库",f"扫描完成，共处理 {added} 首音乐。")

    def refresh_library(self):
        self.tree.clear()
        query=self.library_search.text() if hasattr(self,"library_search") else ""
        category=self.library_category.currentText() if hasattr(self,"library_category") else "全部"
        rows=list_catalog(self.db_path,query,category)
        artists={}
        for row in rows:
            artist=row["artist"] or "未知歌手"
            album=row["album"] or "未分类专辑"
            if artist not in artists:
                ai=QTreeWidgetItem([artist,""])
                ai.setData(0,Qt.UserRole,("artist",artist))
                self.tree.addTopLevelItem(ai)
                artists[artist]=(ai,{})
            ai,albums=artists[artist]
            if album not in albums:
                alb=QTreeWidgetItem([album,""])
                alb.setData(0,Qt.UserRole,("album",artist,album))
                ai.addChild(alb)
                albums[album]=alb
            ti=QTreeWidgetItem([
                row["title"] or Path(row["working_path"]).stem,
                f'{row["duration"]:.0f}s · {row["quality"]}'
            ])
            ti.setData(0,Qt.UserRole,("track",int(row["id"])))
            albums[album].addChild(ti)

        for artist,(ai,albums) in artists.items():
            count=sum(alb.childCount() for alb in albums.values())
            ai.setText(1,f"{count} 首")
            for alb in albums.values():
                alb.setText(1,f"{alb.childCount()} 首")

    def _selected_track_id(self):
        items=self.tree.selectedItems()
        if not items:
            return None
        data=items[0].data(0,Qt.UserRole)
        if data and data[0]=="track":
            return int(data[1])
        return None

    def show_selected(self):
        tid=self._selected_track_id()
        if not tid:
            return
        con=self._db()
        row=con.execute("SELECT * FROM tracks WHERE id=?",(tid,)).fetchone()
        con.close()
        if not row:
            return

        dur=self.main._format_time(row["duration"])
        br=f'{row["bitrate"]/1000:.0f} kbps' if row["bitrate"] else "-"
        sr=f'{row["samplerate"]/1000:.1f} kHz' if row["samplerate"] else "-"
        self.detail.setText(
            f'歌曲：{row["title"]}\n歌手：{row["artist"]}\n专辑：{row["album"]}\n'
            f'时长：{dur}\n格式：{row["format"]}\n码率：{br}\n采样率：{sr}\n'
            f'声道：{row["channels"] or "-"}\n音质：{row["quality"]}\n'
            f'BPM：{row["bpm"] if row["bpm"] is not None else "未分析"}\n'
            f'调性：{row["musical_key"] or "未分析"}\n六轨：{row["stems_status"]}'
        )
        cp=row["cover_path"]
        if cp and Path(cp).exists():
            pix=QPixmap(cp)
            self.cover.setPixmap(pix.scaled(210,210,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        else:
            self.cover.setPixmap(QPixmap())
            self.cover.setText("无封面")

    def batch_analyze(self):
        con=self._db()
        rows=con.execute("SELECT id,working_path,title FROM tracks WHERE analysis_status<>'完成' OR analysis_status IS NULL").fetchall()
        total=max(1,len(rows))
        done=0
        for i,row in enumerate(rows):
            self.progress.setValue(int(i/total*95))
            QApplication.processEvents()
            try:
                import librosa
                y,sr=librosa.load(row["working_path"],sr=22050,mono=True,duration=240)
                tempo,_=librosa.beat.beat_track(y=y,sr=sr)
                bpm=float(np.asarray(tempo).reshape(-1)[0])
                chroma=librosa.feature.chroma_cqt(y=y,sr=sr)
                names=["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
                key=names[int(np.argmax(np.mean(chroma,axis=1)))]
                con.execute(
                    "UPDATE tracks SET bpm=?,musical_key=?,analysis_status='完成' WHERE id=?",
                    (round(bpm,1),key,row["id"])
                )
                done+=1
            except Exception as e:
                con.execute(
                    "UPDATE tracks SET analysis_status=? WHERE id=?",
                    (f"失败:{str(e)[:80]}",row["id"])
                )
        con.commit()
        con.close()
        self.progress.setValue(100)
        self.refresh_library()
        QMessageBox.information(self,"批量分析",f"完成 {done} 首歌曲的 BPM/调性分析。")

    def enqueue_stems(self):
        con=self._db()
        rows=con.execute(
            "SELECT id,title,working_path,stems_status FROM tracks "
            "WHERE stems_status<>'完成' OR stems_status IS NULL ORDER BY artist,album,title"
        ).fetchall()
        self.batch_queue=[]
        for row in rows:
            self.batch_queue.append({
                "id":int(row["id"]),
                "title":row["title"],
                "path":row["working_path"],
                "status":"待处理",
                "progress":0,
                "attempts":0,
                "error":"",
                "stem_dir":""
            })
            con.execute("UPDATE tracks SET stems_status='已排队' WHERE id=?",(row["id"],))
        con.commit()
        con.close()
        self._save_batch_queue()
        self.refresh_task_table()
        self.total_progress.setValue(0)
        self.current_progress.setValue(0)
        self.batch_status.setText(f"批处理：已排队 {len(self.batch_queue)} 首")
        QMessageBox.information(self,"六轨队列",f"已建立 {len(self.batch_queue)} 首歌曲的六轨任务队列。")

    def _batch_queue_file(self):
        return BASE_DIR/"library"/"stem_queue.json"

    def _save_batch_queue(self):
        p=self._batch_queue_file()
        atomic_write_json(p, self.batch_queue)

    def _load_batch_queue(self):
        p=self._batch_queue_file()
        if not p.exists():
            return
        try:
            self.batch_queue=json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            self.batch_queue=[]

    def refresh_task_table(self):
        self.task_table.setRowCount(len(self.batch_queue))
        for r,item in enumerate(self.batch_queue):
            vals=[
                str(r+1),
                item.get("title",""),
                item.get("device","-"),
                item.get("status",""),
                f'{int(item.get("progress",0))}%',
                item.get("error","")
            ]
            for c,v in enumerate(vals):
                self.task_table.setItem(r,c,QTableWidgetItem(str(v)))

    def _next_batch_index(self):
        for i,item in enumerate(self.batch_queue):
            if item.get("status") in ("待处理","等待重试"):
                return i
        return -1

    def start_batch_processing(self):
        if self.batch_running:
            if self.batch_paused:
                self.batch_paused=False
                self.btn_batch_pause.setText("⏸ 暂停")
                self.batch_status.setText("批处理：继续执行")
                self._start_next_batch_task()
            return

        if not self.batch_queue:
            self._load_batch_queue()
        if not self.batch_queue:
            self.enqueue_stems()
        if not self.batch_queue:
            QMessageBox.information(self,"批处理","没有待处理歌曲。")
            return

        self.batch_running=True
        self.batch_paused=False
        self.batch_completed=sum(1 for x in self.batch_queue if x.get("status")=="完成")
        self.batch_failed=sum(1 for x in self.batch_queue if x.get("status")=="失败")
        self.btn_batch_pause.setText("⏸ 暂停")
        self.batch_status.setText("批处理：正在启动")
        self._update_total_progress()
        self._start_next_batch_task()

    def toggle_batch_pause(self):
        if not self.batch_running:
            return
        self.batch_paused=not self.batch_paused
        if self.batch_paused:
            self.btn_batch_pause.setText("▶ 继续")
            if self.batch_worker and self.batch_worker.isRunning():
                self.batch_status.setText("批处理：将在当前歌曲完成后暂停")
            else:
                self.batch_status.setText("批处理：已暂停")
        else:
            self.btn_batch_pause.setText("⏸ 暂停")
            self.batch_status.setText("批处理：继续执行")
            if not self.batch_worker or not self.batch_worker.isRunning():
                self._start_next_batch_task()

    def retry_failed_tasks(self):
        count=0
        for item in self.batch_queue:
            if item.get("status")=="失败":
                item["status"]="等待重试"
                item["progress"]=0
                item["error"]=""
                count+=1
        self._save_batch_queue()
        self.refresh_task_table()
        if count:
            self.batch_running=True
            self.batch_paused=False
            self._start_next_batch_task()
        else:
            QMessageBox.information(self,"重试失败","当前没有失败任务。")

    def _device_for_batch(self):
        mode=self.device_mode.currentText()
        if mode=="仅 CPU":
            return "cpu"
        try:
            import torch
            cuda=torch.cuda.is_available()
        except Exception:
            cuda=False
        if mode=="优先 NVIDIA GPU" and not cuda:
            return "cpu"
        return "cuda" if cuda else "cpu"

    def _start_next_batch_task(self):
        if not self.batch_running or self.batch_paused:
            return
        if self.batch_worker and self.batch_worker.isRunning():
            return

        idx=self._next_batch_index()
        if idx<0:
            self.batch_running=False
            self.batch_status.setText(
                f"批处理完成：成功 {sum(1 for x in self.batch_queue if x.get('status')=='完成')} / "
                f"失败 {sum(1 for x in self.batch_queue if x.get('status')=='失败')}"
            )
            self.current_progress.setValue(100)
            self.total_progress.setValue(100)
            self._save_batch_queue()
            self.refresh_library()
            return

        self.batch_index=idx
        item=self.batch_queue[idx]
        item["status"]="处理中"
        item["attempts"]=int(item.get("attempts",0))+1
        item["device"]=self._device_for_batch().upper()
        item["progress"]=0
        item["error"]=""
        self.current_progress.setValue(0)
        self.batch_status.setText(
            f"批处理：{idx+1}/{len(self.batch_queue)} · {item.get('title','')}"
        )
        self.refresh_task_table()
        self._save_batch_queue()

        # Use the stable single-song worker already proven by the main six-track page.
        self.batch_worker=SeparationWorker(item["path"])
        active_worker=self.batch_worker
        self.batch_worker.model_progress.connect(self._on_batch_model_progress)
        self.batch_worker.separation_progress.connect(self._on_batch_song_progress)
        self.batch_worker.done.connect(self._on_batch_song_done)
        self.batch_worker.failed.connect(self._on_batch_song_failed)
        self.batch_worker.finished.connect(lambda w=active_worker:self._release_batch_worker(w))
        self.batch_worker.start()

    def _release_batch_worker(self,worker):
        if self.batch_worker is worker:
            self.batch_worker=None
            if self.batch_running and not self.batch_paused:
                QTimer.singleShot(0,self._start_next_batch_task)

    def _on_batch_model_progress(self,value,text):
        # Model preparation occupies the first 5% of the task display.
        v=min(5,max(0,int(value*0.05)))
        if 0<=self.batch_index<len(self.batch_queue):
            self.batch_queue[self.batch_index]["progress"]=v
        self.current_progress.setValue(v)
        self.batch_status.setText(text)
        self.refresh_task_table()

    def _on_batch_song_progress(self,value,text):
        v=5+int(max(0,min(100,value))*0.95)
        if 0<=self.batch_index<len(self.batch_queue):
            self.batch_queue[self.batch_index]["progress"]=min(100,v)
        self.current_progress.setValue(min(100,v))
        self.batch_status.setText(
            f"{self.batch_index+1}/{len(self.batch_queue)} · {text}"
        )
        self.refresh_task_table()
        self._update_total_progress()

    def _on_batch_song_done(self,stem_dir):
        if not (0<=self.batch_index<len(self.batch_queue)):
            return
        item=self.batch_queue[self.batch_index]
        item["status"]="完成"
        item["progress"]=100
        item["stem_dir"]=stem_dir
        item["error"]=""
        self.batch_completed+=1

        con=self._db()
        con.execute("UPDATE tracks SET stems_status='完成' WHERE id=?",(item["id"],))
        con.commit()
        con.close()

        if self.after_analysis.isChecked():
            self._post_analyze_track(item)
        if self.after_score.isChecked():
            item["score_status"]="待出谱"

        self._save_batch_queue()
        self.refresh_task_table()
        self._update_total_progress()
        if self.batch_paused:
            self.batch_status.setText("批处理：当前歌曲完成，已暂停")
        else:
            QTimer.singleShot(250,self._start_next_batch_task)

    def _on_batch_song_failed(self,error):
        if not (0<=self.batch_index<len(self.batch_queue)):
            return
        item=self.batch_queue[self.batch_index]
        attempts=int(item.get("attempts",1))
        auto_retry=self.retry_failed.isChecked() and attempts<2
        if auto_retry:
            item["status"]="等待重试"
            item["error"]=str(error).splitlines()[0][:180]
            item["progress"]=0
        else:
            item["status"]="失败"
            item["error"]=str(error).splitlines()[0][:180]
            item["progress"]=0
            self.batch_failed+=1
            con=self._db()
            con.execute(
                "UPDATE tracks SET stems_status=? WHERE id=?",
                (f"失败:{item['error'][:80]}",item["id"])
            )
            con.commit()
            con.close()

        self._save_batch_queue()
        self.refresh_task_table()
        self._update_total_progress()
        if self.batch_paused:
            self.batch_status.setText("批处理：已暂停")
        else:
            QTimer.singleShot(400,self._start_next_batch_task)

    def _post_analyze_track(self,item):
        try:
            import librosa
            y,sr=librosa.load(item["path"],sr=22050,mono=True,duration=240)
            tempo,_=librosa.beat.beat_track(y=y,sr=sr)
            bpm=float(np.asarray(tempo).reshape(-1)[0])
            chroma=librosa.feature.chroma_cqt(y=y,sr=sr)
            names=["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
            key=names[int(np.argmax(np.mean(chroma,axis=1)))]
            con=self._db()
            con.execute(
                "UPDATE tracks SET bpm=?,musical_key=?,analysis_status='完成' WHERE id=?",
                (round(bpm,1),key,item["id"])
            )
            con.commit()
            con.close()
            item["analysis_status"]="完成"
        except Exception as e:
            item["analysis_status"]="失败:"+str(e)[:80]

    def _update_total_progress(self):
        total=max(1,len(self.batch_queue))
        progress=sum(float(x.get("progress",0)) for x in self.batch_queue)/total
        self.total_progress.setValue(int(progress))




    def refresh_gpu_list(self):
        if not hasattr(self,"gpu_selector"):
            return
        self.gpu_selector.clear()
        added=0
        try:
            import torch
            count=torch.cuda.device_count()
            for i in range(count):
                name=torch.cuda.get_device_name(i)
                self.gpu_selector.addItem(f"GPU {i}: {name}",i)
                added+=1
        except Exception:
            pass
        if added==0:
            self.gpu_selector.addItem("CPU / 未检测到 CUDA",-1)

    def _query_gpu_state(self):
        idx=self.gpu_selector.currentData() if hasattr(self,"gpu_selector") else -1
        if idx is None or int(idx)<0:
            return {"available":False,"index":-1,"memory_percent":0,"temperature":0}
        state={"available":True,"index":int(idx),"memory_percent":0,"temperature":0}
        try:
            import torch
            props=torch.cuda.get_device_properties(int(idx))
            total=float(props.total_memory)
            reserved=float(torch.cuda.memory_reserved(int(idx)))
            state["memory_percent"]=100.0*reserved/max(1.0,total)
        except Exception:
            pass
        try:
            import subprocess, re as _re
            p=subprocess.run(
                ["nvidia-smi","--query-gpu=index,temperature.gpu,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True,text=True,timeout=5
            )
            if p.returncode==0:
                for line in p.stdout.splitlines():
                    parts=[x.strip() for x in line.split(",")]
                    if len(parts)>=4 and int(parts[0])==int(idx):
                        state["temperature"]=float(parts[1])
                        used=float(parts[2]); total=float(parts[3])
                        state["memory_percent"]=100.0*used/max(1.0,total)
                        break
        except Exception:
            pass
        self.scheduler_last_gpu_state=state
        return state

    def _in_night_window(self):
        if not hasattr(self,"night_mode") or not self.night_mode.isChecked():
            return True
        h=time.localtime().tm_hour
        start=int(self.night_start.currentData())
        end=int(self.night_end.currentData())
        if start==end:
            return True
        if start<end:
            return start<=h<end
        return h>=start or h<end

    def _scheduler_allows_start(self):
        if not self._in_night_window():
            self.scheduler_status.setText(
                f"调度器：等待夜间窗口 {self.night_start.currentText()} - {self.night_end.currentText()}"
            )
            return False

        state=self._query_gpu_state()
        if state.get("available"):
            mem_limit=self.gpu_memory_limit.value()
            temp_limit=self.gpu_temp_limit.value()
            if state.get("memory_percent",0)>=mem_limit:
                self.scheduler_status.setText(
                    f"调度器：GPU 显存 {state['memory_percent']:.0f}% ≥ 限制 {mem_limit}%"
                )
                return False
            if state.get("temperature",0)>0 and state["temperature"]>=temp_limit:
                self.scheduler_status.setText(
                    f"调度器：GPU {state['temperature']:.0f}°C ≥ 限制 {temp_limit}°C，等待降温"
                )
                return False
            self.scheduler_status.setText(
                f"调度器：GPU 正常 · 显存 {state['memory_percent']:.0f}% · "
                f"{state['temperature']:.0f}°C"
            )
        else:
            self.scheduler_status.setText("调度器：CPU 模式")
        return True

    def _scheduler_tick(self):
        if getattr(self,"pipeline_running",False) and not getattr(self,"pipeline_paused",False):
            stem_worker=getattr(self,"pipeline_batch_worker",None)
            stage_worker=getattr(self,"pipeline_stage_worker",None)
            if not (stem_worker and stem_worker.isRunning()) and not (stage_worker and stage_worker.isRunning()):
                if self._scheduler_allows_start():
                    self._start_next_pipeline_job()

    def sort_pipeline_by_priority(self):
        rank={"高":0,"普通":1,"低":2}
        self.pipeline_jobs.sort(
            key=lambda j:(rank.get(j.get("priority","普通"),1),j.get("created_at",0))
        )
        self._save_pipeline_jobs()
        self.refresh_pipeline_table()

    def set_selected_job_priority(self,priority):
        row=self.pipeline_table.currentRow()
        if row<0 or row>=len(self.pipeline_jobs):
            return
        self.pipeline_jobs[row]["priority"]=priority
        self.sort_pipeline_by_priority()

    def _retry_backoff_ready(self,job):
        return time.time() >= float(job.get("next_retry_at",0) or 0)

    def _mark_job_retry(self,job):
        count=int(job.get("retry_count",0))+1
        job["retry_count"]=count
        delay=min(300,self.scheduler_backoff_seconds*(2**max(0,count-1)))
        job["next_retry_at"]=time.time()+delay
        job["status"]="待处理"
        return delay

    def _pipeline_file(self):
        return BASE_DIR/"library"/"auto_pipeline_jobs.json"

    def _save_pipeline_jobs(self):
        p=self._pipeline_file()
        atomic_write_json(p, self.pipeline_jobs)

    def _load_pipeline_jobs(self):
        p=self._pipeline_file()
        if not p.exists():
            return
        try:
            self.pipeline_jobs=json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            self.pipeline_jobs=[]

    def _enabled_pipeline_stages(self):
        return [
            s for s,cb in [
                ("stems",self.pipe_stems),
                ("analysis",self.pipe_analysis),
                ("chords",self.pipe_chords),
                ("score",self.pipe_score),
                ("arrangement",self.pipe_arrange),
                ("render",self.pipe_render),
                ("library",None),
            ] if cb is None or cb.isChecked()
        ]

    def _new_pipeline_job(self,row):
        return {
            "track_id":int(row["id"]),
            "title":row["title"],
            "priority":self.default_priority.currentText() if hasattr(self,"default_priority") else "普通",
            "retry_count":0,
            "next_retry_at":0,
            "path":row["working_path"],
            "stem_dir":"",
            "stages":{s:"待处理" for s in self.pipeline_stage_order},
            "status":"待处理",
            "error":"",
            "created_at":time.time(),
            "updated_at":time.time(),
            "artifacts":{}
        }

    def build_pipeline_jobs(self):
        con=self._db()
        rows=con.execute("SELECT id,title,working_path FROM tracks ORDER BY artist,album,title").fetchall()
        con.close()
        self.pipeline_jobs=[self._new_pipeline_job(r) for r in rows if r["working_path"] and Path(r["working_path"]).exists()]
        self.sort_pipeline_by_priority()
        self._save_pipeline_jobs()
        self.refresh_pipeline_table()

    def refresh_pipeline_table(self):
        self.pipeline_table.setRowCount(len(self.pipeline_jobs))
        for r,job in enumerate(self.pipeline_jobs):
            st=job.get("stages",{})
            vals=[
                job.get("priority","普通"),
                job.get("title",""),
                st.get("stems","-"),
                st.get("analysis","-"),
                st.get("chords","-"),
                st.get("score","-"),
                st.get("arrangement","-"),
                st.get("render","-"),
                st.get("library","-"),
                job.get("status","")
            ]
            for c,v in enumerate(vals):
                self.pipeline_table.setItem(r,c,QTableWidgetItem(str(v)))

    def start_auto_pipeline(self):
        if self.pipeline_executor.currentText().startswith("云端"):
            QMessageBox.information(
                self,"云端执行器",
                "v2.0.0 已预留云端执行器接口，但当前 Windows 测试版尚未绑定服务器 API。\n"
                "请先使用“本地执行器”。"
            )
            return

        if not self.pipeline_jobs:
            self.build_pipeline_jobs()
        if not self.pipeline_jobs:
            QMessageBox.information(self,"自动流水线","音乐库中没有可处理歌曲。")
            return

        self.pipeline_running=True
        self.pipeline_paused=False
        self.pipe_pause.setText("暂停流水线")
        self.pipeline_status.setText(f"流水线：{len(self.pipeline_jobs)} 首待处理")
        self._start_next_pipeline_job()

    def toggle_pipeline_pause(self):
        if not self.pipeline_running:
            return
        self.pipeline_paused=not self.pipeline_paused
        if self.pipeline_paused:
            self.pipe_pause.setText("继续流水线")
            self.pipeline_status.setText("流水线：将在当前阶段安全完成后暂停")
        else:
            self.pipe_pause.setText("暂停流水线")
            self.pipeline_status.setText("流水线：继续执行")
            QTimer.singleShot(100,self._start_next_pipeline_job)

    def resume_failed_pipeline_jobs(self):
        count=0
        for job in self.pipeline_jobs:
            if job.get("status")=="失败":
                job["status"]="待处理"
                job["error"]=""
                for stage,state in job.get("stages",{}).items():
                    if state.startswith("失败"):
                        job["stages"][stage]="待处理"
                count+=1
        self._save_pipeline_jobs()
        self.refresh_pipeline_table()
        if count:
            self.pipeline_running=True
            self.pipeline_paused=False
            self._start_next_pipeline_job()
        else:
            QMessageBox.information(self,"继续失败任务","当前没有失败任务。")

    def _pipeline_next_job_index(self):
        enabled=self._enabled_pipeline_stages()
        for i,job in enumerate(self.pipeline_jobs):
            if job.get("status") in ("待处理","处理中"):
                if not self._retry_backoff_ready(job):
                    continue
                for s in enabled:
                    if job.get("stages",{}).get(s,"待处理")!="完成":
                        return i
        return -1

    def _pipeline_next_stage(self,job):
        for s in self._enabled_pipeline_stages():
            if job.get("stages",{}).get(s,"待处理")!="完成":
                return s
        return ""

    def _pipeline_update_progress(self):
        enabled=self._enabled_pipeline_stages()
        total=max(1,len(self.pipeline_jobs)*len(enabled))
        done=0
        for job in self.pipeline_jobs:
            for s in enabled:
                if job.get("stages",{}).get(s)=="完成":
                    done+=1
        self.pipeline_progress.setValue(int(done/total*100))

    def _start_next_pipeline_job(self):
        if not self.pipeline_running or self.pipeline_paused:
            return
        if self.pipeline_batch_worker and self.pipeline_batch_worker.isRunning():
            return
        if self.pipeline_stage_worker and self.pipeline_stage_worker.isRunning():
            return
        if not self._scheduler_allows_start():
            return
        idx=self._pipeline_next_job_index()
        if idx<0:
            enabled=self._enabled_pipeline_stages()
            pending=[
                item for item in self.pipeline_jobs
                if item.get("status") in ("待处理","处理中")
                and any(item.get("stages",{}).get(s,"待处理")!="完成" for s in enabled)
            ]
            if pending:
                future=[float(x.get("next_retry_at",0) or 0) for x in pending]
                wait=max(1,int(min(future)-time.time())) if any(future) else 1
                self.pipeline_status.setText(f"流水线：失败任务退避中，约 {wait} 秒后继续")
                QTimer.singleShot(1000,self._start_next_pipeline_job)
                return
            self.pipeline_running=False
            self.pipeline_status.setText("流水线：全部完成")
            self.pipeline_progress.setValue(100)
            self._save_pipeline_jobs()
            self.refresh_library()
            return

        self.pipeline_job_index=idx
        job=self.pipeline_jobs[idx]
        stage=self._pipeline_next_stage(job)
        if not stage:
            job["status"]="完成"
            QTimer.singleShot(50,self._start_next_pipeline_job)
            return

        job["status"]="处理中"
        job["stages"][stage]="处理中"
        job["updated_at"]=time.time()
        self.pipeline_stage=stage
        self.refresh_pipeline_table()
        self._save_pipeline_jobs()

        stage_name={
            "stems":"六轨分离","analysis":"BPM/调性","chords":"和弦/段落",
            "score":"乐谱","arrangement":"智能编配","render":"渲染","library":"入库"
        }.get(stage,stage)
        self.pipeline_status.setText(
            f"流水线：{idx+1}/{len(self.pipeline_jobs)} · {job['title']} · {stage_name}"
        )

        if stage=="stems":
            self._pipeline_run_stems(job)
        else:
            QTimer.singleShot(10,lambda: self._pipeline_run_sync_stage(stage,job))

    def _pipeline_fail(self,job,stage,error):
        job["stages"][stage]="失败"
        job["error"]=str(error)[:300]
        if int(job.get("retry_count",0)) < 2:
            delay=self._mark_job_retry(job)
            job["error"]=f"{job['error']} · {delay}s 后自动重试"
            job["stages"][stage]="待处理"
        else:
            job["status"]="失败"
        job["updated_at"]=time.time()
        self._save_pipeline_jobs()
        self.refresh_pipeline_table()
        self._pipeline_update_progress()
        self.pipeline_status.setText(f"流水线失败：{job['title']} · {stage} · {job['error']}")
        if not self.pipeline_paused:
            QTimer.singleShot(200,self._start_next_pipeline_job)

    def _pipeline_complete_stage(self,job,stage):
        job["stages"][stage]="完成"
        job["updated_at"]=time.time()
        job["retry_count"]=0
        job["next_retry_at"]=0
        if not self._pipeline_next_stage(job):
            job["status"]="完成"
        self._save_pipeline_jobs()
        self.refresh_pipeline_table()
        self._pipeline_update_progress()
        if self.pipeline_paused:
            self.pipeline_status.setText("流水线：已暂停")
        else:
            QTimer.singleShot(100,self._start_next_pipeline_job)

    def _pipeline_run_stems(self,job):
        gpu_index=self.gpu_selector.currentData() if hasattr(self,"gpu_selector") else -1
        job["gpu_index"]=int(gpu_index) if gpu_index is not None else -1
        self.pipeline_batch_worker=SeparationWorker(job["path"])
        active_worker=self.pipeline_batch_worker
        self.pipeline_batch_worker.separation_progress.connect(
            lambda v,t:self.pipeline_status.setText(f"流水线：{job['title']} · 六轨 {v}%")
        )
        self.pipeline_batch_worker.done.connect(
            lambda stem_dir:self._pipeline_stems_done(job,stem_dir)
        )
        self.pipeline_batch_worker.failed.connect(
            lambda err:self._pipeline_fail(job,"stems",err)
        )
        self.pipeline_batch_worker.finished.connect(
            lambda w=active_worker:self._release_pipeline_batch_worker(w)
        )
        self.pipeline_batch_worker.start()

    def _release_pipeline_batch_worker(self,worker):
        if self.pipeline_batch_worker is worker:
            self.pipeline_batch_worker=None
            if self.pipeline_running and not self.pipeline_paused:
                QTimer.singleShot(0,self._start_next_pipeline_job)

    def _pipeline_stems_done(self,job,stem_dir):
        job["stem_dir"]=stem_dir
        job["artifacts"]["stems"]=stem_dir
        con=self._db()
        con.execute("UPDATE tracks SET stems_status='完成' WHERE id=?",(job["track_id"],))
        con.commit(); con.close()
        self._pipeline_complete_stage(job,"stems")

    def _pipeline_run_sync_stage(self,stage,job):
        try:
            if stage=="render":
                try:
                    job["render_soundfont"]=self.main.arrangement.soundfont_edit.text().strip()
                except Exception:
                    job["render_soundfont"]=""
                job["render_output"]=self.pipeline_output.currentText()
            operations={
                "analysis":lambda:self._pipeline_stage_analysis(job),
                "chords":lambda:self._pipeline_stage_chords(job),
                "score":lambda:self._pipeline_stage_score(job),
                "arrangement":lambda:self._pipeline_stage_arrangement(job),
                "render":lambda:self._pipeline_stage_render(job),
                "library":lambda:self._pipeline_stage_library(job),
            }
            operation=operations.get(stage)
            if operation is None:
                raise RuntimeError(f"未知流水线阶段：{stage}")
            self.pipeline_stage_worker=PipelineStageWorker(operation)
            active_worker=self.pipeline_stage_worker
            self.pipeline_stage_worker.succeeded.connect(
                lambda:self._pipeline_complete_stage(job,stage)
            )
            self.pipeline_stage_worker.failed.connect(
                lambda error:self._pipeline_fail(job,stage,error)
            )
            self.pipeline_stage_worker.finished.connect(
                lambda w=active_worker:self._release_pipeline_stage_worker(w)
            )
            self.pipeline_stage_worker.start()
        except Exception as e:
            self._pipeline_fail(job,stage,e)

    def _release_pipeline_stage_worker(self,worker):
        if self.pipeline_stage_worker is worker:
            self.pipeline_stage_worker=None
            if self.pipeline_running and not self.pipeline_paused:
                QTimer.singleShot(0,self._start_next_pipeline_job)

    def _pipeline_stage_analysis(self,job):
        import librosa
        y,sr=librosa.load(job["path"],sr=22050,mono=True,duration=240)
        tempo,_=librosa.beat.beat_track(y=y,sr=sr)
        bpm=float(np.asarray(tempo).reshape(-1)[0])
        chroma=librosa.feature.chroma_cqt(y=y,sr=sr)
        names=["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
        key=names[int(np.argmax(np.mean(chroma,axis=1)))]
        job["artifacts"]["analysis"]={"bpm":round(bpm,1),"key":key}
        con=self._db()
        con.execute(
            "UPDATE tracks SET bpm=?,musical_key=?,analysis_status='完成' WHERE id=?",
            (round(bpm,1),key,job["track_id"])
        )
        con.commit(); con.close()

    def _pipeline_stage_chords(self,job):
        import librosa
        y,sr=librosa.load(job["path"],sr=22050,mono=True)
        tempo,beat_frames=librosa.beat.beat_track(y=y,sr=sr)
        beat_times=librosa.frames_to_time(beat_frames,sr=sr)
        chroma=librosa.feature.chroma_cqt(y=y,sr=sr)
        beat_chroma=librosa.util.sync(chroma,beat_frames,aggregate=np.median)

        names=["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
        templates=[]
        for root in range(12):
            for suffix,ints in [("",[0,4,7]),("m",[0,3,7]),("7",[0,4,7,10]),("maj7",[0,4,7,11]),("m7",[0,3,7,10])]:
                t=np.zeros(12,float)
                for k in ints:t[(root+k)%12]=1.0
                templates.append((names[root]+suffix,t/(np.linalg.norm(t)+1e-9)))

        chords=[]
        for i in range(beat_chroma.shape[1]):
            v=beat_chroma[:,i].astype(float)
            v=v/(np.linalg.norm(v)+1e-9)
            best=max(((float(np.dot(v,t)),name) for name,t in templates),key=lambda x:x[0])
            chords.append(best[1])

        rows=[]
        for start in range(0,min(len(chords),len(beat_times)),4):
            seq=chords[start:start+4]
            compact=[]
            for c in seq:
                if not compact or compact[-1]!=c:compact.append(c)
            rows.append({
                "bar":len(rows)+1,
                "seconds":float(beat_times[start]),
                "chords":compact,
                "section":f"段落 {len(rows)//8+1}"
            })

        out=BASE_DIR/"pipeline"/"chords"
        out.mkdir(parents=True,exist_ok=True)
        p=out/f"{job['track_id']}_chords.json"
        p.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
        job["artifacts"]["chords"]=str(p)
        job["artifacts"]["chord_timeline"]=rows

        con=self._db()
        con.execute("UPDATE tracks SET chords_status='完成' WHERE id=?",(job["track_id"],))
        con.commit(); con.close()

    def _pipeline_stage_score(self,job):
        rows=job["artifacts"].get("chord_timeline")
        if not rows:
            cp=job["artifacts"].get("chords","")
            if cp and Path(cp).exists():
                rows=json.loads(Path(cp).read_text(encoding="utf-8"))
        if not rows:
            raise RuntimeError("没有和弦时间线，无法出谱")

        outdir=BASE_DIR/"pipeline"/"scores"
        outdir.mkdir(parents=True,exist_ok=True)
        p=outdir/f"{job['track_id']}_lead_sheet.html"
        trs=[]
        for row in rows:
            trs.append(
                f"<tr><td>{row['bar']}</td><td>{self.main._format_time(row['seconds'])}</td>"
                f"<td>{html.escape(row['section'])}</td><td>{html.escape(' / '.join(row['chords']))}</td></tr>"
            )
        page=f"""<!doctype html><meta charset='utf-8'><style>
        body{{font-family:'Microsoft YaHei UI';background:#09111f;color:#edf3ff;padding:30px}}
        table{{width:100%;border-collapse:collapse}}td,th{{padding:9px;border-bottom:1px solid #253451}}
        </style><h1>{html.escape(job['title'])}</h1>
        <table><tr><th>小节</th><th>时间</th><th>段落</th><th>和弦</th></tr>{''.join(trs)}</table>"""
        p.write_text(page,encoding="utf-8")
        job["artifacts"]["score"]=str(p)
        con=self._db()
        con.execute("UPDATE tracks SET score_status='完成' WHERE id=?",(job["track_id"],))
        con.commit(); con.close()

    def _pipeline_stage_arrangement(self,job):
        rows=job["artifacts"].get("chord_timeline")
        if not rows:
            raise RuntimeError("缺少和弦时间线")

        from mido import MidiFile,MidiTrack,Message,MetaMessage,bpm2tempo
        analysis=job["artifacts"].get("analysis",{})
        bpm=float(analysis.get("bpm",120) or 120)

        mid=MidiFile(ticks_per_beat=480)
        meta=MidiTrack();mid.tracks.append(meta)
        meta.append(MetaMessage('set_tempo',tempo=bpm2tempo(bpm),time=0))
        meta.append(MetaMessage('time_signature',numerator=4,denominator=4,time=0))

        guitar=MidiTrack();mid.tracks.append(guitar)
        bass=MidiTrack();mid.tracks.append(bass)
        piano=MidiTrack();mid.tracks.append(piano)
        drums=MidiTrack();mid.tracks.append(drums)

        note_map={"C":60,"C#":61,"D":62,"D#":63,"E":64,"F":65,"F#":66,"G":67,"G#":68,"A":69,"A#":70,"B":71}
        total=max(1,len(rows))
        for i,row in enumerate(rows):
            chord=(row.get("chords") or ["C"])[0]
            m=re.match(r"^([A-G](?:#)?)(m?)",chord)
            root=note_map.get(m.group(1) if m else "C",60)
            minor=bool(m and m.group(2)=="m")
            chord_notes=[root,root+(3 if minor else 4),root+7]

            # Musical Intelligence-style role estimate based on 8-bar blocks.
            block=i//8
            pos=i/max(1,total-1)
            if pos<0.12:
                role="intro"
            elif pos<0.45:
                role="verse"
            elif pos<0.68:
                role="chorus"
            elif pos<0.85:
                role="bridge"
            else:
                role="outro"

            strategy={
                "intro": {"g":0.52,"b":0.45,"d":0.35,"p":0.68,"fill":False},
                "verse": {"g":0.62,"b":0.58,"d":0.55,"p":0.58,"fill":False},
                "chorus":{"g":0.90,"b":0.88,"d":0.95,"p":0.80,"fill":True},
                "bridge":{"g":0.40,"b":0.50,"d":0.44,"p":0.75,"fill":False},
                "outro": {"g":0.48,"b":0.45,"d":0.35,"p":0.62,"fill":False},
            }[role]

            # Guitar
            gvel=int(42+45*strategy["g"])
            gsteps=8 if role=="chorus" else 4
            gdur=240 if gsteps==8 else 480
            for step in range(gsteps):
                if role in ("intro","bridge") and step%2==1:
                    n=chord_notes[step%len(chord_notes)]
                    guitar.append(Message('note_on',note=n,velocity=gvel,time=0,channel=0))
                    guitar.append(Message('note_off',note=n,velocity=0,time=gdur,channel=0))
                else:
                    for n in chord_notes:
                        guitar.append(Message('note_on',note=n,velocity=gvel,time=0,channel=0))
                    guitar.append(Message('note_off',note=chord_notes[0],velocity=0,time=int(gdur*.82),channel=0))
                    for n in chord_notes[1:]:
                        guitar.append(Message('note_off',note=n,velocity=0,time=0,channel=0))
                    guitar.append(Message('note_on',note=root,velocity=1,time=max(1,int(gdur*.18)),channel=0))
                    guitar.append(Message('note_off',note=root,velocity=0,time=0,channel=0))

            # Bass
            bvel=int(55+35*strategy["b"])
            bass_pattern=[root-24,root-17,root-24,root-12] if role=="chorus" else [root-24,root-17,root-24,root-17]
            for bn in bass_pattern:
                bn=max(28,min(72,bn))
                bass.append(Message('note_on',note=bn,velocity=bvel,time=0,channel=1))
                bass.append(Message('note_off',note=bn,velocity=0,time=480,channel=1))

            # Piano: more sustained in bridge/intro to avoid guitar masking.
            pvel=int(42+30*strategy["p"])
            if role in ("intro","bridge","outro"):
                for n in chord_notes:
                    piano.append(Message('note_on',note=n+12,velocity=pvel,time=0,channel=2))
                piano.append(Message('note_off',note=chord_notes[0]+12,velocity=0,time=1920,channel=2))
                for n in chord_notes[1:]:
                    piano.append(Message('note_off',note=n+12,velocity=0,time=0,channel=2))
            else:
                for beat in range(4):
                    n=chord_notes[beat%len(chord_notes)]+12
                    piano.append(Message('note_on',note=n,velocity=pvel,time=0,channel=2))
                    piano.append(Message('note_off',note=n,velocity=0,time=480,channel=2))

            # Drums
            dvel=int(45+50*strategy["d"])
            for e in range(8):
                events=[(42,max(35,dvel-25))]
                if e in (0,4):events.append((36,dvel))
                if e in (2,6):events.append((38,dvel))
                if role=="chorus" and e in (3,7):events.append((36,max(45,dvel-5))
                )
                for n,v in events:
                    drums.append(Message('note_on',note=n,velocity=min(120,v),time=0,channel=9))
                drums.append(Message('note_off',note=42,velocity=0,time=240,channel=9))
                for n,_ in events[1:]:
                    drums.append(Message('note_off',note=n,velocity=0,time=0,channel=9))

            if strategy["fill"] and (i+1)%8==0:
                for note in [45,47,50,38]:
                    drums.append(Message('note_on',note=note,velocity=min(120,dvel+10),time=0,channel=9))
                    drums.append(Message('note_off',note=note,velocity=0,time=120,channel=9))

        outdir=BASE_DIR/"pipeline"/"arrangements"
        outdir.mkdir(parents=True,exist_ok=True)
        p=outdir/f"{job['track_id']}_arrangement.mid"
        mid.save(str(p))
        job["artifacts"]["arrangement_midi"]=str(p)
        job["artifacts"]["arrangement_engine"]="Musical Intelligence Pipeline v2.1"
        con=self._db()
        con.execute("UPDATE tracks SET arrangement_status='完成' WHERE id=?",(job["track_id"],))
        con.commit();con.close()

    def _pipeline_stage_render(self,job):
        midi=job["artifacts"].get("arrangement_midi","")
        if not midi or not Path(midi).exists():
            raise RuntimeError("没有编配 MIDI")

        sf_path=str(job.get("render_soundfont","") or "")

        if not sf_path or not Path(sf_path).exists():
            # MIDI 编配已经是可交付成果。SoundFont 是可选的本地音色库，
            # 未配置时跳过音频渲染，不再让整条 AI 流水线失败。
            job["artifacts"]["render_notice"] = "未配置 SoundFont，已保留 MIDI 并跳过音频渲染"
            con=self._db()
            con.execute(
                "UPDATE tracks SET render_status='已跳过（未配置 SoundFont）' WHERE id=?",
                (job["track_id"],),
            )
            con.commit();con.close()
            return

        fluidsynth=self.main._find_fluidsynth()
        if not fluidsynth:
            raise RuntimeError("未找到 FluidSynth")

        outdir=BASE_DIR/"pipeline"/"rendered"
        outdir.mkdir(parents=True,exist_ok=True)
        wav=outdir/f"{job['track_id']}_final.wav"
        p=subprocess.run(
            [fluidsynth,"-ni",sf_path,midi,"-F",str(wav),"-r","44100"],
            capture_output=True,text=True,timeout=600
        )
        if p.returncode!=0 or not wav.exists():
            raise RuntimeError((p.stderr or p.stdout or "渲染失败")[-1500:])
        job["artifacts"]["final_wav"]=str(wav)

        if job.get("render_output")=="WAV + MP3":
            ffmpeg=self.main._find_ffmpeg()
            if not ffmpeg:
                raise RuntimeError("需要 MP3，但未找到 FFmpeg")
            mp3=outdir/f"{job['track_id']}_final.mp3"
            p2=subprocess.run(
                [ffmpeg,"-y","-i",str(wav),"-codec:a","libmp3lame","-b:a","320k",str(mp3)],
                capture_output=True,text=True,timeout=300
            )
            if p2.returncode!=0 or not mp3.exists():
                raise RuntimeError("MP3 编码失败")
            job["artifacts"]["final_mp3"]=str(mp3)

        con=self._db()
        con.execute(
            "UPDATE tracks SET render_status='完成',final_audio_path=? WHERE id=?",
            (str(wav),job["track_id"])
        )
        con.commit();con.close()

    def _pipeline_stage_library(self,job):
        # Final consistency checkpoint.
        con=self._db()
        row=con.execute("SELECT id FROM tracks WHERE id=?",(job["track_id"],)).fetchone()
        if not row:
            raise RuntimeError("音乐库中找不到歌曲记录")
        con.commit();con.close()
        job["artifacts"]["library_updated"]=True


    def load_selected_to_workspace(self):
        tid=self._selected_track_id()
        if not tid:
            return
        con=self._db()
        row=con.execute("SELECT working_path FROM tracks WHERE id=?",(tid,)).fetchone()
        con.close()
        if row and Path(row["working_path"]).exists():
            self.main.load_imported_working_file(row["working_path"])


class CommunityPage(QWidget):
    """Desktop account and beta community client backed by mobile_api.py."""

    CONFIG_FILE = BASE_DIR / "config" / "community.json"

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.token = ""
        self.username = ""
        self.nickname = ""

        root = QVBoxLayout(self)
        title = QLabel("账号 / 内测群聊")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        hint = QLabel("Windows、Android 与 iOS 使用同一账号和群聊；服务器可填写电脑局域网地址或 Cloudflare HTTPS 域名。")
        hint.setObjectName("SectionHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        account_box = QGroupBox("橘味儿账号")
        form = QGridLayout(account_box)
        self.server_edit = QLineEdit("http://192.168.1.100:8000")
        self.server_edit.setPlaceholderText("例如 http://电脑IP:8000 或 https://api.example.com")
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("账号（至少 3 位）")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("密码（至少 6 位）")
        self.nickname_edit = QLineEdit()
        self.nickname_edit.setPlaceholderText("昵称（注册时可选）")
        login_btn = QPushButton("登录")
        register_btn = QPushButton("注册")
        apply_button_accent(login_btn, "primary")
        login_btn.clicked.connect(lambda: self.authenticate(False))
        register_btn.clicked.connect(lambda: self.authenticate(True))
        self.logout_btn = QPushButton("退出登录")
        self.logout_btn.clicked.connect(self.logout)
        self.account_status = QLabel("未登录")
        self.account_status.setObjectName("SectionHint")
        form.addWidget(QLabel("AI 服务器"), 0, 0)
        form.addWidget(self.server_edit, 0, 1, 1, 4)
        form.addWidget(QLabel("账号"), 1, 0)
        form.addWidget(self.user_edit, 1, 1)
        form.addWidget(QLabel("密码"), 1, 2)
        form.addWidget(self.password_edit, 1, 3)
        form.addWidget(QLabel("昵称"), 2, 0)
        form.addWidget(self.nickname_edit, 2, 1)
        form.addWidget(login_btn, 2, 2)
        form.addWidget(register_btn, 2, 3)
        form.addWidget(self.logout_btn, 2, 4)
        form.addWidget(self.account_status, 3, 0, 1, 5)
        root.addWidget(account_box)

        chat_box = QGroupBox("v3.0 内测群聊")
        chat_layout = QVBoxLayout(chat_box)
        self.messages = QTextBrowser()
        self.messages.setPlaceholderText("登录后可与三端内测用户交流。")
        chat_layout.addWidget(self.messages, 1)
        send_row = QHBoxLayout()
        self.message_edit = QLineEdit()
        self.message_edit.setPlaceholderText("输入消息，最多 500 字")
        self.message_edit.returnPressed.connect(self.send_message)
        refresh_btn = QPushButton("刷新")
        send_btn = QPushButton("发送")
        apply_button_accent(send_btn, "primary")
        refresh_btn.clicked.connect(self.refresh_messages)
        send_btn.clicked.connect(self.send_message)
        send_row.addWidget(self.message_edit, 1)
        send_row.addWidget(refresh_btn)
        send_row.addWidget(send_btn)
        chat_layout.addLayout(send_row)
        root.addWidget(chat_box, 1)
        self._load_config()

    def _base_url(self):
        return self.server_edit.text().strip().rstrip("/")

    def _request(self, method, path, payload=None):
        base = self._base_url()
        if not base.startswith(("http://", "https://")):
            raise RuntimeError("服务器地址必须以 http:// 或 https:// 开头")
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", str(exc))
            except Exception:
                detail = str(exc)
            raise RuntimeError(detail) from exc
        except Exception as exc:
            raise RuntimeError(f"无法连接服务器：{exc}") from exc

    def _load_config(self):
        try:
            data = json.loads(self.CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        self.server_edit.setText(str(data.get("server", self.server_edit.text())))
        self.token = str(data.get("token", ""))
        self.username = str(data.get("username", ""))
        self.nickname = str(data.get("nickname", ""))
        self.user_edit.setText(self.username)
        self._update_status()
        if self.token:
            QTimer.singleShot(700, self.refresh_messages)

    def _save_config(self):
        self.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.CONFIG_FILE, {
            "server": self._base_url(), "token": self.token,
            "username": self.username, "nickname": self.nickname,
        })

    def _update_status(self):
        text = f"已登录：{self.nickname or self.username}（{self.username}）" if self.token else "未登录"
        self.account_status.setText(text)
        self.logout_btn.setEnabled(bool(self.token))

    def authenticate(self, register):
        payload = {
            "username": self.user_edit.text().strip(),
            "password": self.password_edit.text(),
            "nickname": self.nickname_edit.text().strip(),
        }
        try:
            data = self._request("POST", "/api/v1/auth/register" if register else "/api/v1/auth/login", payload)
            self.token = str(data.get("token", ""))
            self.username = str(data.get("username", payload["username"]))
            self.nickname = str(data.get("nickname", self.username))
            self.password_edit.clear()
            self._save_config()
            self._update_status()
            self.refresh_messages()
        except Exception as exc:
            QMessageBox.warning(self, "账号操作失败", str(exc))

    def logout(self):
        self.token = ""
        self._save_config()
        self._update_status()
        self.messages.clear()

    def refresh_messages(self):
        if not self.token:
            return
        try:
            data = self._request("GET", "/api/v1/community/messages?limit=100")
            rows = []
            for item in data.get("messages", []):
                stamp = time.strftime("%m-%d %H:%M", time.localtime(float(item.get("created_at", 0))))
                name = html.escape(str(item.get("nickname") or item.get("username") or "用户"))
                content = html.escape(str(item.get("content", ""))).replace("\n", "<br>")
                rows.append(f"<p><b style='color:#FF8A2A'>{name}</b> <span style='color:#A995A6'>{stamp}</span><br>{content}</p>")
            self.messages.setHtml("".join(rows) or "<p>群里还没有消息，来发第一条吧。</p>")
            bar = self.messages.verticalScrollBar()
            bar.setValue(bar.maximum())
        except Exception as exc:
            self.account_status.setText(f"群聊刷新失败：{exc}")

    def send_message(self):
        content = self.message_edit.text().strip()
        if not self.token:
            QMessageBox.information(self, "提示", "请先登录账号。")
            return
        if not content:
            return
        try:
            self._request("POST", "/api/v1/community/messages", {"content": content[:500]})
            self.message_edit.clear()
            self.refresh_messages()
        except Exception as exc:
            QMessageBox.warning(self, "发送失败", str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  ·  v{VERSION}")
        self.setWindowIcon(QIcon(asset_path("novria_app_icon.ico")))
        self.resize(1440, 900)
        self.setMinimumSize(1180, 760)
        self.song_file = None
        self.stem_dir = None
        self.markers = []
        self.analysis_result = {}
        self.chord_timeline = []
        self.section_timeline = []
        self.arrangement_result = {}
        self.manual_section_overrides = {}
        self.arrangement_variants = {"A": {}, "B": {}}
        self.variant_audio = {"A": "", "B": ""}
        self.active_variant = ""
        self.arrangement_history = []
        self.undo_stack = []
        self.redo_stack = []
        self.variant_preview_player = None
        self.ab_stream = None
        self.ab_files = {}
        self.ab_current_variant = "A"
        self.ab_gain = {"A":1.0,"B":1.0}
        self.ab_frame = 0
        self.soundfont_path = ""
        self.melody_reference = []
        self.worker = None
        self.engine = MultiStemEngine()
        self.metronome_engine = MetronomeEngine()
        self.midi_worker = None
        self._auto_next_fired = False
        self.is_playing_ui = False
        self._timeline_dragging = False

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        sidebar = QWidget()
        sidebar.setFixedWidth(228)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0,0,0,0)
        side.setSpacing(10)

        brand = QGroupBox()
        brand_l = QVBoxLayout(brand)
        brand_l.setContentsMargins(14,14,14,14)
        brand_top = QHBoxLayout()
        brand_icon = QLabel()
        pix = QPixmap(asset_path("novria_app_icon_256.png"))
        brand_icon.setPixmap(pix.scaled(48,48,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        brand_text = QVBoxLayout()
        bt = QLabel(APP_NAME)
        bt.setObjectName("BrandTitle")
        bs = QLabel("AI 音乐工作站")
        bs.setObjectName("BrandSub")
        brand_text.addWidget(bt)
        brand_text.addWidget(bs)
        brand_top.addWidget(brand_icon)
        brand_top.addLayout(brand_text)
        brand_l.addLayout(brand_top)
        ver = QLabel(f"Performance · v{VERSION}")
        ver.setObjectName("BrandSub")
        brand_l.addWidget(ver)
        side.addWidget(brand)

        self.nav = QListWidget()
        self.nav.setObjectName("NavList")
        self.nav.setIconSize(QSize(30,30))
        nav_items = [
            ("统一音乐导入","import"),
            ("音乐库","projects"),
            ("AI 七轨分离","split"),
            ("AI 改编 / 乐谱","arrange"),
            ("演出谱面","arrange"),
            ("乐手演奏中心","live"),
            ("现场演出","live"),
            ("Setlist 歌单","setlist"),
            ("AI 歌声","voice"),
            ("作品中心","projects"),
            ("账号 / 内测群聊","projects"),
            ("设置","settings"),
        ]
        for text, ico in nav_items:
            QListWidgetItem(QIcon(icon_path(ico)), text, self.nav)
        self.nav.setCurrentRow(2)
        side.addWidget(self.nav, 1)

        footer = QLabel("让音乐创作与演出更自由")
        footer.setAlignment(Qt.AlignCenter)
        footer.setObjectName("BrandSub")
        side.addWidget(footer)

        self.stack = QStackedWidget()
        self.universal_import = UniversalImportPage(self)
        self.music_library = MusicLibraryPage(self)
        self.studio = StudioPage(self)
        self.arrangement = ArrangementScorePage(self)
        self.score_performance = ScorePerformancePage(self)
        self.instrument_experience = InstrumentExperiencePage(self)
        self.live = LivePage(self)
        self.live_pro = LiveProPage(self)
        self.setlist = SetlistPage(self)
        self.voice_lab = VoiceLabPage(self)
        self.stack.addWidget(self.universal_import)
        self.stack.addWidget(self.music_library)
        self.stack.addWidget(self.studio)
        self.stack.addWidget(self.arrangement)
        self.stack.addWidget(self.score_performance)
        self.stack.addWidget(self.instrument_experience)
        self.stack.addWidget(self.live_pro)
        self.stack.addWidget(self.setlist)
        self.stack.addWidget(self.voice_lab)
        self.stack.addWidget(Placeholder("作品中心：工程管理继续完善中"))
        self.community = CommunityPage(self)
        self.stack.addWidget(self.community)
        self.settings_page = SettingsPage(self)
        self.stack.addWidget(self.settings_page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)

        root.addWidget(sidebar)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage(f"就绪   ·   {APP_NAME} v{VERSION}")
        QTimer.singleShot(300, self.restore_live_session)
        QTimer.singleShot(500, self.refresh_smart_arranger_summary)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_timeline)
        self.timer.start(200)

        self.session_timer = QTimer(self)
        self.session_timer.timeout.connect(self.save_live_session)
        self.session_timer.start(5000)

        try:
            self.setStyleSheet(Path(asset_path("theme.qss")).read_text(encoding="utf-8"))
        except Exception:
            pass


    def load_imported_working_file(self, path):
        p=Path(path)
        if not p.exists():
            return
        self.song_file=str(p)
        self.stem_dir=None
        self.engine.close()
        self.studio.file_label.setText(p.name)
        if hasattr(self,"arrangement"):
            self.arrangement.song_label.setText(p.name)
            self.arrangement.analysis_status.setText("已从统一导入中心载入，等待分析")
        self.load_live_preset_file()
        self.nav.setCurrentRow(2)

    def import_song(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "导入歌曲", "", "音频 (*.mp3 *.wav *.flac *.m4a *.aac)"
        )
        if not p:
            return
        self.song_file = p
        self.stem_dir = None
        self.stop_variant_preview()
        self.stop_ab_instant_preview()
        self.metronome_engine.stop()
        if self.midi_worker:
            self.midi_worker.stop()
            self.midi_worker.wait(700)
        self.engine.close()
        self.studio.file_label.setText(Path(p).name)
        if hasattr(self, "arrangement"):
            self.arrangement.song_label.setText(Path(p).name)
            self.arrangement.analysis_status.setText("已导入歌曲，等待和弦/乐谱分析")
        self.load_live_preset_file()
        self.studio.log.setText("歌曲已导入。点击“AI 七轨兼容分离”。")
        self.studio.model_progress.setValue(0)
        self.studio.split_progress.setValue(0)
        self.studio.model_status.setText("等待检测 AI 模型")
        self.studio.split_status.setText("等待开始")

    def start_separation(self):
        if not self.song_file:
            QMessageBox.warning(self, "提示", "请先导入歌曲。")
            return
        if self.worker and self.worker.isRunning():
            return
        self.stop()
        self.studio.btn_split.setEnabled(False)
        self.studio.model_progress.setRange(0, 100)
        self.studio.split_progress.setRange(0, 100)
        self.studio.model_progress.setValue(0)
        self.studio.split_progress.setValue(0)
        self.studio.log.setText("正在准备 AI 模型与七轨兼容分离...")
        self.worker = SeparationWorker(self.song_file)
        self.worker.log.connect(self.on_split_log)
        self.worker.model_progress.connect(self.on_model_progress)
        self.worker.separation_progress.connect(self.on_separation_progress)
        self.worker.done.connect(self.on_split_done)
        self.worker.failed.connect(self.on_split_failed)
        self.worker.start()

    def on_model_progress(self, value, text):
        self.studio.model_progress.setValue(max(0, min(100, int(value))))
        self.studio.model_status.setText(text)

    def on_separation_progress(self, value, text):
        self.studio.split_progress.setValue(max(0, min(100, int(value))))
        self.studio.split_status.setText(text)

    def on_split_log(self, text):
        self.studio.log.setText(text[-500:])

    def on_split_done(self, stem_dir):
        self.studio.model_progress.setValue(100)
        self.studio.split_progress.setValue(100)
        self.studio.split_status.setText("基础六轨完成 · 电吉他轨按识别结果载入")
        self.studio.btn_split.setEnabled(True)
        self.stem_dir = Path(stem_dir)
        try:
            self.engine.load(self.stem_dir)
            self.load_waveform_if_ready()
            self.sync_mix_controls()
            electric = self.stem_dir / "electric_guitar.wav"
            self.studio.log.setText(
                f"分轨完成：{self.stem_dir}\n"
                + ("已载入独立电吉他轨。" if electric.exists() else "电吉他轨等待二次识别，未伪造空音频。")
            )
            QMessageBox.information(self, "完成", "AI 分轨完成，可以进行多轨 Mute/Solo 和现场播放。")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))

    def on_split_failed(self, text):
        self.studio.model_progress.setValue(0)
        self.studio.split_progress.setValue(0)
        self.studio.model_status.setText("等待检测 AI 模型")
        self.studio.split_status.setText("等待开始")
        self.studio.btn_split.setEnabled(True)
        self.studio.log.setText("分轨失败。")
        QMessageBox.critical(
            self, "AI 分轨失败",
            text + "\n\n如果是模型下载失败，请检查网络后重试；已经下载成功的模型会自动缓存，不会重复下载。"
        )

    def sync_mix_controls(self):
        for key, row in self.studio.rows.items():
            self.engine.mute[key] = row.mute.isChecked()
            self.engine.solo[key] = row.solo.isChecked()
            self.engine.volume[key] = row.volume.value() / 100.0

    def play_pause(self):
        if not self.engine.files:
            QMessageBox.warning(self, "提示", "请先完成 AI 六轨分离。")
            return
        try:
            if self.is_playing_ui and not self.engine.paused:
                self.engine.pause()
                self.is_playing_ui = False
                self.studio.play_btn.setText("播放")
            else:
                self._auto_next_fired = False
                self.engine.resume()
                self.is_playing_ui = True
                self.studio.play_btn.setText("暂停")
        except Exception as e:
            QMessageBox.critical(self, "播放失败", str(e))

    def stop(self):
        self.engine.stop()
        self.is_playing_ui = False
        if hasattr(self, "studio"):
            self.studio.play_btn.setText("播放")
            self.studio.timeline.setValue(0)

    def update_timeline(self):
        dur = self.engine.duration_seconds()
        pos = self.engine.position_seconds()
        if dur > 0 and not self._timeline_dragging:
            self.studio.timeline.blockSignals(True)
            self.studio.timeline.setValue(int(min(1, pos/dur)*1000))
            self.studio.timeline.blockSignals(False)
        def fmt(s):
            s = max(0, int(s))
            return f"{s//60:02d}:{s%60:02d}"
        self.studio.time_label.setText(f"{fmt(pos)} / {fmt(dur)}")
        if self.is_playing_ui and not self.engine.playing and not self.engine.paused:
            if (hasattr(self, "setlist") and self.setlist.auto_next.isChecked()
                    and not self._auto_next_fired and dur > 0 and pos >= max(0, dur - 0.35)):
                self._auto_next_fired = True
                QTimer.singleShot(250, lambda: self.advance_setlist(1, autoplay=True))
            else:
                self._auto_next_fired = False
            self.is_playing_ui = False
            self.studio.play_btn.setText("播放")

    def begin_timeline_seek(self):
        self._timeline_dragging = True

    def preview_timeline_seek(self, value):
        self._timeline_dragging = True
        dur = self.engine.duration_seconds()
        if dur <= 0:
            return
        target = dur * max(0, min(1000, int(value))) / 1000.0
        def fmt(seconds):
            seconds = max(0, int(seconds))
            return f"{seconds//60:02d}:{seconds%60:02d}"
        self.studio.time_label.setText(f"{fmt(target)} / {fmt(dur)}")

    def seek_from_slider(self):
        if not self.engine.files:
            self._timeline_dragging = False
            return
        ratio = self.studio.timeline.value()/1000.0
        self.engine.seek_ratio(ratio)
        self.studio.waveform.set_position(ratio)
        self._timeline_dragging = False

    def apply_live_preset(self, muted_key):
        for key, row in self.studio.rows.items():
            row.solo.setChecked(False)
            row.mute.setChecked(key == muted_key if muted_key else False)
        self.sync_mix_controls()
        names = {
            "guitar":"吉他弹唱（吉他轨关闭）",
            "piano":"钢琴弹唱（钢琴轨关闭）",
            "drums":"鼓手演出（鼓轨关闭）",
            "bass":"贝斯演出（贝斯轨关闭）",
            "vocals":"纯伴奏/KTV（人声轨关闭）",
            None:"全部恢复"
        }
        self.live.status.setText("当前预设：" + names[muted_key])


    def start_midi_worker(self):
        if self.midi_worker and self.midi_worker.isRunning():
            return
        self.midi_worker = MidiWorker()
        self.midi_worker.action.connect(self.handle_midi_action)
        self.midi_worker.status.connect(
            lambda s: self.live_pro.midi_status.setText(s) if hasattr(self, "live_pro") else None
        )
        self.midi_worker.start()

    def handle_midi_action(self, action):
        if action == "play_pause":
            self.play_pause()
        elif action == "stop":
            self.stop()
        elif action == "next":
            self.advance_setlist(1, autoplay=True)
        elif action == "previous":
            self.advance_setlist(-1, autoplay=False)

    def advance_setlist(self, delta=1, autoplay=False):
        if not hasattr(self, "setlist") or not self.setlist.items:
            return
        r = self.setlist.current_index()
        if r < 0:
            target = 0
        else:
            target = r + delta
        if target < 0 or target >= len(self.setlist.items):
            return
        self.stop()
        self.setlist.select_index(target)
        item = self.setlist.items[target]
        self.song_file = item["path"]
        self.studio.file_label.setText(Path(self.song_file).name)

        # 优先复用已经存在的六轨目录。
        candidate = STEMS_DIR / "htdemucs_6s" / Path(self.song_file).stem
        if candidate.exists():
            try:
                self.stem_dir = candidate
                self.engine.load(candidate)
                self.load_waveform_if_ready()
                self.sync_mix_controls()
                if autoplay:
                    QTimer.singleShot(350, self.play_pause)
                return
            except Exception:
                pass

        self.nav.setCurrentRow(2)
        QMessageBox.information(
            self, "Setlist",
            f"已切换到：{Path(self.song_file).name}\n该歌曲尚无可用六轨缓存，请先执行 AI 六轨分离。"
        )

    def save_live_session(self):
        try:
            self.save_live_preset_file()
            data = {
                "version": VERSION,
                "song_file": self.song_file,
                "stem_dir": str(self.stem_dir) if self.stem_dir else None,
                "setlist": self.setlist.items if hasattr(self, "setlist") else [],
                "setlist_index": self.setlist.current_index() if hasattr(self, "setlist") else -1,
                "position_seconds": self.engine.position_seconds(),
                "transpose": self.live_pro.transpose.value() if hasattr(self, "live_pro") else 0,
                "speed": self.live_pro.speed.value() if hasattr(self, "live_pro") else 1.0,
            }
            path = BASE_DIR / "user_data" / "last_live_session.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def restore_live_session(self):
        path = BASE_DIR / "user_data" / "last_live_session.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if hasattr(self, "setlist"):
                self.setlist.items = data.get("setlist", [])
                self.setlist.refresh()
                idx = int(data.get("setlist_index", -1))
                if idx >= 0:
                    self.setlist.select_index(idx)
            if hasattr(self, "live_pro"):
                self.live_pro.transpose.setValue(int(data.get("transpose", 0)))
                self.live_pro.speed.setValue(float(data.get("speed", 1.0)))
        except Exception:
            pass


    def _format_time(self, seconds):
        seconds = max(0, float(seconds or 0))
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m:02d}:{s:02d}"

    def _transpose_note_name(self, name, semitones):
        names = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
        base = str(name or "C").replace("♭","b")
        aliases = {"Db":"C#","Eb":"D#","Gb":"F#","Ab":"G#","Bb":"A#"}
        base = aliases.get(base, base)
        if base not in names:
            return base
        return names[(names.index(base)+int(semitones))%12]

    def _transpose_chord(self, chord, semitones):
        if not chord or chord == "N":
            return chord
        m = re.match(r"^([A-G](?:#|b)?)(.*)$", chord)
        if not m:
            return chord
        return self._transpose_note_name(m.group(1), semitones) + m.group(2)

    def update_target_key_label(self):
        if not hasattr(self, "arrangement"):
            return
        key = self.analysis_result.get("key", "") if self.analysis_result else ""
        if not key:
            self.arrangement.target_key.setText("目标调：—")
            return
        semis = self.arrangement.transpose.value()
        self.arrangement.target_key.setText("目标调：" + self._transpose_note_name(key, semis))

    def analyze_full_score(self):
        if not self.song_file:
            QMessageBox.warning(self, "提示", "请先导入歌曲。")
            return
        try:
            import librosa
            self.arrangement.progress.setValue(5)
            self.arrangement.analysis_status.setText("正在读取音频并检测节拍...")
            QApplication.processEvents()
            y, sr = librosa.load(self.song_file, sr=22050, mono=True)
            tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            tempo_val = float(np.asarray(tempo).reshape(-1)[0])
            beat_times = librosa.frames_to_time(beat_frames, sr=sr)
            if len(beat_times) < 4:
                raise RuntimeError("未检测到足够节拍，无法生成乐谱。")
            self.arrangement.progress.setValue(25)
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            beat_chroma = librosa.util.sync(chroma, beat_frames, aggregate=np.median)

            names = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
            chord_types = {
                "":    ([0,4,7],       [1.0,0.84,0.74]),
                "m":   ([0,3,7],       [1.0,0.84,0.74]),
                "7":   ([0,4,7,10],    [1.0,0.82,0.72,0.60]),
                "maj7":([0,4,7,11],    [1.0,0.82,0.72,0.58]),
                "m7":  ([0,3,7,10],    [1.0,0.82,0.72,0.60]),
                "sus4":([0,5,7],       [1.0,0.80,0.72]),
                "dim": ([0,3,6],       [1.0,0.80,0.70]),
            }
            templates=[]
            for root in range(12):
                for suffix,(intervals,weights) in chord_types.items():
                    temp=np.zeros(12,dtype=float)
                    for interval,weight in zip(intervals,weights):
                        temp[(root+interval)%12]=weight
                    templates.append((names[root]+suffix,temp))
            chords=[]
            for i in range(beat_chroma.shape[1]):
                v=beat_chroma[:,i].astype(float)
                norm=np.linalg.norm(v)
                if norm < 1e-8:
                    chords.append("N")
                    continue
                v=v/norm
                best=("N",-1e9)
                for cname,temp in templates:
                    t=temp/(np.linalg.norm(temp)+1e-9)
                    score=float(np.dot(v,t))
                    if score>best[1]:
                        best=(cname,score)
                chords.append(best[0])

            for i in range(1,len(chords)-1):
                if chords[i-1] == chords[i+1] != chords[i]:
                    chords[i]=chords[i-1]

            self.arrangement.progress.setValue(55)
            mean_chroma=np.mean(chroma,axis=1)
            key=names[int(np.argmax(mean_chroma))]
            self.analysis_result={"bpm":round(tempo_val,1),"key":key,"time_signature":"4/4"}
            self.studio.bpm_label.setText(f"BPM：{tempo_val:.1f}")
            self.studio.key_label.setText(f"调性参考：{key}")

            rows=[]
            total_beats=min(len(chords), len(beat_times))
            bar_no=1
            for start in range(0,total_beats,4):
                seq=chords[start:start+4]
                compact=[]
                for c in seq:
                    if not compact or compact[-1]!=c:
                        compact.append(c)
                t=float(beat_times[start]) if start < len(beat_times) else 0.0
                rows.append({"bar":bar_no,"seconds":t,"chords":compact})
                bar_no += 1

            sections=[]
            if self.markers:
                for m in self.markers:
                    sections.append({"name":m.get("name","段落"),"seconds":float(m.get("seconds",0))})
                sections.sort(key=lambda x:x["seconds"])
            else:
                for i in range(0,len(rows),8):
                    sections.append({"name":f"段落 {i//8+1}","seconds":rows[i]["seconds"]})
            self.section_timeline=sections
            for row in rows:
                sec=""
                for s in sections:
                    if row["seconds"] >= s["seconds"]:
                        sec=s["name"]
                    else:
                        break
                row["section"]=sec or "段落 1"
            self.chord_timeline=rows

            self.arrangement.chord_table.setRowCount(len(rows))
            for r,row in enumerate(rows):
                values=[str(row["bar"]),self._format_time(row["seconds"]),"  ".join(row["chords"]),row["section"]]
                for c,val in enumerate(values):
                    self.arrangement.chord_table.setItem(r,c,QTableWidgetItem(val))
            self.arrangement.progress.setValue(100)
            self.arrangement.analysis_status.setText(
                f"分析完成：{tempo_val:.1f} BPM · {key} 调参考 · {len(rows)} 小节 · 已生成和弦时间线"
            )
            self.update_target_key_label()
            if hasattr(self,"instrument_experience"):
                self.instrument_experience.refresh_sections()
            self.refresh_manual_sections()
            self.refresh_compare_sections()
        except Exception as e:
            self.arrangement.progress.setValue(0)
            QMessageBox.critical(self,"乐谱分析失败",str(e))

    def generate_transposed_stems(self):
        if not self.stem_dir or not Path(self.stem_dir).exists():
            QMessageBox.warning(self,"提示","请先完成六轨分离。")
            return
        semis=int(self.arrangement.transpose.value())
        if semis == 0:
            QMessageBox.information(self,"提示","当前为原调，无需生成。")
            return
        try:
            import librosa
            self.stop()
            song=Path(self.song_file).stem if self.song_file else "song"
            out_dir=BASE_DIR/"arrangements"/f"{song}_transpose_{semis:+d}"
            out_dir.mkdir(parents=True,exist_ok=True)
            stems=[k for k,_,_ in STEM_ORDER]
            for idx,key in enumerate(stems):
                self.arrangement.progress.setValue(int(idx/len(stems)*90))
                QApplication.processEvents()
                src=Path(self.stem_dir)/f"{key}.wav"
                if not src.is_file():
                    continue
                data,sr=sf.read(str(src),dtype="float32",always_2d=True)
                shifted=[]
                for ch in range(data.shape[1]):
                    shifted.append(librosa.effects.pitch_shift(data[:,ch],sr=sr,n_steps=semis))
                out=np.stack(shifted,axis=1).astype(np.float32)
                sf.write(str(out_dir/f"{key}.wav"),out,sr,subtype="PCM_24")
            self.arrangement.progress.setValue(100)
            self.stem_dir=out_dir
            self.engine.load(out_dir)
            self.load_waveform_if_ready()
            self.sync_mix_controls()
            QMessageBox.information(self,"升降调完成",f"已生成 {semis:+d} 半音演出版并载入：\n{out_dir}")
        except Exception as e:
            QMessageBox.critical(self,"升降调失败",str(e))

    def _score_rows_transposed(self):
        semis=self.arrangement.transpose.value() if hasattr(self,"arrangement") else 0
        out=[]
        for row in self.chord_timeline:
            out.append({**row,"chords":[self._transpose_chord(c,semis) for c in row.get("chords",[])]})
        return out

    def _make_score_html(self, title, instrument="lead"):
        rows=self._score_rows_transposed()
        bpm=self.analysis_result.get("bpm","—")
        key=self.analysis_result.get("key","—")
        semis=self.arrangement.transpose.value() if hasattr(self,"arrangement") else 0
        target=self._transpose_note_name(key,semis) if key != "—" else key
        guides={
            "lead":"Lead Sheet：按小节显示和弦与段落。",
            "guitar":"吉他：建议根据和弦使用开放和弦/封闭和弦；4/4 可先以八分音符扫弦作为排练起点。",
            "bass":"贝斯：基础版本以每个和弦根音为主，强拍落根音，段落连接处可加入五度与经过音。",
            "drums":"鼓：基础 4/4 groove：Hi-Hat 八分音符，Snare 2/4 拍，Kick 1/3 拍；副歌可增强 Crash 与 Fill。",
            "piano":"键盘：右手三和弦/转位，左手根音或根音+五度；根据段落密度调整织体。",
        }
        trs=[]
        for r in rows:
            chords=" / ".join(html.escape(c) for c in r["chords"])
            trs.append(f"<tr><td>{r['bar']}</td><td>{self._format_time(r['seconds'])}</td><td>{html.escape(r['section'])}</td><td class='chord'>{chords}</td></tr>")
        return f'''<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font-family:'Microsoft YaHei UI',Arial;background:#0a1020;color:#eef3ff;padding:30px}}h1{{color:#b993ff}}.meta{{color:#9fb0cf;margin-bottom:20px}}.guide{{background:#111c33;border:1px solid #2c3b5e;padding:14px;border-radius:10px;margin:16px 0}}table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #253451;padding:10px;text-align:left}}th{{color:#8fa2c6}}.chord{{font-size:18px;font-weight:bold;color:#65e1ce}}small{{color:#8795b0}}</style></head><body>
<h1>{html.escape(title)}</h1><div class="meta">BPM {bpm} · 原调参考 {html.escape(str(key))} · 演出调 {html.escape(str(target))} · 升降 {semis:+d} 半音 · 4/4</div>
<div class="guide">{html.escape(guides.get(instrument,guides['lead']))}</div>
<table><tr><th>小节</th><th>时间</th><th>段落</th><th>和弦</th></tr>{''.join(trs)}</table>
<p><small>橘味儿音乐 · AI 分析生成的排练/演奏参考谱，建议乐手演出前人工校对。</small></p></body></html>'''

    def export_lead_sheet(self):
        self.export_instrument_score("lead")

    def export_instrument_score(self, instrument):
        if not self.chord_timeline:
            QMessageBox.warning(self,"提示","请先运行“分析和弦 / BPM / 调性”。")
            return
        names={"lead":"Lead Sheet","guitar":"吉他演奏参考谱","bass":"贝斯演奏参考谱","drums":"鼓手演奏参考谱","piano":"键盘演奏参考谱"}
        song=Path(self.song_file).stem if self.song_file else "song"
        default=EXPORTS_DIR/f"{song}_{instrument}_score.html"
        p,_=QFileDialog.getSaveFileName(self,"导出演奏谱",str(default),"HTML 乐谱 (*.html)")
        if not p:
            return
        Path(p).write_text(self._make_score_html(f"{song} · {names.get(instrument,instrument)}",instrument),encoding="utf-8")
        try:
            webbrowser.open(Path(p).resolve().as_uri())
        except Exception:
            pass
        QMessageBox.information(self,"出谱完成",f"已生成：\n{p}")


    def _difficulty_value(self, text):
        return {"简化":0.55, "标准":0.75, "丰富":0.9, "专业":1.0}.get(str(text),0.75)

    def _current_player_profiles(self):
        ie = getattr(self, "instrument_experience", None)
        if ie is None:
            return {}
        return {
            "guitar":{
                "difficulty":ie.guitar_difficulty.currentText(),
                "tuning":ie.guitar_tuning.currentText(),
                "capo":ie.guitar_capo.value(),
                "style":ie.guitar_style.currentText(),
                "density":ie.guitar_density.value(),
            },
            "bass":{
                "difficulty":ie.bass_difficulty.currentText(),
                "strings":ie.bass_strings.currentText(),
                "pattern":ie.bass_pattern.currentText(),
                "density":ie.bass_density.value(),
                "range":ie.bass_octave.currentText(),
            },
            "drums":{
                "difficulty":ie.drums_difficulty.currentText(),
                "groove":ie.drums_groove.currentText(),
                "hihat":ie.drums_hihat.currentText(),
                "fill":ie.drums_fill.currentText(),
                "strength":ie.drums_strength.value(),
            },
            "piano":{
                "difficulty":ie.piano_difficulty.currentText(),
                "left":ie.piano_left.currentText(),
                "right":ie.piano_right.currentText(),
                "sustain":ie.piano_sustain.currentText(),
                "density":ie.piano_density.value(),
            }
        }

    def refresh_smart_arranger_summary(self):
        if not hasattr(self, "arrangement"):
            return
        p=self._current_player_profiles()
        if not p:
            self.arrangement.smart_summary.setText("未找到乐手参数")
            return
        txt=(
            f"吉他：{p['guitar']['difficulty']} / {p['guitar']['style']} / 密度 {p['guitar']['density']} / Capo {p['guitar']['capo']}\\n"
            f"Bass：{p['bass']['difficulty']} / {p['bass']['pattern']} / 密度 {p['bass']['density']} / {p['bass']['range']}\\n"
            f"鼓：{p['drums']['difficulty']} / {p['drums']['groove']} / {p['drums']['hihat']} / {p['drums']['fill']}\\n"
            f"键盘：{p['piano']['difficulty']} / 左手 {p['piano']['left']} / 右手 {p['piano']['right']} / 密度 {p['piano']['density']}"
        )
        self.arrangement.smart_summary.setText(txt)

    def _smart_chord_notes(self, chord, semis):
        notes={"C":60,"C#":61,"D":62,"D#":63,"E":64,"F":65,"F#":66,"G":67,"G#":68,"A":69,"A#":70,"B":71}
        m=re.match(r"^([A-G](?:#|b)?)(.*)$", chord or "")
        if not m:
            return [60,64,67]
        root=self._transpose_note_name(m.group(1),semis)
        base=notes.get(root,60)
        suffix=m.group(2)
        if suffix.startswith("m") and not suffix.startswith("maj"):
            third=3
        else:
            third=4
        ns=[base,base+third,base+7]
        if suffix=="7":
            ns.append(base+10)
        elif suffix=="maj7":
            ns.append(base+11)
        elif suffix=="m7":
            ns=[base,base+3,base+7,base+10]
        elif suffix=="sus4":
            ns=[base,base+5,base+7]
        elif suffix=="dim":
            ns=[base,base+3,base+6]
        return ns

    def _guitar_bar_events(self, track, ns, profile, mode):
        from mido import Message
        difficulty=self._difficulty_value(profile.get("difficulty"))
        density=max(1,min(10,int(profile.get("density",5))))
        style=profile.get("style","自动推荐")
        capo=int(profile.get("capo",0))
        notes=[n+capo for n in ns]
        velocity=int(48+35*difficulty)

        if "Power Chord" in style:
            notes=[notes[0],notes[0]+7,notes[0]+12]
        elif "分解" in style or "Fingerstyle" in style:
            steps=8 if density>=6 else 4
            dur=240 if steps==8 else 480
            pattern=[0,1,2,1,0,2,1,2] if len(notes)>=3 else [0]*steps
            for i in range(steps):
                n=notes[pattern[i % len(pattern)] % len(notes)]
                track.append(Message('note_on',note=min(108,n),velocity=velocity,time=0,channel=0))
                track.append(Message('note_off',note=min(108,n),velocity=0,time=dur,channel=0))
            return
        else:
            beats=4 if density<=6 else 8
            dur=480 if beats==4 else 240
            for _ in range(beats):
                for n in notes:
                    track.append(Message('note_on',note=min(108,n),velocity=velocity,time=0,channel=0))
                track.append(Message('note_off',note=min(108,notes[0]),velocity=0,time=int(dur*0.78),channel=0))
                for n in notes[1:]:
                    track.append(Message('note_off',note=min(108,n),velocity=0,time=0,channel=0))
                track.append(Message('note_on',note=min(108,notes[0]),velocity=1,time=max(1,int(dur*0.22)),channel=0))
                track.append(Message('note_off',note=min(108,notes[0]),velocity=0,time=0,channel=0))

    def _bass_bar_events(self, track, ns, profile):
        from mido import Message
        root=ns[0]-24
        if "高把位" in profile.get("range",""):
            root+=12
        elif "低音更稳" in profile.get("range",""):
            root-=5
        density=max(1,min(10,int(profile.get("density",5))))
        pattern=profile.get("pattern","根音优先")
        diff=self._difficulty_value(profile.get("difficulty"))
        velocity=int(64+24*diff)

        notes=[]
        if "Walking" in pattern:
            notes=[root,root+4,root+7,root+9]
        elif "八度" in pattern:
            notes=[root,root+12,root+7,root+12]
        elif "五度" in pattern:
            notes=[root,root+7,root,root+7]
        elif "旋律化" in pattern:
            notes=[root,root+4,root+7,root+11]
        else:
            notes=[root,root,root,root]

        if density<=3:
            seq=[notes[0],notes[2]]
            dur=960
        elif density>=8:
            seq=[notes[0],notes[1],notes[2],notes[3],notes[0]+12,notes[2],notes[1],notes[3]]
            dur=240
        else:
            seq=notes
            dur=480

        for n in seq:
            n=max(28,min(72,n))
            track.append(Message('note_on',note=n,velocity=velocity,time=0,channel=1))
            track.append(Message('note_off',note=n,velocity=0,time=dur,channel=1))

    def _piano_bar_events(self, track, ns, profile):
        from mido import Message
        left=profile.get("left","根音")
        right=profile.get("right","三和弦")
        density=max(1,min(10,int(profile.get("density",5))))
        diff=self._difficulty_value(profile.get("difficulty"))
        velocity=int(48+24*diff)

        chord=[n+12 for n in ns]
        if "转位" in right and len(chord)>=3:
            chord=[chord[1],chord[2],chord[0]+12] + chord[3:]
        if "Pad" in right:
            for n in chord:
                track.append(Message('note_on',note=min(108,n),velocity=max(35,velocity-12),time=0,channel=2))
            track.append(Message('note_off',note=min(108,chord[0]),velocity=0,time=1920,channel=2))
            for n in chord[1:]:
                track.append(Message('note_off',note=min(108,n),velocity=0,time=0,channel=2))
            return

        steps=8 if density>=7 else 4
        dur=240 if steps==8 else 480
        for i in range(steps):
            if "分解" in right or "Rhodes" in right:
                n=chord[i % len(chord)]
                track.append(Message('note_on',note=min(108,n),velocity=velocity,time=0,channel=2))
                track.append(Message('note_off',note=min(108,n),velocity=0,time=dur,channel=2))
            else:
                for n in chord:
                    track.append(Message('note_on',note=min(108,n),velocity=velocity,time=0,channel=2))
                track.append(Message('note_off',note=min(108,chord[0]),velocity=0,time=int(dur*0.85),channel=2))
                for n in chord[1:]:
                    track.append(Message('note_off',note=min(108,n),velocity=0,time=0,channel=2))
                track.append(Message('note_on',note=min(108,chord[0]),velocity=1,time=max(1,int(dur*0.15)),channel=2))
                track.append(Message('note_off',note=min(108,chord[0]),velocity=0,time=0,channel=2))

    def _drum_bar_events(self, track, profile, is_section_boundary=False):
        from mido import Message
        groove=profile.get("groove","Pop 8Beat")
        hihat=profile.get("hihat","八分音符")
        fill=profile.get("fill","少量 Fill")
        strength=max(1,min(10,int(profile.get("strength",5))))
        difficulty=self._difficulty_value(profile.get("difficulty"))
        vel_base=int(50+35*difficulty+(strength-5)*2)

        sixteenth = "十六" in hihat
        steps=16 if sixteenth else 8
        dur=120 if sixteenth else 240
        hh_note=51 if "Ride" in hihat else 42

        for step in range(steps):
            beat_pos = step/(4 if sixteenth else 2)
            events=[(hh_note,max(35,vel_base-25))]
            if abs(beat_pos-0.0)<0.01 or abs(beat_pos-2.0)<0.01:
                events.append((36,min(120,vel_base+12)))
            if abs(beat_pos-1.0)<0.01 or abs(beat_pos-3.0)<0.01:
                events.append((38,min(120,vel_base+8)))
            if "Rock" in groove and beat_pos in (0.0,1.5,2.0):
                events.append((36,min(120,vel_base+8)))
            if "Funk" in groove and step % 4 == 3:
                events.append((36,min(115,vel_base)))
            for note,vel in events:
                track.append(Message('note_on',note=note,velocity=vel,time=0,channel=9))
            track.append(Message('note_off',note=hh_note,velocity=0,time=dur,channel=9))
            for note,_ in events[1:]:
                track.append(Message('note_off',note=note,velocity=0,time=0,channel=9))

        wants_fill = is_section_boundary and ("段落前" in fill or "副歌" in fill or "丰富" in fill)
        if wants_fill:
            # Append a short tom/snare fill by borrowing one final quarter-note feel.
            for note in [45,47,50,38]:
                track.append(Message('note_on',note=note,velocity=min(120,vel_base+10),time=0,channel=9))
                track.append(Message('note_off',note=note,velocity=0,time=120,channel=9))


    def _section_role(self, name, index, total):
        text=str(name or "").lower()
        if "intro" in text or "前奏" in text:
            return "intro"
        if "verse" in text or "主歌" in text:
            return "verse"
        if "chorus" in text or "副歌" in text:
            return "chorus"
        if "bridge" in text or "桥" in text:
            return "bridge"
        if "solo" in text or "间奏" in text:
            return "solo"
        if "outro" in text or "尾奏" in text:
            return "outro"
        if total <= 1:
            return "verse"
        ratio=index/max(1,total-1)
        if ratio < 0.12:
            return "intro"
        if ratio < 0.42:
            return "verse"
        if ratio < 0.66:
            return "chorus"
        if ratio < 0.84:
            return "bridge"
        return "outro"

    def _section_strategy(self, role, curve="自动判断"):
        base = {
            "intro":  {"energy":0.48,"guitar":0.55,"bass":0.45,"drums":0.35,"piano":0.65,"fill":0.15,"space":0.35},
            "verse":  {"energy":0.58,"guitar":0.62,"bass":0.58,"drums":0.55,"piano":0.58,"fill":0.20,"space":0.25},
            "chorus": {"energy":0.92,"guitar":0.88,"bass":0.88,"drums":0.95,"piano":0.82,"fill":0.72,"space":0.05},
            "bridge": {"energy":0.52,"guitar":0.40,"bass":0.50,"drums":0.46,"piano":0.72,"fill":0.35,"space":0.45},
            "solo":   {"energy":0.82,"guitar":0.72,"bass":0.78,"drums":0.84,"piano":0.55,"fill":0.65,"space":0.10},
            "outro":  {"energy":0.45,"guitar":0.50,"bass":0.48,"drums":0.38,"piano":0.58,"fill":0.28,"space":0.40},
        }[role].copy()

        if curve=="渐进增强":
            if role in ("intro","verse"):
                base["energy"]*=0.88
            elif role in ("chorus","solo"):
                base["energy"]=min(1.0,base["energy"]*1.06)
        elif curve=="平稳现场":
            for k in ("energy","guitar","bass","drums","piano"):
                base[k]=0.68 + (base[k]-0.68)*0.35
        elif curve=="强弱对比":
            if role in ("verse","bridge","intro"):
                base["energy"]*=0.78
            if role in ("chorus","solo"):
                base["energy"]=min(1.0,base["energy"]*1.08)
        elif curve=="抒情克制":
            base["drums"]*=0.72
            base["guitar"]*=0.82
            base["bass"]*=0.86
            base["piano"]=min(1.0,base["piano"]*1.05)
            base["fill"]*=0.45
            base["space"]=min(0.8,base["space"]+0.18)
        return base

    def _build_section_map(self):
        rows=self.chord_timeline or []
        if not rows:
            return []
        unique=[]
        seen=set()
        for row in rows:
            s=row.get("section","段落")
            if s not in seen:
                seen.add(s); unique.append(s)
        curve=self.arrangement.energy_curve.currentText() if hasattr(self,"arrangement") else "自动判断"
        out=[]
        for i,name in enumerate(unique):
            role=self._section_role(name,i,len(unique))
            out.append({
                "name":name,
                "role":role,
                "strategy":self._section_strategy(role,curve)
            })
        return out

    def refresh_musical_intelligence_preview(self):
        if not self.chord_timeline:
            self.arrangement.intelligence_summary.setText("请先完成歌曲和弦/段落分析。")
            return
        smap=self._build_section_map()
        labels={"intro":"前奏","verse":"主歌","chorus":"副歌","bridge":"桥段","solo":"间奏/独奏","outro":"尾奏"}
        lines=[]
        for s in smap:
            st=s["strategy"]
            lines.append(
                f"{s['name']} → {labels.get(s['role'],s['role'])} | "
                f"能量 {int(st['energy']*100)}% | "
                f"吉他 {int(st['guitar']*100)}% | Bass {int(st['bass']*100)}% | "
                f"鼓 {int(st['drums']*100)}% | 键盘 {int(st['piano']*100)}% | "
                f"Fill {int(st['fill']*100)}%"
            )
        self.arrangement.intelligence_summary.setText("\n".join(lines))

    def _section_strategy_for_name(self, section_name, section_map):
        for item in section_map:
            if item["name"] == section_name:
                return item["strategy"], item["role"]
        return self._section_strategy("verse"), "verse"

    def _apply_section_profile(self, profile, strategy, instrument):
        p=dict(profile or {})
        factor=float(strategy.get(instrument,0.7))
        density_key="density"
        if density_key in p:
            p[density_key]=max(1,min(10,int(round(float(p[density_key])*factor))))
        if instrument=="drums":
            p["strength"]=max(1,min(10,int(round(float(p.get("strength",5))*max(0.55,strategy.get("drums",0.7))))))
            if strategy.get("fill",0)<0.25:
                p["fill"]="少量 Fill"
            elif strategy.get("fill",0)>0.65:
                p["fill"]="段落前 Fill"
        return p

    def _musical_intelligence_bar(self, tracks, row, ns, profiles, strategy, role, boundary, mode):
        guitar,bass,piano,drums = tracks
        gp=self._apply_section_profile(profiles.get("guitar",{}),strategy,"guitar")
        bp=self._apply_section_profile(profiles.get("bass",{}),strategy,"bass")
        pp=self._apply_section_profile(profiles.get("piano",{}),strategy,"piano")
        dp=self._apply_section_profile(profiles.get("drums",{}),strategy,"drums")

        # Human-friendly orchestration decisions.
        if role=="intro":
            if "扫弦" in gp.get("style",""):
                gp["style"]="分解和弦"
            dp["strength"]=max(2,dp.get("strength",5)-2)
        elif role=="chorus":
            if gp.get("style","自动推荐")=="自动推荐":
                gp["style"]="扫弦"
            bp["density"]=max(bp.get("density",5),6)
            dp["strength"]=min(10,dp.get("strength",5)+2)
            if dp.get("fill")=="少量 Fill":
                dp["fill"]="段落前 Fill"
        elif role=="bridge":
            # Leave space: piano may hold longer notes; guitar reduced.
            gp["density"]=max(1,int(gp.get("density",5)*0.55))
            pp["right"]="Pad铺底"
            dp["strength"]=max(1,int(dp.get("strength",5)*0.7))
        elif role=="outro":
            gp["density"]=max(1,int(gp.get("density",5)*0.65))
            bp["density"]=max(1,int(bp.get("density",5)*0.65))
            dp["strength"]=max(1,int(dp.get("strength",5)*0.6))
            pp["right"]="Pad铺底"

        # Frequency/rhythm separation heuristic:
        # if piano is dense, guitar becomes rhythmically simpler; if guitar dense, piano sustains.
        if int(pp.get("density",5)) >= 7 and int(gp.get("density",5)) >= 7:
            if role in ("chorus","solo"):
                pp["right"]="Pad铺底"
            else:
                gp["density"]=5

        self._guitar_bar_events(guitar,ns,gp,mode)
        self._bass_bar_events(bass,ns,bp)
        self._piano_bar_events(piano,ns,pp)
        self._drum_bar_events(drums,dp,boundary)




    def _integrated_rms_db(self, path):
        data,sr=sf.read(path,dtype="float32",always_2d=True)
        if len(data)==0:
            return -120.0
        mono=np.mean(data,axis=1)
        # Ignore near-silence for more useful program-level matching.
        mask=np.abs(mono)>1e-5
        if np.any(mask):
            mono=mono[mask]
        rms=float(np.sqrt(np.mean(np.square(mono))+1e-12))
        return 20.0*math.log10(max(rms,1e-12))

    def prepare_ab_loudness_match(self):
        pa=self.variant_audio.get("A","")
        pb=self.variant_audio.get("B","")
        if not pa or not pb or not Path(pa).exists() or not Path(pb).exists():
            return False
        try:
            da=self._integrated_rms_db(pa)
            db=self._integrated_rms_db(pb)
            target=min(da,db)
            self.ab_gain["A"]=10**((target-da)/20.0)
            self.ab_gain["B"]=10**((target-db)/20.0)
            if hasattr(self,"arrangement"):
                self.arrangement.diff_label.setText(
                    f"响度匹配：A {da:.1f} dB RMS / B {db:.1f} dB RMS → 共同目标 {target:.1f} dB RMS"
                )
            return True
        except Exception:
            self.ab_gain={"A":1.0,"B":1.0}
            return False

    def refresh_ab_waveforms(self):
        if not hasattr(self,"arrangement"):
            return
        pa=self.variant_audio.get("A","")
        pb=self.variant_audio.get("B","")
        if pa and Path(pa).exists():
            self.arrangement.ab_wave_a.set_waveform_from_wav(pa)
        if pb and Path(pb).exists():
            self.arrangement.ab_wave_b.set_waveform_from_wav(pb)

    def _open_ab_files(self):
        self._close_ab_files()
        for v in ("A","B"):
            p=self.variant_audio.get(v,"")
            if p and Path(p).exists():
                self.ab_files[v]=sf.SoundFile(p,"r")
        if set(self.ab_files.keys()) != {"A","B"}:
            self._close_ab_files()
            return False
        a=self.ab_files["A"]; b=self.ab_files["B"]
        if a.samplerate!=b.samplerate or a.channels!=b.channels:
            self._close_ab_files()
            QMessageBox.critical(self,"A/B 不兼容","A/B 渲染文件的采样率或声道数不同。")
            return False
        return True

    def _close_ab_files(self):
        for f in getattr(self,"ab_files",{}).values():
            try: f.close()
            except Exception: pass
        self.ab_files={}

    def start_ab_instant_preview(self):
        if not self._open_ab_files():
            QMessageBox.warning(self,"提示","请先把 A 和 B 都渲染成 WAV。")
            return False

        if hasattr(self,"arrangement") and self.arrangement.loudness_match.isChecked():
            self.prepare_ab_loudness_match()
        else:
            self.ab_gain={"A":1.0,"B":1.0}

        start,end=self._selected_compare_segment()
        sr=self.ab_files["A"].samplerate
        ch=self.ab_files["A"].channels
        loop=bool(hasattr(self,"arrangement") and self.arrangement.loop_compare.isChecked())
        start_frame=max(0,int(start*sr))
        end_frame=int(end*sr) if end else min(self.ab_files["A"].frames,self.ab_files["B"].frames)
        self.ab_frame=start_frame
        for f in self.ab_files.values():
            f.seek(start_frame)

        def cb(outdata,frames,time_info,status):
            v=self.ab_current_variant
            f=self.ab_files[v]
            # Keep both files aligned even when only one is audible.
            pos=self.ab_frame
            for key,fh in self.ab_files.items():
                fh.seek(pos)
            data=self.ab_files[v].read(frames,dtype="float32",always_2d=True)
            n=len(data)

            if n<frames or pos+n>=end_frame:
                valid=max(0,min(n,end_frame-pos))
                first=data[:valid]
                if loop:
                    remain=frames-valid
                    for fh in self.ab_files.values():
                        fh.seek(start_frame)
                    second=self.ab_files[v].read(remain,dtype="float32",always_2d=True)
                    data=np.vstack([first,second]) if len(first) else second
                    self.ab_frame=start_frame+len(second)
                else:
                    outdata.fill(0)
                    if valid:
                        outdata[:valid]=first*self.ab_gain.get(v,1.0)
                    raise sd.CallbackStop()
            else:
                self.ab_frame=pos+frames

            if len(data)<frames:
                padded=np.zeros((frames,ch),dtype=np.float32)
                padded[:len(data)]=data
                data=padded
            outdata[:]=data[:frames]*self.ab_gain.get(v,1.0)

        self.stop_ab_instant_preview()
        self.ab_stream=sd.OutputStream(
            samplerate=sr,channels=ch,dtype="float32",blocksize=512,callback=cb
        )
        self.ab_stream.start()
        return True

    def stop_ab_instant_preview(self):
        if self.ab_stream:
            try:
                self.ab_stream.stop()
                self.ab_stream.close()
            except Exception:
                pass
            self.ab_stream=None
        self._close_ab_files()

    def instant_switch_variant(self, variant):
        if variant not in ("A","B"):
            return
        self.ab_current_variant=variant
        self.active_variant=variant
        if not self.ab_stream:
            if not self.start_ab_instant_preview():
                return
        if hasattr(self,"arrangement"):
            self.arrangement.diff_label.setText(
                f"正在瞬时 A/B 对比：当前 {variant} · "
                f"{'已启用响度匹配' if self.arrangement.loudness_match.isChecked() else '未启用响度匹配'}"
            )

    def analyze_ab_difference(self):
        pa=self.variant_audio.get("A","")
        pb=self.variant_audio.get("B","")
        if not pa or not pb or not Path(pa).exists() or not Path(pb).exists():
            QMessageBox.warning(self,"提示","请先渲染 A/B WAV。")
            return
        try:
            a,sra=sf.read(pa,dtype="float32",always_2d=True)
            b,srb=sf.read(pb,dtype="float32",always_2d=True)
            if sra!=srb:
                raise RuntimeError("A/B 采样率不同")
            n=min(len(a),len(b))
            if n<=0:
                raise RuntimeError("A/B 音频为空")
            a=a[:n]; b=b[:n]
            if a.shape[1]!=b.shape[1]:
                m=min(a.shape[1],b.shape[1])
                a=a[:,:m]; b=b[:,:m]

            # Compare after level matching to emphasize arrangement/timbre differences.
            da=self._integrated_rms_db(pa)
            db=self._integrated_rms_db(pb)
            target=min(da,db)
            ga=10**((target-da)/20.0)
            gb=10**((target-db)/20.0)
            aa=a*ga; bb=b*gb
            diff=aa-bb

            rms_a=float(np.sqrt(np.mean(aa**2)+1e-12))
            rms_b=float(np.sqrt(np.mean(bb**2)+1e-12))
            rms_diff=float(np.sqrt(np.mean(diff**2)+1e-12))
            corr=float(np.corrcoef(aa.reshape(-1),bb.reshape(-1))[0,1]) if n>100 else 0.0
            corr=max(-1.0,min(1.0,corr if not np.isnan(corr) else 0.0))
            relative=100.0*rms_diff/max(1e-9,(rms_a+rms_b)/2.0)

            self.arrangement.diff_label.setText(
                f"A/B 差异分析：响度匹配后差异强度约 {relative:.1f}% · "
                f"波形相关度 {corr:.3f} · "
                f"A {da:.1f} dB RMS / B {db:.1f} dB RMS。"
            )
        except Exception as e:
            QMessageBox.critical(self,"A/B 差异分析失败",str(e))

    def restore_selected_history(self):
        if not hasattr(self,"arrangement"):
            return
        row=self.arrangement.history_table.currentRow()
        if row<0:
            QMessageBox.information(self,"历史恢复","请先选择一条历史记录。")
            return
        # Table is newest-first.
        index=len(self.arrangement_history)-1-row
        if index<0 or index>=len(self.arrangement_history):
            return
        self._push_undo_state("恢复历史前")
        state=self.arrangement_history[index]
        self.manual_section_overrides=json.loads(json.dumps(state.get("manual_overrides",{}),ensure_ascii=False))
        self.arrangement_variants=json.loads(json.dumps(state.get("variants",{"A":{},"B":{}}),ensure_ascii=False))
        self.active_variant=state.get("active_variant","")
        self.load_manual_section_settings()
        QMessageBox.information(self,"历史恢复",f"已恢复：{state.get('label','历史快照')}")


    def _snapshot_state(self, label=""):
        return {
            "time":time.time(),
            "label":label,
            "manual_overrides":json.loads(json.dumps(self.manual_section_overrides,ensure_ascii=False)),
            "variants":json.loads(json.dumps(self.arrangement_variants,ensure_ascii=False)),
            "active_variant":self.active_variant,
        }

    def _push_undo_state(self, label="修改"):
        self.undo_stack.append(self._snapshot_state(label))
        if len(self.undo_stack) > 50:
            self.undo_stack=self.undo_stack[-50:]
        self.redo_stack.clear()

    def undo_arrangement_change(self):
        if not self.undo_stack:
            QMessageBox.information(self,"Undo","没有可撤销的操作。")
            return
        self.redo_stack.append(self._snapshot_state("redo"))
        state=self.undo_stack.pop()
        self.manual_section_overrides=state.get("manual_overrides",{})
        self.arrangement_variants=state.get("variants",{"A":{},"B":{}})
        self.active_variant=state.get("active_variant","")
        self.load_manual_section_settings()
        self.refresh_history_table()

    def redo_arrangement_change(self):
        if not self.redo_stack:
            QMessageBox.information(self,"Redo","没有可重做的操作。")
            return
        self.undo_stack.append(self._snapshot_state("undo"))
        state=self.redo_stack.pop()
        self.manual_section_overrides=state.get("manual_overrides",{})
        self.arrangement_variants=state.get("variants",{"A":{},"B":{}})
        self.active_variant=state.get("active_variant","")
        self.load_manual_section_settings()
        self.refresh_history_table()

    def save_arrangement_snapshot(self):
        state=self._snapshot_state("手动快照")
        self.arrangement_history.append(state)
        folder=BASE_DIR/"arrangement_history"
        folder.mkdir(parents=True,exist_ok=True)
        song=Path(self.song_file).stem if self.song_file else "project"
        p=folder/f"{song}_{int(state['time'])}.json"
        p.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
        state["file"]=str(p)
        self.refresh_history_table()
        QMessageBox.information(self,"历史快照",f"已保存：\n{p}")

    def refresh_history_table(self):
        if not hasattr(self,"arrangement"):
            return
        table=self.arrangement.history_table
        table.setRowCount(len(self.arrangement_history))
        for r,item in enumerate(reversed(self.arrangement_history)):
            ts=time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(item.get("time",0)))
            vals=[
                ts,
                item.get("active_variant","") or "-",
                item.get("label",""),
                item.get("file","")
            ]
            for c,v in enumerate(vals):
                table.setItem(r,c,QTableWidgetItem(str(v)))

    def _variant_midi_path(self, variant):
        p=str(self.arrangement_variants.get(variant,{}).get("midi",""))
        if p and Path(p).exists():
            return p
        return ""

    def _variant_render_output(self, variant, ext="wav"):
        song=Path(self.song_file).stem if self.song_file else "song"
        folder=EXPORTS_DIR/"ab_compare"
        folder.mkdir(parents=True,exist_ok=True)
        return str(folder/f"{song}_variant_{variant}.{ext}")

    def render_variant_audio(self, variant):
        midi=self._variant_midi_path(variant)
        if not midi:
            self.generate_variant_midi(variant)
            midi=self._variant_midi_path(variant)
        if not midi:
            return

        sf=self.arrangement.soundfont_edit.text().strip() if hasattr(self,"arrangement") else self.soundfont_path
        if not sf or not Path(sf).exists():
            QMessageBox.warning(self,"提示","请先在“新编配音源渲染”区域选择 SoundFont。")
            return
        fluidsynth=self._find_fluidsynth()
        if not fluidsynth:
            QMessageBox.critical(self,"缺少 FluidSynth","未找到 fluidsynth.exe。")
            return

        out=self._variant_render_output(variant,"wav")
        try:
            self.arrangement.progress.setValue(10)
            QApplication.processEvents()
            p=subprocess.run(
                [fluidsynth,"-ni",sf,midi,"-F",out,"-r","44100"],
                capture_output=True,text=True,timeout=600
            )
            if p.returncode != 0 or not Path(out).exists():
                raise RuntimeError((p.stderr or p.stdout or "FluidSynth 渲染失败")[-2000:])
            self.variant_audio[variant]=out
            self.arrangement_variants.setdefault(variant,{})["render_wav"]=out
            self.refresh_ab_waveforms()
            if self.variant_audio.get("A") and self.variant_audio.get("B"):
                self.prepare_ab_loudness_match()
            self.arrangement.progress.setValue(100)
            QMessageBox.information(self,"渲染完成",f"{variant} 版已渲染：\n{out}")
        except Exception as e:
            self.arrangement.progress.setValue(0)
            QMessageBox.critical(self,"渲染失败",str(e))

    def _selected_compare_segment(self):
        if not hasattr(self,"arrangement"):
            return (0.0,None)
        text=self.arrangement.compare_section.currentText()
        sections=self.section_timeline or []
        if not text or not sections:
            return (0.0,None)
        idx=self.arrangement.compare_section.currentData()
        if idx is None:
            return (0.0,None)
        idx=int(idx)
        start=float(sections[idx].get("seconds",0))
        end=float(sections[idx+1].get("seconds",0)) if idx+1<len(sections) else None
        return (start,end)

    def preview_variant(self, variant):
        path=self.variant_audio.get(variant,"")
        if not path or not Path(path).exists():
            self.render_variant_audio(variant)
            path=self.variant_audio.get(variant,"")
        if not path or not Path(path).exists():
            return
        try:
            if self.variant_preview_player:
                try:
                    self.variant_preview_player.stop()
                    self.variant_preview_player.close()
                except Exception:
                    pass
                self.variant_preview_player=None

            f=sf.SoundFile(path,"r")
            sr=f.samplerate
            ch=f.channels
            start,end=self._selected_compare_segment()
            if hasattr(self,"arrangement") and self.arrangement.loop_compare.isChecked() and start>0:
                f.seek(int(start*sr))

            loop_start=int(start*sr)
            loop_end=int(end*sr) if end else f.frames
            loop_enabled=bool(hasattr(self,"arrangement") and self.arrangement.loop_compare.isChecked())

            def cb(outdata,frames,time_info,status):
                data=f.read(frames,dtype="float32",always_2d=True)
                if len(data)<frames:
                    if loop_enabled:
                        f.seek(loop_start)
                        extra=f.read(frames-len(data),dtype="float32",always_2d=True)
                        data=np.vstack([data,extra]) if len(data) else extra
                    else:
                        outdata[:len(data)] = data
                        if len(data)<frames: outdata[len(data):]=0
                        raise sd.CallbackStop()

                if loop_enabled and f.tell() >= loop_end:
                    remain=max(0,loop_end-(f.tell()-len(data)))
                    if remain < len(data):
                        first=data[:remain]
                        f.seek(loop_start)
                        second=f.read(len(data)-remain,dtype="float32",always_2d=True)
                        data=np.vstack([first,second]) if len(first) else second
                outdata[:] = data[:frames]

            stream=sd.OutputStream(samplerate=sr,channels=ch,dtype="float32",callback=cb)
            stream.start()
            self.variant_preview_player=stream
            self._variant_preview_file=f
            self.active_variant=variant
        except Exception as e:
            QMessageBox.critical(self,"试听失败",str(e))

    def stop_variant_preview(self):
        if self.variant_preview_player:
            try:
                self.variant_preview_player.stop()
                self.variant_preview_player.close()
            except Exception:
                pass
            self.variant_preview_player=None
        try:
            if hasattr(self,"_variant_preview_file") and self._variant_preview_file:
                self._variant_preview_file.close()
        except Exception:
            pass

    def adopt_variant(self, variant):
        if not self.arrangement_variants.get(variant):
            QMessageBox.warning(self,"提示",f"版本 {variant} 还没有保存。")
            return
        self._push_undo_state(f"采用 {variant}")
        self.active_variant=variant
        chosen=json.loads(json.dumps(self.arrangement_variants[variant],ensure_ascii=False))
        self.manual_section_overrides=chosen.get("manual_overrides",self.manual_section_overrides)
        self.arrangement_result=chosen.copy()
        song=Path(self.song_file).stem if self.song_file else "project"
        folder=BASE_DIR/"arrangement_history"
        folder.mkdir(parents=True,exist_ok=True)
        state=self._snapshot_state(f"采用版本 {variant}")
        p=folder/f"{song}_adopt_{variant}_{int(time.time())}.json"
        p.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
        state["file"]=str(p)
        self.arrangement_history.append(state)
        self.refresh_history_table()
        QMessageBox.information(self,"已采用",f"版本 {variant} 已设为当前正式编配。")

    def refresh_compare_sections(self):
        if not hasattr(self,"arrangement"):
            return
        combo=self.arrangement.compare_section
        combo.clear()
        for i,s in enumerate(self.section_timeline or []):
            combo.addItem(f"{s.get('name','段落')} · {self._format_time(s.get('seconds',0))}",i)

    def refresh_manual_sections(self):
        if not hasattr(self,"arrangement"):
            return
        combo=self.arrangement.manual_section
        current=combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        sections=[]
        for row in self.chord_timeline or []:
            s=row.get("section","段落")
            if s not in sections:
                sections.append(s)
        combo.addItems(sections)
        if current:
            idx=combo.findText(current)
            if idx>=0: combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        self.load_manual_section_settings()

    def load_manual_section_settings(self):
        if not hasattr(self,"arrangement"):
            return
        sec=self.arrangement.manual_section.currentText()
        data=self.manual_section_overrides.get(sec,{})
        pairs=[
            ("manual_guitar","guitar"),
            ("manual_bass","bass"),
            ("manual_drums","drums"),
            ("manual_piano","piano"),
            ("manual_fill","fill"),
            ("manual_space","space"),
        ]
        for attr,key in pairs:
            getattr(self.arrangement,attr).setValue(int(data.get(key,0)))

    def capture_manual_section_settings(self):
        if not hasattr(self,"arrangement"):
            return
        sec=self.arrangement.manual_section.currentText()
        if not sec:
            return
        self.manual_section_overrides[sec]={
            "guitar":self.arrangement.manual_guitar.value(),
            "bass":self.arrangement.manual_bass.value(),
            "drums":self.arrangement.manual_drums.value(),
            "piano":self.arrangement.manual_piano.value(),
            "fill":self.arrangement.manual_fill.value(),
            "space":self.arrangement.manual_space.value(),
        }

    def save_arrangement_variant(self, name):
        self._push_undo_state(f"保存版本 {name}")
        self.capture_manual_section_settings()
        data={
            "name":name,
            "energy_curve":self.arrangement.energy_curve.currentText(),
            "manual_overrides":json.loads(json.dumps(self.manual_section_overrides,ensure_ascii=False)),
            "player_profiles":self._current_player_profiles(),
            "transpose":self.arrangement.transpose.value(),
            "arrange_mode":self.arrangement.arrange_mode.currentText(),
        }
        self.arrangement_variants[name]=data
        if self.song_file:
            folder=BASE_DIR/"arrangement_variants"
            folder.mkdir(parents=True,exist_ok=True)
            p=folder/f"{Path(self.song_file).stem}_variant_{name}.json"
            p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        QMessageBox.information(self,"版本已保存",f"已保存编配版本 {name}")

    def _strategy_with_manual_override(self, section_name, strategy, variant=None):
        st=dict(strategy)
        source=self.manual_section_overrides
        if variant and self.arrangement_variants.get(variant):
            source=self.arrangement_variants[variant].get("manual_overrides",source)
        ov=source.get(section_name,{})
        for key in ("guitar","bass","drums","piano","fill"):
            if key in ov:
                st[key]=max(0.05,min(1.0,st.get(key,0.7)*(1.0+float(ov[key])/100.0)))
        if "space" in ov:
            st["space"]=max(0.0,min(0.95,st.get("space",0.2)+float(ov["space"])/100.0))
            # more space also subtly reduces active density
            reduce_factor=max(0.45,1.0-float(ov["space"])/180.0)
            if float(ov["space"])>0:
                for key in ("guitar","bass","drums","piano"):
                    st[key]*=reduce_factor
        return st

    def generate_variant_midi(self, variant):
        if not self.arrangement_variants.get(variant):
            self.save_arrangement_variant(variant)
        if not self.chord_timeline:
            QMessageBox.warning(self,"提示","请先分析歌曲。")
            return

        try:
            from mido import MidiFile, MidiTrack, MetaMessage, bpm2tempo
            v=self.arrangement_variants.get(variant,{})
            profiles=v.get("player_profiles") or self._current_player_profiles()
            mode=v.get("arrange_mode") or self.arrangement.arrange_mode.currentText()
            song=Path(self.song_file).stem if self.song_file else "song"
            out,_=QFileDialog.getSaveFileName(
                self,f"生成 {variant} 版 MIDI",
                str(EXPORTS_DIR/f"{song}_{mode}_variant_{variant}.mid"),
                "MIDI (*.mid)"
            )
            if not out:
                return

            mid=MidiFile(ticks_per_beat=480)
            meta=MidiTrack(); mid.tracks.append(meta)
            bpm=float(self.analysis_result.get("bpm",120) or 120)
            meta.append(MetaMessage('set_tempo',tempo=bpm2tempo(bpm),time=0))
            meta.append(MetaMessage('time_signature',numerator=4,denominator=4,time=0))

            guitar=MidiTrack(); guitar.append(MetaMessage('track_name',name=f'Juweier Variant {variant} Guitar',time=0)); mid.tracks.append(guitar)
            bass=MidiTrack(); bass.append(MetaMessage('track_name',name=f'Juweier Variant {variant} Bass',time=0)); mid.tracks.append(bass)
            piano=MidiTrack(); piano.append(MetaMessage('track_name',name=f'Juweier Variant {variant} Piano',time=0)); mid.tracks.append(piano)
            drums=MidiTrack(); drums.append(MetaMessage('track_name',name=f'Juweier Variant {variant} Drums',time=0)); mid.tracks.append(drums)

            section_map=self._build_section_map()
            semis=int(v.get("transpose",self.arrangement.transpose.value()))
            prev_section=None
            total=max(1,len(self.chord_timeline))
            for idx,row in enumerate(self.chord_timeline):
                self.arrangement.progress.setValue(int(idx/total*95))
                QApplication.processEvents()
                chord=(row.get("chords") or ["C"])[0]
                ns=self._smart_chord_notes(chord,semis)
                section=row.get("section","段落")
                strategy,role=self._section_strategy_for_name(section,section_map)
                strategy=self._strategy_with_manual_override(section,strategy,variant)
                boundary=prev_section is not None and section!=prev_section
                prev_section=section
                self._musical_intelligence_bar(
                    (guitar,bass,piano,drums),
                    row,ns,profiles,strategy,role,boundary,mode
                )
            mid.save(out)
            self.arrangement.progress.setValue(100)
            self.arrangement_variants[variant]["midi"]=out
            QMessageBox.information(self,"生成完成",f"{variant} 版 MIDI 已生成：\n{out}")
        except Exception as e:
            self.arrangement.progress.setValue(0)
            QMessageBox.critical(self,"生成失败",str(e))

    def compare_variant_summary(self):
        a=self.arrangement_variants.get("A",{})
        b=self.arrangement_variants.get("B",{})
        return {"A":a,"B":b}

    def generate_musical_intelligence_midi(self):
        if not self.chord_timeline:
            QMessageBox.warning(self,"提示","请先分析歌曲和弦。")
            return
        if not getattr(self.arrangement,"musical_intelligence",None) or not self.arrangement.musical_intelligence.isChecked():
            return self.generate_smart_arrangement_midi()

        try:
            from mido import MidiFile, MidiTrack, MetaMessage, bpm2tempo
            profiles=self._current_player_profiles()
            mode=self.arrangement.arrange_mode.currentText()
            song=Path(self.song_file).stem if self.song_file else "song"
            out,_=QFileDialog.getSaveFileName(
                self,"导出音乐性智能编配 MIDI",
                str(EXPORTS_DIR/f"{song}_{mode}_musical.mid"),
                "MIDI (*.mid)"
            )
            if not out:
                return

            mid=MidiFile(ticks_per_beat=480)
            meta=MidiTrack(); mid.tracks.append(meta)
            bpm=float(self.analysis_result.get("bpm",120) or 120)
            meta.append(MetaMessage('set_tempo',tempo=bpm2tempo(bpm),time=0))
            meta.append(MetaMessage('time_signature',numerator=4,denominator=4,time=0))

            guitar=MidiTrack(); guitar.append(MetaMessage('track_name',name='Juweier Musical Guitar',time=0)); mid.tracks.append(guitar)
            bass=MidiTrack(); bass.append(MetaMessage('track_name',name='Juweier Musical Bass',time=0)); mid.tracks.append(bass)
            piano=MidiTrack(); piano.append(MetaMessage('track_name',name='Juweier Musical Piano',time=0)); mid.tracks.append(piano)
            drums=MidiTrack(); drums.append(MetaMessage('track_name',name='Juweier Musical Drums',time=0)); mid.tracks.append(drums)

            section_map=self._build_section_map()
            semis=self.arrangement.transpose.value()
            prev_section=None
            total=max(1,len(self.chord_timeline))

            for idx,row in enumerate(self.chord_timeline):
                self.arrangement.progress.setValue(int(idx/total*95))
                QApplication.processEvents()
                chord=(row.get("chords") or ["C"])[0]
                ns=self._smart_chord_notes(chord,semis)
                section=row.get("section","段落")
                strategy,role=self._section_strategy_for_name(section,section_map)
                self.capture_manual_section_settings()
                strategy=self._strategy_with_manual_override(section,strategy)
                boundary=prev_section is not None and section!=prev_section
                prev_section=section
                self._musical_intelligence_bar(
                    (guitar,bass,piano,drums),
                    row,ns,profiles,strategy,role,boundary,mode
                )

            mid.save(out)
            self.arrangement_result={
                "mode":mode,
                "midi":out,
                "transpose":semis,
                "smart_arranger":True,
                "musical_intelligence":True,
                "energy_curve":self.arrangement.energy_curve.currentText(),
                "section_map":section_map,
                "player_profiles":profiles,
            }
            self.arrangement.progress.setValue(100)
            self.refresh_musical_intelligence_preview()
            QMessageBox.information(
                self,"音乐性智能编配完成",
                f"已根据段落强弱、乐器空间和当前乐手设置生成新 MIDI：\n{out}"
            )
        except Exception as e:
            self.arrangement.progress.setValue(0)
            QMessageBox.critical(self,"音乐性编配失败",str(e))

    def generate_smart_arrangement_midi(self):
        if not self.chord_timeline:
            QMessageBox.warning(self,"提示","请先分析歌曲和弦。")
            return
        try:
            from mido import MidiFile, MidiTrack, Message, MetaMessage, bpm2tempo
            profiles=self._current_player_profiles()
            mode=self.arrangement.arrange_mode.currentText()
            song=Path(self.song_file).stem if self.song_file else "song"
            out,_=QFileDialog.getSaveFileName(
                self,"导出智能编配 MIDI",
                str(EXPORTS_DIR/f"{song}_{mode}_smart.mid"),
                "MIDI (*.mid)"
            )
            if not out:
                return

            mid=MidiFile(ticks_per_beat=480)
            meta=MidiTrack(); mid.tracks.append(meta)
            bpm=float(self.analysis_result.get("bpm",120) or 120)
            meta.append(MetaMessage('set_tempo',tempo=bpm2tempo(bpm),time=0))
            meta.append(MetaMessage('time_signature',numerator=4,denominator=4,time=0))

            guitar=MidiTrack(); guitar.append(MetaMessage('track_name',name='Juweier Smart Guitar',time=0)); mid.tracks.append(guitar)
            bass=MidiTrack(); bass.append(MetaMessage('track_name',name='Juweier Smart Bass',time=0)); mid.tracks.append(bass)
            piano=MidiTrack(); piano.append(MetaMessage('track_name',name='Juweier Smart Piano',time=0)); mid.tracks.append(piano)
            drums=MidiTrack(); drums.append(MetaMessage('track_name',name='Juweier Smart Drums',time=0)); mid.tracks.append(drums)

            semis=self.arrangement.transpose.value()
            prev_section=None
            total=max(1,len(self.chord_timeline))
            for idx,row in enumerate(self.chord_timeline):
                self.arrangement.progress.setValue(int(idx/total*95))
                QApplication.processEvents()
                chord=(row.get("chords") or ["C"])[0]
                ns=self._smart_chord_notes(chord,semis)
                section=row.get("section","")
                boundary = prev_section is not None and section != prev_section
                prev_section=section

                self._guitar_bar_events(guitar,ns,profiles.get("guitar",{}),mode)
                self._bass_bar_events(bass,ns,profiles.get("bass",{}))
                self._piano_bar_events(piano,ns,profiles.get("piano",{}))
                self._drum_bar_events(drums,profiles.get("drums",{}),boundary)

            mid.save(out)
            self.arrangement_result={
                "mode":mode,
                "midi":out,
                "transpose":semis,
                "smart_arranger":True,
                "player_profiles":profiles
            }
            self.arrangement.progress.setValue(100)
            QMessageBox.information(
                self,"智能编配完成",
                f"已按照当前吉他/Bass/鼓/键盘设置生成新 MIDI：\\n{out}"
            )
        except Exception as e:
            self.arrangement.progress.setValue(0)
            QMessageBox.critical(self,"智能编配失败",str(e))

    def generate_arrangement_midi(self):
        if not self.chord_timeline:
            QMessageBox.warning(self,"提示","请先分析歌曲和弦。")
            return
        try:
            from mido import MidiFile, MidiTrack, Message, MetaMessage, bpm2tempo
            mode=self.arrangement.arrange_mode.currentText()
            song=Path(self.song_file).stem if self.song_file else "song"
            out,_=QFileDialog.getSaveFileName(self,"导出新编配 MIDI",str(EXPORTS_DIR/f"{song}_{mode}.mid"),"MIDI (*.mid)")
            if not out:
                return
            mid=MidiFile(ticks_per_beat=480)
            meta=MidiTrack()
            mid.tracks.append(meta)
            bpm=float(self.analysis_result.get("bpm",120) or 120)
            meta.append(MetaMessage('set_tempo',tempo=bpm2tempo(bpm),time=0))
            meta.append(MetaMessage('time_signature',numerator=4,denominator=4,time=0))
            notes={"C":60,"C#":61,"D":62,"D#":63,"E":64,"F":65,"F#":66,"G":67,"G#":68,"A":69,"A#":70,"B":71}
            semis=self.arrangement.transpose.value()

            def chord_notes(ch):
                m=re.match(r"^([A-G](?:#|b)?)(m?)",ch or "")
                if not m:
                    return [60,64,67]
                root=self._transpose_note_name(m.group(1),semis)
                base=notes.get(root,60)
                third=3 if m.group(2)=="m" else 4
                return [base,base+third,base+7]

            guitar=MidiTrack(); guitar.append(MetaMessage('track_name',name='Juweier Guitar',time=0)); mid.tracks.append(guitar)
            bass=MidiTrack(); bass.append(MetaMessage('track_name',name='Juweier Bass',time=0)); mid.tracks.append(bass)
            piano=MidiTrack(); piano.append(MetaMessage('track_name',name='Juweier Piano',time=0)); mid.tracks.append(piano)
            drums=MidiTrack(); drums.append(MetaMessage('track_name',name='Juweier Drums',time=0)); mid.tracks.append(drums)

            for row in self.chord_timeline:
                chord=(row.get("chords") or ["C"])[0]
                ns=chord_notes(chord)
                gvel=48 if "钢琴" in mode else 72
                for beat in range(4):
                    for n in ns:
                        guitar.append(Message('note_on',note=n,velocity=gvel,time=0,channel=0))
                    guitar.append(Message('note_off',note=ns[0],velocity=0,time=360,channel=0))
                    for n in ns[1:]:
                        guitar.append(Message('note_off',note=n,velocity=0,time=0,channel=0))
                    guitar.append(Message('note_on',note=ns[0],velocity=1,time=120,channel=0))
                    guitar.append(Message('note_off',note=ns[0],velocity=0,time=0,channel=0))

                bbase=ns[0]-24
                for beat in range(4):
                    bn=bbase if beat%2==0 else bbase+7
                    bass.append(Message('note_on',note=max(24,bn),velocity=78,time=0,channel=1))
                    bass.append(Message('note_off',note=max(24,bn),velocity=0,time=480,channel=1))

                pvel=48 if ("木吉他" in mode or "不插电" in mode) else 68
                for n in ns:
                    piano.append(Message('note_on',note=n+12,velocity=pvel,time=0,channel=2))
                piano.append(Message('note_off',note=ns[0]+12,velocity=0,time=1920,channel=2))
                for n in ns[1:]:
                    piano.append(Message('note_off',note=n+12,velocity=0,time=0,channel=2))

                for eighth in range(8):
                    simultaneous=[(42,45)]
                    if eighth in (0,4):
                        simultaneous.append((36,88))
                    if eighth in (2,6):
                        simultaneous.append((38,82))
                    for note,vel in simultaneous:
                        drums.append(Message('note_on',note=note,velocity=vel,time=0,channel=9))
                    drums.append(Message('note_off',note=42,velocity=0,time=240,channel=9))
                    for note,_ in simultaneous[1:]:
                        drums.append(Message('note_off',note=note,velocity=0,time=0,channel=9))
            mid.save(out)
            self.arrangement_result={"mode":mode,"midi":out,"transpose":semis}
            QMessageBox.information(self,"AI 改编 MIDI 完成",f"已生成新的伴奏编配 MIDI：\n{out}\n\n下一阶段可用独立音源渲染成全新的 WAV/MP3 伴奏。")
        except Exception as e:
            QMessageBox.critical(self,"生成 MIDI 失败",str(e))


    def choose_soundfont(self):
        p,_ = QFileDialog.getOpenFileName(
            self, "选择 SoundFont", "", "SoundFont (*.sf2 *.sf3);;所有文件 (*.*)"
        )
        if not p:
            return
        self.soundfont_path = p
        if hasattr(self, "arrangement"):
            self.arrangement.soundfont_edit.setText(p)

    def _find_fluidsynth(self):
        candidates = [
            BASE_DIR/"runtime"/"fluidsynth"/"bin"/"fluidsynth.exe",
            BASE_DIR/"runtime"/"fluidsynth"/"fluidsynth.exe",
            BASE_DIR/"fluidsynth.exe",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        from shutil import which
        return which("fluidsynth") or ""

    def _find_ffmpeg(self):
        candidates = [
            BASE_DIR/"runtime"/"ffmpeg"/"bin"/"ffmpeg.exe",
            BASE_DIR/"runtime"/"ffmpeg"/"ffmpeg.exe",
            BASE_DIR/"ffmpeg"/"ffmpeg.exe",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        from shutil import which
        return which("ffmpeg") or ""

    def _resolve_arrangement_midi(self):
        p = str(self.arrangement_result.get("midi","") if self.arrangement_result else "")
        if p and Path(p).exists():
            return p
        QMessageBox.warning(self, "提示", "请先生成“新编配 MIDI”。")
        return ""

    def render_arrangement_wav(self):
        midi = self._resolve_arrangement_midi()
        if not midi:
            return
        sf = self.arrangement.soundfont_edit.text().strip() if hasattr(self, "arrangement") else self.soundfont_path
        if not sf or not Path(sf).exists():
            QMessageBox.warning(self, "提示", "请先选择一个合法的 SoundFont（.sf2/.sf3）。")
            return
        fluidsynth = self._find_fluidsynth()
        if not fluidsynth:
            QMessageBox.critical(
                self, "缺少 FluidSynth",
                "未找到 fluidsynth.exe。\n请把 Windows FluidSynth 放到 runtime\\fluidsynth\\bin\\fluidsynth.exe，"
                "或安装后加入 PATH。"
            )
            return
        out,_ = QFileDialog.getSaveFileName(
            self, "渲染新编配 WAV",
            str(EXPORTS_DIR/f"{Path(midi).stem}_render.wav"),
            "WAV (*.wav)"
        )
        if not out:
            return
        try:
            self.arrangement.progress.setValue(15)
            QApplication.processEvents()
            cmd = [
                fluidsynth, "-ni", sf, midi,
                "-F", out, "-r", "44100"
            ]
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if p.returncode != 0 or not Path(out).exists():
                raise RuntimeError((p.stderr or p.stdout or "FluidSynth 渲染失败")[-2000:])
            self.arrangement.progress.setValue(100)
            self.arrangement_result["render_wav"] = out
            QMessageBox.information(self, "渲染完成", f"已生成新的伴奏 WAV：\n{out}")
        except Exception as e:
            self.arrangement.progress.setValue(0)
            QMessageBox.critical(self, "WAV 渲染失败", str(e))

    def render_arrangement_mp3(self):
        midi = self._resolve_arrangement_midi()
        if not midi:
            return
        sf = self.arrangement.soundfont_edit.text().strip() if hasattr(self, "arrangement") else self.soundfont_path
        if not sf or not Path(sf).exists():
            QMessageBox.warning(self, "提示", "请先选择 SoundFont。")
            return
        fluidsynth = self._find_fluidsynth()
        ffmpeg = self._find_ffmpeg()
        if not fluidsynth:
            QMessageBox.critical(self, "缺少 FluidSynth", "未找到 fluidsynth.exe。")
            return
        if not ffmpeg:
            QMessageBox.critical(self, "缺少 FFmpeg", "未找到 ffmpeg.exe，无法编码 MP3。")
            return
        out,_ = QFileDialog.getSaveFileName(
            self, "渲染新编配 MP3",
            str(EXPORTS_DIR/f"{Path(midi).stem}_render.mp3"),
            "MP3 (*.mp3)"
        )
        if not out:
            return
        tmp = BASE_DIR/"temp"/f"{Path(midi).stem}_render_tmp.wav"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.arrangement.progress.setValue(10)
            QApplication.processEvents()
            p1 = subprocess.run(
                [fluidsynth, "-ni", sf, midi, "-F", str(tmp), "-r", "44100"],
                capture_output=True, text=True, timeout=600
            )
            if p1.returncode != 0 or not tmp.exists():
                raise RuntimeError(p1.stderr or p1.stdout or "FluidSynth 渲染失败")
            self.arrangement.progress.setValue(75)
            QApplication.processEvents()
            p2 = subprocess.run(
                [ffmpeg, "-y", "-i", str(tmp), "-codec:a", "libmp3lame", "-b:a", "320k", out],
                capture_output=True, text=True, timeout=300
            )
            if p2.returncode != 0 or not Path(out).exists():
                raise RuntimeError(p2.stderr[-2000:] if p2.stderr else "FFmpeg MP3 编码失败")
            self.arrangement.progress.setValue(100)
            self.arrangement_result["render_mp3"] = out
            QMessageBox.information(self, "渲染完成", f"已生成新的伴奏 MP3：\n{out}")
        except Exception as e:
            self.arrangement.progress.setValue(0)
            QMessageBox.critical(self, "MP3 渲染失败", str(e))
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

    def _musicxml_chord_parts(self, chord):
        import re as _re
        m=_re.match(r"^([A-G])([#b]?)(.*)$", chord or "C")
        if not m:
            return "C",0,"major"
        step=m.group(1)
        accidental=m.group(2)
        suffix=m.group(3)
        alter=1 if accidental=="#" else (-1 if accidental=="b" else 0)
        kind_map={
            "":"major","m":"minor","7":"dominant","maj7":"major-seventh",
            "m7":"minor-seventh","sus4":"suspended-fourth","dim":"diminished"
        }
        return step,alter,kind_map.get(suffix,"major")

    def export_musicxml(self):
        if not self.chord_timeline:
            QMessageBox.warning(self, "提示", "请先完成和弦/乐谱分析。")
            return
        song=Path(self.song_file).stem if self.song_file else "song"
        p,_=QFileDialog.getSaveFileName(
            self, "导出 MusicXML",
            str(EXPORTS_DIR/f"{song}_Juweier.musicxml"),
            "MusicXML (*.musicxml *.xml)"
        )
        if not p:
            return
        rows=self._score_rows_transposed()
        key_map={"C":0,"G":1,"D":2,"A":3,"E":4,"B":5,"F#":6,"F":-1,"A#":-2,"D#":-3,"G#":-4,"C#":7}
        target_key=self._transpose_note_name(
            self.analysis_result.get("key","C"),
            self.arrangement.transpose.value()
        )
        fifths=key_map.get(target_key,0)
        parts=[]
        for idx,row in enumerate(rows, start=1):
            chord=(row.get("chords") or ["C"])[0]
            step,alter,kind=self._musicxml_chord_parts(chord)
            attrs=""
            if idx==1:
                attrs=f"""<attributes><divisions>1</divisions><key><fifths>{fifths}</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>"""
            alter_xml=f"<root-alter>{alter}</root-alter>" if alter else ""
            parts.append(
                f"""<measure number="{idx}">{attrs}
<harmony><root><root-step>{step}</root-step>{alter_xml}</root><kind>{kind}</kind></harmony>
<direction placement="above"><direction-type><words>{html.escape(row.get("section",""))}</words></direction-type></direction>
<note><rest/><duration>4</duration><type>whole</type></note>
</measure>"""
            )
        xml=f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
<work><work-title>{html.escape(song)}</work-title></work>
<part-list><score-part id="P1"><part-name>Juweier Lead Sheet</part-name></score-part></part-list>
<part id="P1">{''.join(parts)}</part>
</score-partwise>"""
        Path(p).write_text(xml,encoding="utf-8")
        QMessageBox.information(self, "MusicXML 完成", f"已生成：\n{p}")

    def export_melody_reference(self):
        if not self.song_file:
            QMessageBox.warning(self, "提示", "请先导入歌曲。")
            return
        try:
            import librosa
            y,sr=librosa.load(self.song_file,sr=22050,mono=True)
            f0, voiced_flag, voiced_prob = librosa.pyin(
                y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"), sr=sr
            )
            times=librosa.times_like(f0,sr=sr)
            refs=[]
            last_note=None
            start=None
            for t,hz,voiced in zip(times,f0,voiced_flag):
                note=None
                if voiced and hz is not None and not np.isnan(hz):
                    midi=int(round(librosa.hz_to_midi(hz)))
                    note=librosa.midi_to_note(midi, octave=True, cents=False)
                if note!=last_note:
                    if last_note is not None and start is not None:
                        refs.append({"start":float(start),"end":float(t),"note":last_note})
                    start=float(t) if note else None
                    last_note=note
            self.melody_reference=refs
            song=Path(self.song_file).stem
            p,_=QFileDialog.getSaveFileName(
                self, "导出主旋律参考",
                str(EXPORTS_DIR/f"{song}_melody_reference.csv"),
                "CSV (*.csv)"
            )
            if not p:
                return
            lines=["start_seconds,end_seconds,note"]
            for r in refs:
                if r["end"]-r["start"] >= 0.08:
                    lines.append(f'{r["start"]:.3f},{r["end"]:.3f},{r["note"]}')
            Path(p).write_text("\n".join(lines),encoding="utf-8")
            QMessageBox.information(
                self,"主旋律参考完成",
                f"已生成单声部音高参考：\n{p}\n\n这是自动音高跟踪结果，不等同于人工校对的主旋律总谱。"
            )
        except Exception as e:
            QMessageBox.critical(self,"主旋律参考转写失败",str(e))


    def _root_midi(self, chord, octave=4):
        import re as _re
        m=_re.match(r"^([A-G])([#b]?)(m?)", chord or "C")
        if not m:
            return 60
        pc={"C":0,"D":2,"E":4,"F":5,"G":7,"A":9,"B":11}[m.group(1)]
        if m.group(2)=="#": pc+=1
        elif m.group(2)=="b": pc-=1
        return 12*(octave+1)+(pc%12)

    def export_instrument_musicxml(self, instrument):
        if not self.chord_timeline:
            QMessageBox.warning(self,"提示","请先分析歌曲和弦。")
            return
        song=Path(self.song_file).stem if self.song_file else "song"
        p,_=QFileDialog.getSaveFileName(
            self, f"导出 {instrument} MusicXML",
            str(EXPORTS_DIR/f"{song}_{instrument}.musicxml"),
            "MusicXML (*.musicxml)"
        )
        if not p: return
        rows=self._score_rows_transposed()
        measures=[]
        for i,row in enumerate(rows,1):
            chord=(row.get("chords") or ["C"])[0]
            midi=self._root_midi(chord,3 if instrument=="bass" else 4)
            step_names=["C","C","D","D","E","F","F","G","G","A","A","B"]
            alters=[0,1,0,1,0,0,1,0,1,0,1,0]
            pc=midi%12
            octave=midi//12-1
            step=step_names[pc]; alter=alters[pc]
            alter_xml=f"<alter>{alter}</alter>" if alter else ""
            attrs=""
            if i==1:
                clef="<sign>F</sign><line>4</line>" if instrument=="bass" else "<sign>G</sign><line>2</line>"
                attrs=f"<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time><clef>{clef}</clef></attributes>"
            if instrument=="drums":
                notes = """
                <note><unpitched><display-step>G</display-step><display-octave>5</display-octave></unpitched><duration>2</duration><voice>1</voice><type>eighth</type><notehead>x</notehead></note>
                <note><unpitched><display-step>C</display-step><display-octave>5</display-octave></unpitched><duration>2</duration><voice>1</voice><type>eighth</type></note>
                <note><unpitched><display-step>G</display-step><display-octave>5</display-octave></unpitched><duration>2</duration><voice>1</voice><type>eighth</type><notehead>x</notehead></note>
                <note><unpitched><display-step>F</display-step><display-octave>4</display-octave></unpitched><duration>2</duration><voice>1</voice><type>eighth</type></note>
                """
                notes = notes*2
            elif instrument=="guitar":
                # Quarter-note chord-root picking reference.
                notes="".join([
                    f"<note><pitch><step>{step}</step>{alter_xml}<octave>{octave}</octave></pitch><duration>4</duration><type>quarter</type></note>"
                    for _ in range(4)
                ])
            elif instrument=="piano":
                notes=f"<note><pitch><step>{step}</step>{alter_xml}<octave>{octave}</octave></pitch><duration>16</duration><type>whole</type></note>"
            else:
                notes="".join([
                    f"<note><pitch><step>{step}</step>{alter_xml}<octave>{octave}</octave></pitch><duration>8</duration><type>half</type></note>"
                    for _ in range(2)
                ])
            measures.append(f"<measure number='{i}'>{attrs}{notes}</measure>")
        part_name={"guitar":"Guitar","bass":"Bass","drums":"Drums","piano":"Piano"}.get(instrument,instrument)
        xml=f"""<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
<work><work-title>{html.escape(song)}</work-title></work>
<part-list><score-part id="P1"><part-name>{part_name}</part-name></score-part></part-list>
<part id="P1">{''.join(measures)}</part></score-partwise>"""
        Path(p).write_text(xml,encoding="utf-8")
        QMessageBox.information(self,"分谱完成",f"已导出：\n{p}")


    def save_live_preset_file(self):
        if not self.song_file:
            return
        song=Path(self.song_file).stem
        p=BASE_DIR/"presets"/f"{song}.json"
        p.parent.mkdir(parents=True,exist_ok=True)
        data={
            "song":self.song_file,
            "tracks":{
                key:{
                    "mute":row.mute.isChecked(),
                    "solo":row.solo.isChecked(),
                    "volume":row.volume.value()
                } for key,row in self.studio.rows.items()
            },
            "transpose":self.arrangement.transpose.value() if hasattr(self,"arrangement") else 0,
            "live_transpose":self.live_pro.transpose.value() if hasattr(self,"live_pro") else 0,
            "live_speed":self.live_pro.speed.value() if hasattr(self,"live_pro") else 1.0
        }
        p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")

    def load_live_preset_file(self):
        if not self.song_file:
            return
        p=BASE_DIR/"presets"/f"{Path(self.song_file).stem}.json"
        if not p.exists():
            return
        try:
            data=json.loads(p.read_text(encoding="utf-8"))
            for key,val in data.get("tracks",{}).items():
                if key in self.studio.rows:
                    row=self.studio.rows[key]
                    row.mute.setChecked(bool(val.get("mute",False)))
                    row.solo.setChecked(bool(val.get("solo",False)))
                    row.volume.setValue(int(val.get("volume",90)))
            if hasattr(self,"arrangement"):
                self.arrangement.transpose.setValue(int(data.get("transpose",0)))
            if hasattr(self,"live_pro"):
                self.live_pro.transpose.setValue(int(data.get("live_transpose",0)))
                self.live_pro.speed.setValue(float(data.get("live_speed",1.0)))
            self.sync_mix_controls()
        except Exception:
            pass

    def save_project(self):
        if not self.song_file:
            QMessageBox.warning(self, "提示", "当前没有歌曲工程。")
            return
        data = {
            "app": APP_NAME,
            "version": VERSION,
            "markers": self.markers,
            "analysis": self.analysis_result,
            "chord_timeline": self.chord_timeline,
            "section_timeline": self.section_timeline,
            "arrangement": self.arrangement_result,
            "score_transpose": self.arrangement.transpose.value() if hasattr(self, "arrangement") else 0,
            "soundfont": self.arrangement.soundfont_edit.text().strip() if hasattr(self, "arrangement") else "",
            "melody_reference": self.melody_reference,
            "score_follow_enabled": self.score_performance.auto_follow.isChecked() if hasattr(self, "score_performance") else True,
            "instrument_profile": self.instrument_experience._profile_data() if hasattr(self, "instrument_experience") else {},
            "all_player_profiles": self._current_player_profiles(),
            "musical_intelligence_enabled": self.arrangement.musical_intelligence.isChecked() if hasattr(self, "arrangement") else True,
            "energy_curve": self.arrangement.energy_curve.currentText() if hasattr(self, "arrangement") else "自动判断",
            "manual_section_overrides": self.manual_section_overrides,
            "arrangement_variants": self.arrangement_variants,
            "variant_audio": self.variant_audio,
            "active_variant": self.active_variant,
            "arrangement_history": self.arrangement_history,
            "ab_gain": self.ab_gain,
            "ab_current_variant": self.ab_current_variant,
            "pipeline_enabled": True,
            "setlist": self.setlist.items if hasattr(self, "setlist") else [],
            "live_transpose": self.live_pro.transpose.value() if hasattr(self, "live_pro") else 0,
            "live_speed": self.live_pro.speed.value() if hasattr(self, "live_pro") else 1.0,
            "source_song": self.song_file,
            "stem_dir": str(self.stem_dir) if self.stem_dir else None,
            "tracks": {
                key: {
                    "mute": row.mute.isChecked(),
                    "solo": row.solo.isChecked(),
                    "volume": row.volume.value()
                } for key, row in self.studio.rows.items()
            }
        }
        default = PROJECTS_DIR / (Path(self.song_file).stem + ".novria.json")
        p, _ = QFileDialog.getSaveFileName(self, "保存工程", str(default), "橘味儿音乐工程 (*.json)")
        if not p:
            return
        Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        QMessageBox.information(self, "成功", "工程已保存。")

    def export_mix(self):
        if not self.engine.files or not self.stem_dir:
            QMessageBox.warning(self, "提示", "请先完成六轨分离。")
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "导出混音", str(EXPORTS_DIR / f"{Path(self.song_file).stem}_mix.wav"),
            "WAV (*.wav)"
        )
        if not out:
            return
        try:
            self.stop()
            stems = {}
            sr = None
            max_frames = 0
            solos = [k for k,v in self.engine.solo.items() if v]
            active = set(solos) if solos else {k for k in self.engine.files if not self.engine.mute[k]}
            for key, _, _ in STEM_ORDER:
                if key not in active:
                    continue
                stem_path=self.stem_dir/f"{key}.wav"
                if not stem_path.is_file():
                    continue
                data, this_sr = sf.read(str(stem_path), dtype="float32", always_2d=True)
                sr = sr or this_sr
                stems[key] = data * self.engine.volume[key]
                max_frames = max(max_frames, len(data))
            if not stems:
                raise RuntimeError("没有可导出的活动音轨。")
            ch = next(iter(stems.values())).shape[1]
            mix = np.zeros((max_frames, ch), dtype=np.float32)
            for data in stems.values():
                mix[:len(data)] += data
            peak = float(np.max(np.abs(mix)))
            if peak > 0.98:
                mix *= 0.98 / peak
            sf.write(out, mix, sr, subtype="PCM_24")
            QMessageBox.information(self, "导出完成", f"已导出：\n{out}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))


    def seek_ratio_direct(self, ratio):
        try:
            self.engine.seek_ratio(float(ratio))
            if hasattr(self.studio, "timeline"):
                self.studio.timeline.setValue(int(float(ratio)*1000))
            if hasattr(self.studio, "waveform"):
                self.studio.waveform.set_position(float(ratio))
        except Exception:
            pass

    def analyze_music(self):
        """轻量本地分析。优先 librosa；没有时给出明确提示。"""
        if not self.song_file:
            QMessageBox.warning(self, "提示", "请先导入歌曲。")
            return
        try:
            import librosa
            y, sr = librosa.load(self.song_file, sr=None, mono=True, duration=180)
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            try:
                tempo_val = float(np.asarray(tempo).reshape(-1)[0])
            except Exception:
                tempo_val = float(tempo)
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            pitch_class = int(np.argmax(np.mean(chroma, axis=1)))
            names = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
            key = names[pitch_class]
            self.analysis_result = {"bpm": round(tempo_val,1), "key": key}
            self.studio.bpm_label.setText(f"BPM：{tempo_val:.1f}")
            self.studio.key_label.setText(f"调性参考：{key}")
        except ImportError:
            QMessageBox.information(self, "需要分析组件",
                "当前运行环境未包含 librosa。\n重新构建 v0.4.0 EXE 后会自动包含 BPM/调性分析组件。")
        except Exception as e:
            QMessageBox.critical(self, "分析失败", str(e))

    def add_marker(self):
        if not self.engine.files:
            QMessageBox.warning(self, "提示", "请先完成分轨并加载音轨。")
            return
        dur = self.engine.duration_seconds()
        pos = self.engine.position_seconds()
        ratio = (pos/dur) if dur > 0 else 0
        dlg = MarkerDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.markers.append({"name": dlg.name(), "ratio": ratio, "seconds": pos})
            self.markers.sort(key=lambda x: x["ratio"])
            if hasattr(self.studio, "waveform"):
                self.studio.waveform.set_markers(self.markers)

    def load_waveform_if_ready(self):
        try:
            if self.stem_dir and hasattr(self.studio, "waveform"):
                p = Path(self.stem_dir) / "vocals.wav"
                if p.exists():
                    self.studio.waveform.set_waveform_from_wav(p)
        except Exception:
            pass

    def closeEvent(self, event: QCloseEvent):
        library=getattr(self,"music_library",None)
        workers=[getattr(self,"worker",None)]
        if library is not None:
            workers.extend([
                getattr(library,"batch_worker",None),
                getattr(library,"pipeline_batch_worker",None),
            ])
            stage_worker=getattr(library,"pipeline_stage_worker",None)
            if stage_worker and stage_worker.isRunning():
                QMessageBox.information(
                    self,"正在安全完成任务",
                    "当前分析/编配阶段仍在运行。为防止工程文件损坏，请等待本阶段完成后再关闭软件。"
                )
                event.ignore()
                return
        for worker in workers:
            if worker and worker.isRunning():
                try:
                    if hasattr(worker,"stop"):
                        worker.stop()
                    else:
                        worker.requestInterruption()
                    worker.wait(3000)
                except Exception:
                    pass
                if worker.isRunning():
                    QMessageBox.information(
                        self,"正在停止 AI 任务",
                        "六轨任务仍在释放模型资源，请稍后再关闭软件。"
                    )
                    event.ignore()
                    return
        self.engine.close()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
