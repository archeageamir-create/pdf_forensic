from __future__ import annotations

import os
from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.gui.project_search import ProjectSearchDialog
from app.models import Finding, FindingLevel, FileKind, UserMark
from app.models import ResearchProject
from tests.test_persistence_reporting import sample_result
from tests.test_universal import service_at


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path, application):
    service = service_at(tmp_path / "workspace")
    window = MainWindow(service)
    yield window
    window.close()


def test_non_pdf_has_searchable_results_and_no_pdf_tabs(window):
    result = sample_result()
    result.evidence.kind = FileKind.JPEG
    result.findings = [
        Finding("GPS", "GPSLatitude", "51.1", "ExifTool/GPS"),
        Finding("EXIF", "Software", "Photo Editor", "Pillow", FindingLevel.MEDIUM),
    ]
    window._display_result(result)
    window.expert_mode.setChecked(True)
    assert not window.tabs.isTabVisible(window.tabs.indexOf(window.structure_tabs))
    assert not window.metadata_tabs.isTabVisible(
        window.metadata_tabs.indexOf(window.pdf_info_table)
    )
    explorer = window.findings_explorer
    explorer.search.setText("широта")
    assert explorer.table.rowCount() == 1
    assert "51.1" in explorer.detail.toPlainText()
    window._review_findings()
    assert explorer.table.rowCount() == 1
    assert explorer.visible_findings[0].name == "Software"


def test_overview_fact_opens_exact_source_and_queue_gives_list_space(window):
    result = sample_result()
    result.findings = [
        Finding("EXIF", "Model", "one", "Pillow"),
        Finding("EXIF", "Model", "two", "ExifTool"),
    ]
    window._display_result(result)
    window.identity_panel._open_fact(1, 0)
    explorer = window.findings_explorer
    assert explorer.visible_findings[explorer.table.currentRow()].source == "ExifTool"
    window._show_queue()
    assert window.document_banner.isHidden()
    window._show_welcome()
    assert not window.document_banner.isHidden()


def test_queue_refresh_preserves_scroll_and_does_not_rebuild_unchanged_rows(
    window, tmp_path
):
    for index in range(30):
        path = tmp_path / f"evidence-{index}.bin"
        path.write_bytes(b"test")
        window.queue_panel.queue.enqueue(path)
    window._show_queue()
    panel = window.queue_panel
    with patch.object(panel, "_update_jobs", wraps=panel._update_jobs) as update:
        panel.refresh()
        update.assert_not_called()


def test_async_project_search_opens_the_saved_finding(window, application):
    import time
    from PySide6.QtTest import QTest

    result = sample_result()
    result.findings = [Finding("EXIF", "Model", "Камера А", "Synthetic source")]
    window.service.repository.save(result)
    dialog = ProjectSearchDialog(
        window.service.config.database_path, None, "Тест", window
    )
    dialog.open_finding.connect(window._open_search_finding)
    dialog.query.setText("камера а")
    dialog._search()
    deadline = time.monotonic() + 5
    while dialog.worker is not None and time.monotonic() < deadline:
        QTest.qWait(10)
    assert dialog.worker is None and len(dialog.hits) == 1
    dialog._open()
    assert window.current_result.evidence.id == result.evidence.id
    explorer = window.findings_explorer
    assert (
        explorer.visible_findings[explorer.table.currentRow()].id
        == result.findings[0].id
    )


def test_empty_case_cannot_reveal_or_mark_previous_file(window):
    result = sample_result()
    window.service.repository.save(result)
    window._display_result(result)
    window._show_welcome()
    window._show_queue()
    assert not window.findings_explorer.findings
    assert all(
        window.tabs.isTabEnabled(i) == (window.tabs.widget(i) is window.queue_panel)
        for i in range(window.tabs.count())
    )
    with patch.object(window.service.repository, "update_finding_mark") as update:
        window._mark_changed(result.findings[0].id, UserMark.SIGNIFICANT, True)
        update.assert_not_called()


def test_notes_survive_switching_files_and_export_state(window):
    first, second = sample_result(), sample_result()
    second.evidence.id = str(uuid4())
    second.findings = []
    window.service.repository.save(first)
    window.service.repository.save(second)
    window._display_result(first)
    window.notes_edit.setPlainText("Заметка до смены файла")
    window.conclusions_edit.setPlainText("Вывод эксперта")
    window._display_result(second)
    loaded = window.service.repository.load(first.evidence.id)
    assert loaded.evidence.user_notes == "Заметка до смены файла"
    assert loaded.evidence.user_conclusions == "Вывод эксперта"
    window._display_result(loaded)
    assert window.notes_edit.toPlainText() == "Заметка до смены файла"


