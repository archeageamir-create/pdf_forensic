from __future__ import annotations

import json
import threading
import time
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QScrollArea
from app.gui.dialogs import ProjectDialog, SettingsDialog
from tests.test_final_review import window as window  # noqa: F401
from tests.test_persistence_reporting import sample_result


def wait_until(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.01)
    assert predicate()


def test_export_is_responsive_and_uses_clicked_file_snapshot(window, tmp_path):
    first, second = sample_result(), sample_result()
    window.service.repository.save(first)
    window.service.repository.save(second)
    window._display_result(first)
    window.notes_edit.setPlainText("Заметка в момент сохранения")
    entered, release = threading.Event(), threading.Event()
    target = tmp_path / "report.json"
    from app.reporting import JsonReportExporter
    original = JsonReportExporter.export

    def delayed(self, result, path):
        entered.set()
        assert release.wait(8)
        return original(self, result, path)

    with patch("app.gui.main_window.QFileDialog.getSaveFileName", return_value=(str(target), "")), patch.object(JsonReportExporter, "export", delayed), patch.object(window, "_report_saved") as shown:
        window._export("json")
        assert entered.wait(3)
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        window._display_result(second)
        window.notes_edit.setPlainText("Другая заметка")
        QApplication.processEvents()
        assert ticks and not window.save_report_button.isEnabled()
        release.set()
        wait_until(lambda: window.export_worker is None)
        shown.assert_called_once_with(target)
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["evidence"]["id"] == first.evidence.id
    assert saved["evidence"]["user_notes"] == "Заметка в момент сохранения"
    assert window.save_report_button.isEnabled()


def test_export_failure_keeps_previous_report_and_enables_retry(window, tmp_path):
    result = sample_result()
    window.service.repository.save(result)
    window._display_result(result)
    target = tmp_path / "old.json"
    target.write_text("previous report", encoding="utf-8")
    with patch("app.gui.main_window.QFileDialog.getSaveFileName", return_value=(str(target), "")), patch("app.gui.main_window.JsonReportExporter.export", side_effect=OSError("disk full")), patch.object(window, "_export_failed") as error:
        window._export("json")
        wait_until(lambda: window.export_worker is None)
        error.assert_called_once()
    assert target.read_text(encoding="utf-8") == "previous report"
    assert window.save_report_button.isEnabled()


def test_small_window_and_dialog_buttons_remain_reachable(window):
    window.sidebar_action.setChecked(True)
    window.show()
    window._display_result(sample_result())
    QApplication.processEvents()
    window.resize(900, 560)
    QApplication.processEvents()
    assert window.width() <= 900 and window.height() <= 560
    window.sidebar_action.setChecked(False)
    assert not window.sidebar.isVisible()
    window.sidebar_action.setChecked(True)
    assert window.sidebar.isVisible()
    for dialog in (ProjectDialog(window), SettingsDialog(window.service.config, window)):
        dialog.resize(640, 420)
        dialog.show()
        QApplication.processEvents()
        assert dialog.height() <= 420
        assert dialog.findChild(QScrollArea)
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons and dialog.rect().contains(buttons.geometry())
        dialog.close()
