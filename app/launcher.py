import sys
import os
import re
import json
import shutil
import subprocess
import traceback
import faulthandler
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QScrollArea, QSizePolicy, QMessageBox,
    QWidget, QHBoxLayout, QPushButton, QLabel
)

from app import main as m

VERSION = "3.2.2"
DISPLAY_NAME = "橘味儿音乐"


def resource_root():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def runtime_base():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


def install_crash_logging():
    base = runtime_base()
    log_dir = base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    crash_path = log_dir / "crash.log"
    crash_fp = open(crash_path, "a", encoding="utf-8", buffering=1)
    crash_fp.write("\n===== Juweier Music startup v%s =====\n" % VERSION)
    try:
        faulthandler.enable(crash_fp, all_threads=True)
    except Exception:
        pass

    def hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            crash_fp.write(text + "\n")
            crash_fp.flush()
        except Exception:
            pass
        try:
            QMessageBox.critical(None, "程序运行异常", f"程序发生异常，已写入：\n{crash_path}\n\n{text[-1200:]}")
        except Exception:
            pass
    sys.excepthook = hook
    return crash_fp


def _decode_worker_line(raw: bytes) -> str:
    if not raw:
        return ""
    for enc in ("utf-8", "gb18030", "mbcs"):
        try:
            return raw.decode(enc).strip()
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace").strip()


class ProcessSeparationWorker(QThread):
    log = Signal(str)
    model_progress = Signal(int, str)
    separation_progress = Signal(int, str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, input_file: str):
        super().__init__()
        self.input_file = input_file
        self.proc = None

    def _command(self):
        base = runtime_base()
        if getattr(sys, "frozen", False):
            worker = base / "Juweier-Separation-Worker.exe"
            if not worker.exists():
                worker = base / "NOVRIA-Separation-Worker.exe"
            if not worker.exists():
                raise RuntimeError(f"未找到独立六轨 Worker：{worker}")
            cmd = [str(worker)]
        else:
            cmd = [sys.executable, "-m", "app.separation_worker_process"]
        cmd += [self.input_file, "--output", str(m.STEMS_DIR), "--device", "auto"]
        return cmd

    def stop(self):
        self.requestInterruption()
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def run(self):
        base = runtime_base()
        log_dir = base / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        worker_log = log_dir / "separation-parent.log"
        try:
            cmd = self._command()
            self.log.emit("六轨任务已切换到独立 GPU Worker 进程")

            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONLEGACYWINDOWSSTDIO"] = "0"

            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
                bufsize=0,
                creationflags=creationflags,
                env=env,
            )

            last_error = ""
            done_emitted = False
            if self.proc.stdout is not None:
                for raw in iter(self.proc.stdout.readline, b""):
                    line = _decode_worker_line(raw)
                    if not line:
                        continue
                    with worker_log.open("a", encoding="utf-8") as f:
                        f.write(line + "\n")
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue
                    kind = data.get("type")
                    if kind == "model_progress":
                        self.model_progress.emit(int(data.get("value", 0)), str(data.get("text", "")))
                    elif kind == "separation_progress":
                        self.separation_progress.emit(int(data.get("value", 0)), str(data.get("text", "")))
                    elif kind == "diagnostic":
                        self.log.emit("Worker: " + json.dumps(data, ensure_ascii=False))
                    elif kind == "failed":
                        last_error = str(data.get("error", "六轨 Worker 失败"))
                    elif kind == "done":
                        stem_dir = str(data.get("stem_dir", ""))
                        if stem_dir:
                            done_emitted = True
                            self.done.emit(stem_dir)

            code = self.proc.wait()
            if code != 0:
                detail = last_error or f"Worker 退出码 {code}，请查看 logs\\separation-parent.log"
                self.failed.emit(f"独立六轨 Worker 异常退出（代码 {code}）：{detail}")
            elif not done_emitted:
                self.failed.emit("独立六轨 Worker 已结束，但没有返回六轨结果。请查看 logs\\separation-parent.log")
        except Exception as exc:
            try:
                with worker_log.open("a", encoding="utf-8") as f:
                    f.write("\n===== parent worker exception =====\n" + traceback.format_exc())
            except Exception:
                pass
            self.failed.emit(str(exc))
        finally:
            self.proc = None


def install_runtime_patches():
    m.re = re
    m.APP_NAME = DISPLAY_NAME
    m.VERSION = VERSION

    def _find_ffmpeg(self):
        exe_dir = runtime_base()
        candidates = [
            exe_dir / "tools" / "ffmpeg" / "ffmpeg.exe",
            exe_dir / "ffmpeg.exe",
            Path(getattr(m, "BASE_DIR", exe_dir)) / "tools" / "ffmpeg" / "ffmpeg.exe",
        ]
        for p in candidates:
            if p.exists() and p.is_file():
                return str(p)
        return shutil.which("ffmpeg") or ""

    m.MainWindow._find_ffmpeg = _find_ffmpeg
    m.SeparationWorker = ProcessSeparationWorker

    # v2.1.7 implements source/work-file de-duplication in MusicLibraryPage
    # directly, so launcher monkey-patching is no longer needed.


def write_gpu_diagnostic(log_fp):
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        log_fp.write("gpu_diagnostic=" + (result.stdout.strip() or result.stderr.strip() or "unavailable") + "\n")
    except Exception:
        log_fp.write("gpu_diagnostic_error=" + traceback.format_exc() + "\n")


