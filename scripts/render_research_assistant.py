"""Render research-assistant flows with synthetic material; also export a draft."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.analyzers.timeline import TimelineBuilder
from app.models import AnalysisMode, Finding
from app.reporting import HtmlReportExporter
from app.reporting.docx_exporter import DocxReportExporter
from app.resources.theme import apply_theme
from tests.test_universal import service_at, write_word


def main():
    root = ROOT / ".verification/research-2026-09-28/ui"
    root.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    for font in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "consola.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font))
    app.setStyle("Fusion")
    apply_theme(app)
    with tempfile.TemporaryDirectory(prefix="research-ui-") as temp:
        work = Path(temp)
        service = service_at(work / "workspace")
        path = work / "СИНТЕТИЧЕСКИЙ ПРИМЕР — договор с правками.docx"
        write_word(path, {"word/vbaProject.bin": b"synthetic placeholder, not a real macro"})
        result = service.analyze_file(path, mode=AnalysisMode.CUSTOM)
        a = Finding("XMP", "CreateDate", "2026-01-02T12:00:00+05:00", "Synthetic example A")
        b = Finding("XMP", "CreateDate", "2026-01-02T07:00:00Z", "Synthetic example B")
        result.findings.extend((a, b))
        result.artifacts["timeline"] = TimelineBuilder().build(result.evidence, result.findings)
        service.repository.save(result)
        window = MainWindow(service)
        window.resize(1366, 900)
        window.show()
        window._display_result(result)
        window.tabs.setCurrentIndex(0)
        app.processEvents()
        window.grab().save(str(root / "overview.png"))
        window._review_findings()
        app.processEvents()
        window.grab().save(str(root / "guidance.png"))
        window.findings_explorer._add_observation()
        panel = window.chronology_panel
        window.tabs.setCurrentWidget(panel)
        panel.table.clearSelection()
        for row, event in enumerate(panel.events):
            if event.get("finding_id") in {a.id, b.id}:
                panel.table.selectionModel().select(panel.table.model().index(row, 0),
                    QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        app.processEvents()
        window.grab().save(str(root / "chronology.png"))
        panel._add_note()
        app.processEvents()
        window.grab().save(str(root / "draft.png"))
        window.tabs.setCurrentWidget(window.metadata_tabs)
        window.resize(900, 700)
        app.processEvents()
        window.grab().save(str(root / "guidance-small.png"))
        HtmlReportExporter().export(result, root / "synthetic-research-report.html")
        DocxReportExporter().export(result, root / "synthetic-research-report.docx")
        print(f"Minimum size: {window.minimumSizeHint().width()} x {window.minimumSizeHint().height()}")
        window.close()
    print(root)


if __name__ == "__main__":
    main()
