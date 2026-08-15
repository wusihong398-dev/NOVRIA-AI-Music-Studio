import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QScrollArea, QSizePolicy

from app import main as m

VERSION = "2.1.1"


def resource_root():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


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
    root = resource_root()
    m.VERSION = VERSION
    m.ASSETS_DIR = root / "assets"
    m.ICONS_DIR = m.ASSETS_DIR / "icons"
    if getattr(sys, "frozen", False):
        m.BASE_DIR = Path(sys.executable).resolve().parent
        m.STEMS_DIR = m.BASE_DIR / "stems"
        m.PROJECTS_DIR = m.BASE_DIR / "projects"
        m.EXPORTS_DIR = m.BASE_DIR / "exports"

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
