"""Render the real Qt UI offscreen using clearly synthetic evidence."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from PIL import Image

from app.gui.main_window import MainWindow
from app.resources.theme import apply_theme
from app.models import AnalysisMode
from tests.test_universal import service_at, write_word


def main():
    root = ROOT / ".verification" / "ui"
    root.mkdir(parents=True, exist_ok=True)
    specimen_root = Path(tempfile.mkdtemp(prefix="preview-", dir=root))
    application = QApplication([])
    for font in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "consola.ttf"):
        QFontDatabase.addApplicationFont(
            str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font)
        )
    application.setApplicationName("DFI Preview")
    application.setStyle("Fusion")
    apply_theme(application)
    service = service_at(specimen_root / "workspace")
    word = specimen_root / "ДЕМО — договор с исправлениями.docx"
    write_word(word, {"word/vbaProject.bin": b"synthetic placeholder"})
    result = service.analyze_file(word, mode=AnalysisMode.CUSTOM)
    application.processEvents()
    window = MainWindow(service)
    window.show()
    window.resize(1366, 900)
    window._display_result(result)
    window.tabs.setCurrentIndex(0)
    application.processEvents()
    window.grab().save(str(root / "overview.png"))
    window._review_findings()
    application.processEvents()
    window.grab().save(str(root / "findings.png"))
    window.queue_panel.queue.enqueue(word, mode=AnalysisMode.QUICK)
    window.queue_panel.queue.save_watch(specimen_root, None, AnalysisMode.QUICK)
    window._show_queue()
    application.processEvents()
    window.grab().save(str(root / "queue.png"))
    window._show_welcome()
    application.processEvents()
    window.grab().save(str(root / "welcome.png"))
    window.resize(900, 700)
    window._show_queue()
    application.processEvents()
    window.grab().save(str(root / "queue-small.png"))
    print(
        f"minimum size: {window.minimumSizeHint().width()} x {window.minimumSizeHint().height()}"
    )
    window.close()
    print(root)


if __name__ == "__main__":
    main()