def test_research_guidance_opens_source_and_draft_preserves_expert_conclusion(window):
    result = sample_result()
    result.evidence.user_conclusions = "Самостоятельный вывод эксперта"
    result.evidence.user_notes = "Исходная заметка"
    finding = Finding("EXIF", "Software", "Editor", "Pillow", location="IFD0 tag 305")
    result.findings = [finding]
    window.service.repository.save(result)
    window._display_result(result)
    assistant = window.research_assistant
    row = next(i for i, a in enumerate(assistant.answers) if a.rule_id == "software")
    assistant.table.setCurrentCell(row, 0)
    assistant._open_ground()
    assert window.findings_explorer.visible_findings[window.findings_explorer.table.currentRow()].id == finding.id
    explorer = window.findings_explorer
    assert "Возможные объяснения" in explorer.detail.toPlainText()
    assert explorer.raw_detail.isHidden()
    explorer.raw_toggle.setChecked(True)
    assert not explorer.raw_detail.isHidden()
    explorer._add_observation()
    saved = window.service.repository.load(result.evidence.id)
    assert saved.evidence.user_conclusions == "Самостоятельный вывод эксперта"
    assert "Исходная заметка" in saved.evidence.user_notes
    assert finding.id in saved.evidence.user_notes
    assert "IFD0 tag 305" in saved.evidence.user_notes
    old_note = saved.evidence.user_notes
    explorer._add_observation()
    assert window.notes_edit.toPlainText() == old_note
    window._show_welcome()
    assert not assistant.answers and not window.chronology_panel.events
    assert not assistant.add_draft.isEnabled()


def test_chronology_compare_and_source_navigation(window):
    from PySide6.QtCore import QItemSelectionModel

    result = sample_result()
    first = Finding("EXIF", "DateTimeOriginal", "2026:01:02 12:00:00+05:00", "Pillow")
    second = Finding("XMP", "CreateDate", "2026-01-02T07:00:00Z", "ExifTool/XMP")
    result.findings = [first, second]
    window.service.repository.save(result)
    window._display_result(result)
    panel = window.chronology_panel
    rows = [i for i, event in enumerate(panel.events) if event.get("finding_id") in {first.id, second.id}]
    panel.table.clearSelection()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for row in rows:
        panel.table.selectionModel().select(panel.table.model().index(row, 0), flags)
    assert "одному моменту" in panel.detail.toPlainText()
    assert panel.add_note.isEnabled()
    panel._add_note()
    assert first.id in window.notes_edit.toPlainText()
    panel.table.clearSelection()
    panel.table.selectRow(rows[0])
    panel._open_source()
    assert window.findings_explorer.visible_findings[window.findings_explorer.table.currentRow()].id == first.id


def test_chronology_buttons_keep_exact_pair_and_clear_stale_comparison(window):
    result = sample_result()
    first = Finding("EXIF", "DateTimeOriginal", "2026:01:02 12:00:00+05:00", "Pillow")
    second = Finding("XMP", "CreateDate", "2026-01-02T07:00:00Z", "ExifTool/XMP")
    third = Finding("EXIF", "ModifyDate", "2026:01:03 12:00:00", "Pillow")
    result.findings = [first, second, third]
    window.service.repository.save(result)
    window._display_result(result)
    panel = window.chronology_panel
    rows = {e.get("finding_id"): i for i, e in enumerate(panel.events)}
    panel.table.selectRow(rows[first.id])
    panel.pin_date.click()
    assert not panel.compare_dates.isEnabled()
    panel.table.selectRow(rows[second.id])
    assert panel.compare_dates.isEnabled()
    assert not panel.add_note.isEnabled()
    panel.compare_dates.click()
    assert "одному моменту" in panel.detail.toPlainText()
    panel.add_note.click()
    assert first.id in window.notes_edit.toPlainText()
    assert second.id in window.notes_edit.toPlainText()
    panel.table.selectRow(rows[third.id])
    assert not panel.add_note.isEnabled()
    panel.compare_dates.click()
    assert "не вычисляются" in panel.detail.toPlainText()
    panel.reset_comparison.click()
    assert not panel.add_note.isEnabled()
    assert panel.comparison is None
    panel.pin_date.click()
    window._display_result(sample_result())
    assert panel.anchor_row is None and panel.comparison is None
    assert not panel.compare_dates.isEnabled()


def test_reset_filters_recovers_all_results_without_changing_marks(window):
    result = sample_result()
    result.findings.extend([Finding("EXIF", "Software", "Demo", "Pillow")])
    window.service.repository.save(result)
    window._display_result(result)
    explorer = window.findings_explorer
    explorer.mark.setCurrentIndex(explorer.mark.findData(UserMark.SIGNIFICANT.value))
    explorer.include.setChecked(False)
    explorer.category.setCurrentIndex(1)
    explorer.attention.setChecked(True)
    explorer.search.setText("nonexistent-value")
    assert not explorer.visible_findings
    assert explorer.reset_filters.isEnabled()
    explorer.reset_filters.click()
    assert len(explorer.visible_findings) == 2
    assert not explorer.reset_filters.isEnabled()
    saved = window.service.repository.load(result.evidence.id)
    assert saved.findings[0].user_mark == UserMark.SIGNIFICANT.value
    assert not saved.findings[0].include_in_report


