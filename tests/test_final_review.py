from __future__ import annotations

import json
import os
import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest

from app.gui.main_window import MainWindow
from app.models import ResearchProject, Finding
from app.resources.theme import apply_theme
from tests.test_persistence_reporting import sample_result
from tests.test_universal import service_at


@pytest.fixture
def window(tmp_path):
    application = QApplication.instance() or QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
    apply_theme(application)
    widget = MainWindow(service_at(tmp_path / "workspace"))
    yield widget
    widget.close()
    application.processEvents()


def test_failed_autosave_preserves_draft_blocks_navigation_and_can_retry(window):
    first, second = sample_result(), sample_result()
    window.service.repository.save(first)
    window.service.repository.save(second)
    window._display_result(first)
    window.notes_edit.setPlainText("Незаменимая заметка эксперта")
    window.conclusions_edit.setPlainText("Самостоятельный вывод")
    assert "Есть изменения" in window.notes_saved_label.text()
    with patch.object(window.service.repository, "update_evidence_notes", side_effect=sqlite3.OperationalError("disk is full")):
        assert window._save_notes() is False
        assert first.evidence.user_notes == ""
        assert "не сохранены" in window.notes_saved_label.text()
        window._display_result(second)
        assert window.current_result.evidence.id == first.evidence.id
        assert window.notes_edit.toPlainText() == "Незаменимая заметка эксперта"
        close = QCloseEvent()
        window.closeEvent(close)
        assert not close.isAccepted()
        with patch("app.gui.main_window.QFileDialog.getSaveFileName") as choose:
            window._export("json")
        choose.assert_not_called()
    assert window._save_notes() is True
    assert "не сохранены" not in window.statusBar().currentMessage()
    saved = window.service.repository.load(first.evidence.id)
    assert saved.evidence.user_notes == "Незаменимая заметка эксперта"
    assert saved.evidence.user_conclusions == "Самостоятельный вывод"
    window._display_result(second)
    assert window.current_result.evidence.id == second.evidence.id


def test_analysis_ready_does_not_write_previous_notes_into_new_file(window):
    first, second = sample_result(), sample_result()
    window.service.repository.save(first)
    window.service.repository.save(second)
    window._display_result(first)
    window.notes_edit.setPlainText("Относится только к первому файлу")
    window._analysis_ready(second)
    assert window.service.repository.load(first.evidence.id).evidence.user_notes == "Относится только к первому файлу"
    assert window.service.repository.load(second.evidence.id).evidence.user_notes == ""


@pytest.mark.parametrize("in_project", [False, True])
def test_exported_audit_contains_only_selected_evidence(window, tmp_path, in_project):
    project = ResearchProject("Другое дело", "42", "Закрытые материалы")
    window.service.create_project(project)
    result = sample_result()
    if in_project:
        result.evidence.project_id = project.id
    window.service.repository.save(result)
    repository = window.service.repository
    repository.log_event("analysis_completed", result.evidence.id, "selected", result.evidence.project_id)
    repository.log_event("report_exported", "unrelated-quick-file", "private-other-quick", None)
    repository.log_event("report_exported", "unrelated-project-file", "private-other-project", project.id)
    window._display_result(result)
    destination = tmp_path / "selected.zip"
    with patch("app.gui.main_window.QFileDialog.getSaveFileName", return_value=(str(destination), "")), patch.object(window, "_report_saved"):
        window._export("zip")
    with zipfile.ZipFile(destination) as archive:
        log = json.loads(archive.read("logs/project_audit.json"))
    assert [entry["object_id"] for entry in log] == [result.evidence.id]
    assert log[0]["result"] == "selected"


def test_duplicate_input_is_identified_and_selects_existing_job(window, tmp_path):
    source = tmp_path / "one.bin"
    source.write_bytes(b"sample")
    with patch.object(window, "start_background_processing"):
        window._start_analysis([source])
        identifier = window.queue_panel._current_job().id
        window._start_analysis([source])
    assert len(window.queue_panel.queue.list_jobs()) == 1
    assert window.queue_panel._current_job().id == identifier
    assert "Добавлено в очередь: 0" in window.queue_panel.notice.text()
    assert "Уже были в очереди: 1" in window.queue_panel.notice.text()


def test_queue_identifies_target_project_before_processing(window, tmp_path):
    first, second = ResearchProject("Первое дело", "А-1", "Файл"), ResearchProject("Второе дело", "Б-2", "Файл")
    source = tmp_path / "same.bin"
    source.write_bytes(b"sample")
    for project in (first, second):
        window.service.create_project(project)
        window.queue_panel.queue.enqueue(source, project.id)
    window.queue_panel.refresh()
    panel = window.queue_panel
    assert "Общая очередь" in panel.summary.text()
    assert {panel.table.item(row, 1).text() for row in range(2)} == {"А-1 — Первое дело", "Б-2 — Второе дело"}
    panel.table.setCurrentCell(0, 0)
    assert panel.table.item(0, 1).text() in panel.detail.toPlainText()
    with patch.object(panel, "open_result") as opened:
        panel._open()
    opened.emit.assert_not_called()


