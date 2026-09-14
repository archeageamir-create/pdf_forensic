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