def test_source_pane_reopens_after_being_collapsed(window, application):
    window._display_result(sample_result())
    window.tabs.setCurrentWidget(window.metadata_tabs)
    window.resize(1200, 900)
    window.show()
    explorer = window.findings_explorer
    application.processEvents()
    explorer.splitter.setSizes([400, 200, 0])
    explorer.raw_toggle.setChecked(True)
    application.processEvents()
    assert explorer.raw_detail.isVisible()
    assert explorer.splitter.sizes()[2] >= 80
    assert 'test-tool' in explorer.raw_detail.toPlainText()
    explorer.raw_toggle.setChecked(False)
    window.resize(900, 700)
    application.processEvents()
    assert window.height() <= 700


def test_visible_export_saves_latest_notes_and_reports_exact_path(window, tmp_path):
    import json

    result = sample_result()
    window.service.repository.save(result)
    window._display_result(result)
    assert window.save_report_button.isEnabled()
    assert window.export_actions["json"] in window.save_report_button.menu().actions()
    window.notes_edit.setPlainText("Заметка непосредственно перед сохранением")
    destination = tmp_path / "Отчёт с пробелами.json"
    with patch("app.gui.main_window.QFileDialog.getSaveFileName", return_value=(str(destination), "")), patch.object(window, "_report_saved") as saved:
        window.export_actions["json"].trigger()
        from tests.qt_helpers import wait_for_export
        wait_for_export(window)
    saved.assert_called_once_with(destination)
    assert json.loads(destination.read_text(encoding="utf-8"))["evidence"]["user_notes"] == window.notes_edit.toPlainText()
    window._show_welcome()
    assert not window.save_report_button.isEnabled()


def test_guide_opens_local_pdf_and_handles_missing_file(window, tmp_path):
    guide = tmp_path / "Руководство.pdf"
    guide.write_bytes(b"%PDF-1.4\n")
    with patch("app.gui.main_window.bundled_resource", return_value=guide), patch("app.gui.main_window.QDesktopServices.openUrl", return_value=True) as opened:
        window.user_guide_action.trigger()
        assert opened.call_args.args[0].toLocalFile() == str(guide.resolve()).replace("\\", "/")
    guide.unlink()
    with patch("app.gui.main_window.bundled_resource", return_value=guide), patch("app.gui.main_window.QDesktopServices.openUrl") as opened, patch("app.gui.main_window.QMessageBox.information") as notice:
        window.user_guide_action.trigger()
    opened.assert_not_called()
    assert "Руководство не найдено" in notice.call_args.args


def test_settings_apply_to_future_queue_jobs(window):
    config = replace(
        window.service.config,
        ffprobe_command="custom-ffprobe",
        max_analysis_seconds=180,
    )
    with patch("app.gui.main_window.SettingsDialog") as dialog:
        dialog.return_value.exec.return_value = True
        dialog.return_value.value.return_value = config
        window._settings()
    assert window.queue_panel.daemon.service is window.service
    assert window.queue_panel.daemon.service.config.ffprobe_command == "custom-ffprobe"


def test_queue_adds_more_files_without_disabling_input(window, tmp_path):
    files = []
    for name in ("one.bin", "two.bin"):
        path = tmp_path / name
        path.write_bytes(b"synthetic")
        files.append(path)
    with patch.object(window, "start_background_processing"):
        window._start_analysis(files[:1])
        window._start_analysis(files[1:])
    assert len(window.queue_panel.queue.list_jobs()) == 2
    assert window.add_action.isEnabled()


def test_expert_mark_and_inclusion_are_saved(window):
    result = sample_result()
    window.service.repository.save(result)
    window._display_result(result)
    explorer = window.findings_explorer
    finding = explorer.visible_findings[0]
    explorer.mark.setCurrentIndex(explorer.mark.findData(UserMark.SIGNIFICANT.value))
    explorer.include.setChecked(False)
    saved = window.service.repository.load(result.evidence.id)
    mark = next(f for f in saved.findings if f.id == finding.id)
    assert mark.user_mark == UserMark.SIGNIFICANT.value
    assert mark.include_in_report is False


def test_quick_research_does_not_mix_other_projects(window):
    project = ResearchProject("Дело", "42", "Тест")
    window.service.create_project(project)
    assigned = sample_result()
    assigned.evidence.project_id = project.id
    window.service.repository.save(assigned)
    unassigned = sample_result()
    unassigned.evidence.id = str(uuid4())
    unassigned.findings = []
    window.service.repository.save(unassigned)
    rows = window.service.repository.list_evidence_summaries(None)
    assert [row["id"] for row in rows] == [unassigned.evidence.id]
    assert (
        window.service.repository.list_evidence_summaries(project.id)[0]["id"]
        == assigned.evidence.id
    )


def test_file_list_does_not_load_every_analysis(window):
    for _ in range(12):
        result = sample_result()
        result.findings = []
        result.evidence.id = str(uuid4())
        result.artifacts = {"large_content": "x" * 100_000}
        window.service.repository.save(result)
    with patch.object(
        window.service.repository, "load", wraps=window.service.repository.load
    ) as load:
        window._refresh_files()
    assert load.call_count <= 1
    assert window.file_list.count() == 12