def test_table_tab_reaches_following_control(window):
    result = sample_result()
    result.findings.append(Finding("XMP", "Creator", "Test", "test"))
    window._display_result(result)
    window.tabs.setCurrentWidget(window.metadata_tabs)
    window.show()
    QApplication.processEvents()
    table = window.findings_explorer.table
    table.setFocus()
    assert QApplication.focusWidget() == table
    QTest.keyClick(table, Qt.Key.Key_Tab)
    assert QApplication.focusWidget() != table


def test_long_name_keeps_result_panes_usable_and_full_name_accessible(window):
    result = sample_result()
    result.evidence.original_name = "Очень длинное имя документа с обстоятельствами " * 4 + ".pdf"
    window._display_result(result)
    window.tabs.setCurrentWidget(window.metadata_tabs)
    window.resize(900, 700)
    window.show()
    QApplication.processEvents()
    assert window.width() == 900 and window.height() == 700
    assert window.document_banner.height() < 125
    assert window.findings_explorer.table.height() > 80
    assert window.findings_explorer.detail.height() > 80
    assert window.drop_label.toolTip() == result.evidence.original_name
    assert window.drop_label.accessibleName() == result.evidence.original_name


def test_narrow_overview_shows_selected_answer_and_keeps_selection_when_resized(window):
    result = sample_result()
    result.findings.append(Finding("OOXML", "creator", "Test", "OOXML"))
    window._display_result(result)
    window.tabs.setCurrentIndex(0)
    window.resize(900, 700)
    window.show()
    QApplication.processEvents()
    assistant = window.research_assistant
    assert assistant.question_selector.isVisible()
    assert not assistant.table.isVisible()
    assistant.question_selector.setCurrentIndex(2)
    assert assistant.table.currentRow() == 2
    assert assistant.answers[2].answer in assistant.detail.toPlainText()
    viewport = window.tabs.widget(0).viewport()
    top = assistant.detail.mapTo(viewport, assistant.detail.rect().topLeft()).y()
    assert top + 60 < viewport.height()
    window.resize(1560, 900)
    QApplication.processEvents()
    assert assistant.table.isVisible()
    assert assistant.table.currentRow() == 2


def test_empty_results_do_not_offer_disabled_reset(window):
    window.findings_explorer.populate([])
    assert "Сбросить фильтры" not in window.findings_explorer.detail.toPlainText()
    assert "Обзор" in window.findings_explorer.detail.toPlainText()


def test_file_search_explains_empty_list_and_project_switch_clears_it(window):
    result = sample_result()
    window.service.repository.save(result)
    window._refresh_files()
    window.file_search.setText("ничего_такого_нет")
    assert "Файлы не найдены" in window.file_search_status.text()
    assert "ранее открытый файл" in window.file_search_status.text()
    project = ResearchProject("Новый проект", "42", "Пример")
    window.service.create_project(project)
    window._refresh_projects(project.id)
    assert window.file_search.text() == ""


def test_expert_mark_syncs_between_views_and_rolls_back_failed_write(window):
    result = sample_result()
    window.service.repository.save(result)
    window._display_result(result)
    explorer = window.findings_explorer
    technical_mark, technical_include = window.pdf_info_table.review_controls[result.findings[0].id]
    explorer.include.setChecked(False)
    assert not technical_include.isChecked()
    technical_mark.setCurrentIndex(1)
    assert explorer.mark.currentData() == technical_mark.currentData()
    with patch.object(window.service.repository, "update_finding_mark", side_effect=sqlite3.OperationalError("read only")):
        technical_include.setChecked(True)
    assert not explorer.include.isChecked() and not technical_include.isChecked()
    assert not window.service.repository.load(result.evidence.id).findings[0].include_in_report
    technical_include.setChecked(True)
    assert explorer.include.isChecked()
    assert window.service.repository.load(result.evidence.id).findings[0].include_in_report
    assert "не сохранена" not in window.statusBar().currentMessage()


def test_sidebar_selection_opens_file_when_queue_is_active(window):
    first, second = sample_result(), sample_result()
    window.service.repository.save(first)
    window.service.repository.save(second)
    window._refresh_files()
    window._show_queue()
    window.file_list.setCurrentRow(1)
    assert window.tabs.currentIndex() == 0
    assert window.current_result.evidence.id == window.file_list.currentItem().data(Qt.ItemDataRole.UserRole)
