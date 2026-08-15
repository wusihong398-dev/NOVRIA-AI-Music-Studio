import sys
import os
import shutil
import traceback
import faulthandler
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QScrollArea, QSizePolicy, QMessageBox

from app import main as m

VERSION = "2.1.3"


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
            QMessageBox.critical(None, "NOVRIA 运行异常", f"程序发生异常，已写入：\n{crash_path}\n\n{text[-1200:]}")
        except Exception:
            pass
    sys.excepthook = hook
    return crash_fp


def install_runtime_patches():
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


def write_gpu_diagnostic(log_fp):
    try:
        import torch
        log_fp.write(f"torch={torch.__version__}\n")
        log_fp.write(f"torch.version.cuda={torch.version.cuda}\n")
        log_fp.write(f"cuda_available={torch.cuda.is_available()}\n")
        if torch.cuda.is_available():
            log_fp.write(f"gpu={torch.cuda.get_device_name(0)}\n")
            log_fp.write(f"gpu_count={torch.cuda.device_count()}\n")
    except Exception:
        log_fp.write(traceback.format_exc() + "\n")


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
