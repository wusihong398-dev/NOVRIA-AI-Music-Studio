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
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QScrollArea, QSizePolicy, QMessageBox

from app import main as m

VERSION = "2.1.5"


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
    crash_fp.write("\n===== NOVRIA startup v%s =====\n" % VERSION)
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
            worker = base / "NOVRIA-Separation-Worker.exe"
            if not worker.exists():
                raise RuntimeError(f"未找到独立六轨 Worker：{worker}")
            cmd = [str(worker)]
        else:
            cmd = [sys.executable, "-m", "app.separation_worker_process"]
        cmd += [self.input_file, "--output", str(m.STEMS_DIR), "--device", "auto"]
        return cmd

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
            # stderr 合并进 stdout，避免 Demucs/Torch 日志把 stderr PIPE 填满造成死锁。
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
                        # 非 JSON 的 Torch/Demucs 日志仅写入日志，不把乱码推到 UI。
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

    # 导入中心已经通过 fingerprints.json 记录原文件和 working WAV。
    # 旧版音乐库又扫描 imports/working，导致“青花”和“青花_work”重复出现。
    original_scan = m.MusicLibraryPage.scan_imports

    def scan_imports_without_work_duplicates(self):
        original_scan(self)
        try:
            con = self._db()
            rows = con.execute("SELECT id,source_path,working_path,title FROM tracks").fetchall()
            removed = 0
            for row in rows:
                src = str(row["source_path"] or "").replace("/", "\\").lower()
                work = str(row["working_path"] or "").replace("/", "\\").lower()
                title = str(row["title"] or "")
                if src == work and "\\imports\\working\\" in src and title.lower().endswith("_work"):
                    con.execute("DELETE FROM tracks WHERE id=?", (row["id"],))
                    removed += 1
            if removed:
                con.commit()
            con.close()
            if removed:
                self.refresh_library()
        except Exception:
            pass

    m.MusicLibraryPage.scan_imports = scan_imports_without_work_duplicates


def write_gpu_diagnostic(log_fp):
    # 主 GUI 进程不再 import torch，也不初始化 CUDA DLL。
    # CUDA/PyTorch 只允许在独立 Worker 中加载，避免原生 GPU 异常拖垮 Qt 主界面。
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
    win.setWindowTitle(f"{m.APP_NAME}  ·  v{VERSION}")
    win.resize(1500, 940)
    win.setMinimumSize(1100, 700)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