def _recommended_capo(win, semis: int) -> int:
    key = str(getattr(win, "analysis_result", {}).get("key", "") or "")
    if not key or not hasattr(win, "_transpose_note_name"):
        return 0
    try:
        sounding_key = win._transpose_note_name(key, semis)
    except Exception:
        return 0

    friendly = {"C": 8, "D": 7, "E": 7, "G": 9, "A": 8}
    best = (0, -999)
    for capo in range(0, 8):
        try:
            shape_key = win._transpose_note_name(sounding_key, -capo)
        except Exception:
            continue
        score = friendly.get(shape_key, 2) - capo * 0.35
        if score > best[1]:
            best = (capo, score)
    return int(best[0])


def install_live_transpose_controls(win):
    page = getattr(win, "score_performance", None)
    arrangement = getattr(win, "arrangement", None)
    if page is None or arrangement is None or not hasattr(arrangement, "transpose"):
        return

    box = QWidget(page)
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 4, 0, 8)

    original_label = QLabel("原调：—")
    current_label = QLabel("当前演出调：—")
    current_label.setObjectName("StatusGood")
    capo_label = QLabel("吉他 Capo：自动")

    down_btn = QPushButton("▼ 降半音")
    reset_btn = QPushButton("恢复原调")
    up_btn = QPushButton("▲ 升半音")
    for b in (down_btn, reset_btn, up_btn):
        b.setMinimumHeight(42)
    down_btn.setProperty("accent", "secondary")
    up_btn.setProperty("accent", "primary")

    row.addWidget(original_label)
    row.addWidget(current_label)
    row.addWidget(capo_label)
    row.addStretch(1)
    row.addWidget(down_btn)
    row.addWidget(reset_btn)
    row.addWidget(up_btn)

    layout = page.layout()
    if layout is not None and hasattr(layout, "insertWidget"):
        layout.insertWidget(1, box)

    def refresh_labels():
        semis = int(arrangement.transpose.value())
        key = str(getattr(win, "analysis_result", {}).get("key", "—") or "—")
        original_label.setText(f"原调：{key}")
        target = key
        if key != "—" and hasattr(win, "_transpose_note_name"):
            try:
                target = win._transpose_note_name(key, semis)
            except Exception:
                target = key
        current_label.setText(f"当前演出调：{target}  ({semis:+d} 半音)")
        capo = _recommended_capo(win, semis)
        capo_label.setText(f"吉他 Capo：{capo} 品" if capo else "吉他 Capo：不夹")
        ie = getattr(win, "instrument_experience", None)
        if ie is not None and hasattr(ie, "guitar_capo"):
            ie.guitar_capo.setValue(capo)
        if hasattr(win, "update_target_key_label"):
            try:
                win.update_target_key_label()
            except Exception:
                pass
        try:
            page.refresh_score()
        except Exception:
            pass

    def change(delta):
        spin = arrangement.transpose
        value = int(spin.value()) + int(delta)
        value = max(int(spin.minimum()), min(int(spin.maximum()), value))
        spin.setValue(value)
        refresh_labels()

    down_btn.clicked.connect(lambda: change(-1))
    up_btn.clicked.connect(lambda: change(1))
    reset_btn.clicked.connect(lambda: (arrangement.transpose.setValue(0), refresh_labels()))
    arrangement.transpose.valueChanged.connect(lambda _v: refresh_labels())

    # Keyboard shortcuts for hands-busy rehearsal; buttons remain the primary control.
    shortcuts = [
        QShortcut(QKeySequence("Ctrl+Down"), win),
        QShortcut(QKeySequence("Ctrl+Up"), win),
        QShortcut(QKeySequence("Ctrl+0"), win),
    ]
    shortcuts[0].activated.connect(lambda: change(-1))
    shortcuts[1].activated.connect(lambda: change(1))
    shortcuts[2].activated.connect(lambda: (arrangement.transpose.setValue(0), refresh_labels()))
    win._dongba_transpose_shortcuts = shortcuts
    win._dongba_transpose_widgets = (box, original_label, current_label, capo_label)
    refresh_labels()


def wrap_stack_pages(win):
    stack = win.stack
    current = stack.currentIndex()
    original = [stack.widget(i) for i in range(stack.count())]
    for widget in original:
        stack.removeWidget(widget)
    for widget in original:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        scroll.setWidget(widget)
        stack.addWidget(scroll)
    stack.setCurrentIndex(current)


def run():
    crash_fp = install_crash_logging()
    root = resource_root()
    m.VERSION = VERSION
    m.APP_NAME = DISPLAY_NAME
    m.ASSETS_DIR = root / "assets"
    m.ICONS_DIR = m.ASSETS_DIR / "icons"
    if getattr(sys, "frozen", False):
        m.BASE_DIR = runtime_base()
        m.STEMS_DIR = m.BASE_DIR / "stems"
        m.PROJECTS_DIR = m.BASE_DIR / "projects"
        m.EXPORTS_DIR = m.BASE_DIR / "exports"
    install_runtime_patches()
    write_gpu_diagnostic(crash_fp)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    theme = m.ASSETS_DIR / "theme.qss"
    if theme.exists():
        app.setStyleSheet(theme.read_text(encoding="utf-8"))

    win = m.MainWindow()
    wrap_stack_pages(win)
    install_live_transpose_controls(win)
    win.setWindowTitle(f"{DISPLAY_NAME}  ·  v{VERSION}")
    win.resize(1500, 940)
    win.setMinimumSize(1100, 700)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
