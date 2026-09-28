from __future__ import annotations

import json
import zipfile

import pytest

from app.models import FileKind, Finding, UserMark
from app.reporting import (
    DocxReportExporter,
    HtmlReportExporter,
    JsonReportExporter,
    ZipPackageExporter,
)
from app.reporting.safety import atomic_report_path
from tests.test_persistence_reporting import sample_result


def test_zip_temporary_name_does_not_overwrite_evidence(tmp_path):
    original = tmp_path / "report.zip.tmp"
    original.write_bytes(b"original evidence beside report")
    result = sample_result()
    result.evidence.original_path = str(original)
    ZipPackageExporter().export(result, tmp_path / "report.zip")
    assert original.read_bytes() == b"original evidence beside report"
    assert zipfile.is_zipfile(tmp_path / "report.zip")


def test_failed_export_keeps_previous_report_and_cleans_temporary(tmp_path):
    destination = tmp_path / "report.json"
    destination.write_text("previous report", encoding="utf-8")
    with pytest.raises(RuntimeError):
        with atomic_report_path(sample_result(), destination) as temporary:
            temporary.write_text("incomplete", encoding="utf-8")
            raise RuntimeError("simulated export failure")
    assert destination.read_text(encoding="utf-8") == "previous report"
    assert list(tmp_path.iterdir()) == [destination]


def test_docx_escapes_controls_and_marks_truncation_while_json_keeps_value(tmp_path):
    result = sample_result()
    result.evidence.kind = FileKind.DOCX
    result.evidence.user_notes = "Заметка\x00с данными"
    result.findings = [
        Finding(
            "EXIF",
            "Software",
            "a\x01" + "b" * 6100,
            "test\x02",
            location="IFD0/tag\x03",
            user_mark=UserMark.SIGNIFICANT,
        )
    ]
    result.artifacts["analysis_scope"] = {
        "coverage": "Метаданные и сохранённые исправления."
    }
    output = tmp_path / "report.docx"
    DocxReportExporter().export(result, output)
    with zipfile.ZipFile(output) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "\\x00" in xml and "\\x01" in xml and "\\x02" in xml and "\\x03" in xml
    assert "Сокращено:" in xml and "существенно" in xml
    JsonReportExporter().export(result, tmp_path / "report.json")
    raw = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert raw["findings"][0]["value"] == result.findings[0].value


def test_html_report_keeps_source_location_scope_and_escaped_notes():
    result = sample_result()
    result.evidence.kind = FileKind.JPEG
    result.evidence.user_notes = '<script>alert("test")</script>\nline two'
    result.artifacts = {
        "analysis_scope": {"coverage": "Только свойства изображения"},
        "timeline": [
            {
                "raw": "2026-01-01",
                "normalized": "2026-01-01T00:00:00",
                "source": "test",
                "name": "date",
                "timezone_present": False,
            }
        ],
    }
    result.findings = [
        Finding(
            "EXIF",
            "Software",
            "Editor",
            "Pillow",
            location="IFD0 tag 305",
            user_mark=UserMark.EXPLAINED,
        )
    ]
    output = HtmlReportExporter().render(result)
    assert "IFD0 tag 305" in output and "Только свойства изображения" in output
    assert "Часовой пояс не указан" in output and "объяснено" in output
    assert "Авторство и история правок PDF" not in output
    assert "<script>" not in output and "&lt;script&gt;" in output


def test_timeline_reports_keep_offset_provenance_and_do_not_reuse_old_false_precision(tmp_path):
    result = sample_result()
    result.artifacts["timeline"] = [
        {"raw": "D:2026Z", "normalized": "2026-01-01T00:00:00+00:00", "name": "CreationDate", "source": "PDF"},
        {"raw": "2026:01:02 12:00:00", "comparison_raw": "2026:01:02 12:00:00+05:00",
         "source": "ExifTool/ExifIFD", "scope": "embedded_metadata", "name": "DateTimeOriginal",
         "timezone_field": "OffsetTimeOriginal", "timezone_value": "+05:00", "timezone_finding_id": "offset-id",
         "finding_id": "date-id"},
    ]
    html = HtmlReportExporter().render(result)
    path = tmp_path / "timeline.docx"
    DocxReportExporter().export(result, path)
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    for text in (html, xml):
        assert "Неполная точность" in text
        assert "2026-01-01T00:00:00+00:00" not in text
        assert "OffsetTimeOriginal" in text and "offset-id" in text and "date-id" in text
