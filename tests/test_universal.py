from __future__ import annotations

import json
import os
import shutil
import sys
import wave
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from app.adapters.base import CommandRunner
from app.adapters.exiftool import ExifToolAdapter
from app.adapters.ffprobe import FfprobeAdapter
from app.analyzers.analytics import FileComparator
from app.analyzers.overview import needs_attention, original_integrity_label
from app.analyzers.metadata import MetadataConflictDetector
from app.analyzers.timeline import TimelineBuilder, normalize_date
from app.analyzers.pptx import OoxmlLimits
from app.analyzers.universal import (
    ArchiveAnalyzer,
    OfficeAnalyzer,
    json_value,
)
from app.core.config import AppConfig
from app.core.errors import AnalysisError
from app.core.formats import PROFILES, detect_file_kind, extension_matches
from app.core.service import ForensicsService
from app.models import AnalysisMode, FileKind, Finding, FindingLevel, ToolRunStatus
from app.reporting import (
    HtmlReportExporter,
    JsonReportExporter,
    DocxReportExporter,
    ZipPackageExporter,
)
from tests.test_persistence_reporting import sample_result


def service_at(root: Path) -> ForensicsService:
    return ForensicsService(
        AppConfig(
            data_dir=root,
            database_path=root / "db.sqlite3",
            cases_dir=root / "cases",
            reports_dir=root / "reports",
            exiftool_command="definitely-unavailable-exiftool",
            validate_signatures=False,
            create_qdf_in_full_mode=False,
        )
    )


def test_repeated_exiftool_tags_are_not_overwritten():
    findings = ExifToolAdapter._parse_json(
        '[{"IFD0:Software":"first", "IFD0:Software":"second", "GPS:Coordinates":[1,2], "XMP:Nested":{"A":1,"A":2}}]'
    )
    software = [item for item in findings if item.name == "Software"]
    assert [item.value for item in software] == ["first", "second"]
    assert len({item.location for item in software}) == 2
    assert findings[2].value == [1, 2]
    assert findings[3].value == {
        "json_object_pairs": [{"key": "A", "value": 1}, {"key": "A", "value": 2}]
    }


def test_runner_transmits_utf8_input_without_shell_or_console_encoding():
    payload = "C:/Исследование/照片/снимок.jpg\n".encode("utf-8")
    run = CommandRunner().run("stdin-test", [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"], input_bytes=payload)
    assert run.status == ToolRunStatus.COMPLETED
    assert run.stdout == payload.decode("utf-8")


@pytest.mark.skipif(os.name != "nt" or not shutil.which("exiftool"), reason="Real Windows ExifTool integration")
def test_exiftool_preserves_international_filename(tmp_path):
    path = tmp_path / "Снимок_照片_😀.jpg"
    Image.new("RGB", (10, 10), "white").save(path)
    result = ExifToolAdapter().analyze(path)
    assert result.tool_runs[0].status == ToolRunStatus.COMPLETED
    filename = next(f for f in result.findings if f.name == "FileName")
    assert filename.value == path.name
    assert "FileName encoding must be specified" not in result.tool_runs[0].stdout
    assert result.tool_runs[0].parsed_result["stdin_utf8"] == path.resolve().as_posix() + "\n"


def test_mixed_known_and_unknown_timezone_does_not_assert_date_order():
    findings = [
        Finding("EXIF", "CreateDate", "2026-01-01T12:00:00+05:00", "same source"),
        Finding("EXIF", "ModifyDate", "2026-01-01T06:00:00", "same source"),
    ]
    MetadataConflictDetector().mark(findings)
    assert not any(
        f.name == "Modification date precedes creation date" for f in findings
    )
    assert any(f.name == "Mixed timezone presence" for f in findings)


def test_timeline_excludes_durations_and_does_not_assign_unknown_timezone():
    evidence = sample_result().evidence
    findings = [
        Finding("EXIF", "ExposureTime", "1/125", "ExifTool"),
        Finding("Media streams", "duration_time", "03:20:00", "ffprobe"),
        Finding("OOXML Extended Properties", "TotalTime", 120, "OOXML"),
        Finding("OOXML Extended Properties", "LinksUpToDate", "false", "OOXML"),
        Finding("OOXML Core Properties", "LastModifiedBy", "Editor", "OOXML"),
        Finding("Other", "Update", "yes", "Other"),
        Finding("EXIF", "DateTimeOriginal", "2026:02:03 12:34:56", "ExifTool"),
        Finding("Media metadata", "creation_time", "2026-02-03T10:00:00Z", "ffprobe"),
        Finding("XMP", "ModifyDate", "invalid declared date", "ExifTool"),
    ]
    events = TimelineBuilder().build(evidence, findings)
    names = {event["name"] for event in events}
    assert not names & {"ExposureTime", "duration_time", "TotalTime", "LinksUpToDate", "LastModifiedBy", "Update"}
    assert {"DateTimeOriginal", "creation_time", "ModifyDate"} <= names
    unknown = next(e for e in events if e["name"] == "DateTimeOriginal")
    assert unknown["parsed"] and unknown["timestamp"] is None
    assert unknown["normalized"] == "2026-02-03T12:34:56"
    assert normalize_date("2026-02-03T10:00:00Z")["timestamp"] is not None
    assert next(e for e in events if e["name"] == "ModifyDate")["parsed"] is False


def test_comparison_retains_repeated_fields_at_distinct_locations():
    left, right = sample_result(), sample_result()
    left.findings = [
        Finding("EXIF", "Model", "one", "Pillow", location="IFD0"),
        Finding("EXIF", "Model", "two", "Pillow", location="IFD1"),
    ]
    right.findings = [
        Finding("EXIF", "Model", "changed", "Pillow", location="IFD0"),
        Finding("EXIF", "Model", "two", "Pillow", location="IFD1"),
    ]
    compared = FileComparator().compare(left, right)
    assert any(
        item["field"].endswith("[IFD0]") and item["status"] == "changed"
        for item in compared.items
    )
    assert any(
        item["field"].endswith("[IFD1]") and item["status"] == "same"
        for item in compared.items
    )


def test_exif_rational_keeps_numerator_and_denominator():
    assert json_value(IFDRational(1, 3)) == {
        "type": "rational",
        "numerator": 1,
        "denominator": 3,
        "display": str(IFDRational(1, 3)),
    }


def write_word(path: Path, extra: dict[str, str | bytes] | None = None):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        parts = {
            "[Content_Types].xml": "<Types/>",
            "docProps/core.xml": '<p xmlns:d="urn:d"><d:creator>Тестовый автор</d:creator><d:created>2026-02-01T12:00:00Z</d:created></p>',
            "word/document.xml": '<w:document xmlns:w="urn:w"><w:body><w:ins w:author="Редактор" w:date="2026-02-02T12:00:00Z"><w:r><w:t>Изменение</w:t></w:r></w:ins></w:body></w:document>',
            "word/comments.xml": '<w:comments xmlns:w="urn:w"><w:comment w:author="Эксперт" w:date="2026-02-03T12:00:00Z"><w:p><w:r><w:t>Проверить</w:t></w:r></w:p></w:comment></w:comments>',
            "word/_rels/document.xml.rels": '<Relationships><Relationship Id="r1" Target="https://example.invalid" TargetMode="External"/></Relationships>',
        }
        parts.update(extra or {})
        for name, value in parts.items():
            archive.writestr(name, value)


@pytest.mark.parametrize(
    "header,kind",
    [
        (b"\xff\xd8\xff", FileKind.JPEG),
        (b"\x89PNG\r\n\x1a\n", FileKind.PNG),
        (b"II*\0", FileKind.TIFF),
        (b"GIF89a", FileKind.GIF),
        (b"RIFF\x00\x00\x00\x00WEBP", FileKind.WEBP),
        (b"BM", FileKind.BMP),
        (b"\x00\x00\x00\x18ftypisom", FileKind.MP4),
        (b"\x00\x00\x00\x18ftypqt  ", FileKind.MOV),
        (b"RIFF\x00\x00\x00\x00WAVE", FileKind.WAV),
        (b"ID3", FileKind.MP3),
        (b"fLaC", FileKind.FLAC),
        (b"OggS", FileKind.OGG),
        (b"\x1aE\xdf\xa3", FileKind.MKV),
        (b"RIFF\x00\x00\x00\x00AVI ", FileKind.AVI),
        (b"\x00\x00\x00\x18ftypavif", FileKind.BINARY),
        (b"this is not a PDF", FileKind.BINARY),
    ],
)
def test_content_routes_even_with_false_extension(tmp_path, header, kind):
    path = tmp_path / "ложное-имя.pdf"
    path.write_bytes(header)
    assert detect_file_kind(path) == kind


def test_all_file_kinds_have_profiles():
    assert set(PROFILES) == set(FileKind)
    assert extension_matches(".JPG", FileKind.JPEG)
    assert extension_matches(".tif", FileKind.TIFF)
    assert extension_matches(".docm", FileKind.DOCX)
    assert extension_matches(".pdf", FileKind.JPEG) is False
    assert extension_matches(".pdf", FileKind.BINARY) is None


def test_image_exif_and_original_immutability_round_trip(tmp_path):
    path = tmp_path / "фотография.pdf"
    exif = Image.Exif()
    exif[271] = "Synthetic Camera"
    exif[305] = "Test Editor"
    exif[306] = "2026:02:01 12:00:00"
    Image.new("RGB", (40, 30), "#667788").save(path, format="JPEG", exif=exif)
    original = path.read_bytes()
    service = service_at(tmp_path / "workspace")
    result = service.analyze_file(path, mode=AnalysisMode.CUSTOM)
    values = {f.name: f.value for f in result.findings}
    assert result.evidence.kind == FileKind.JPEG
    assert values["Make"] == "Synthetic Camera"
    assert values["Image width"] == 40
    assert values["Extension matches signature"] is False
    assert not result.errors
    assert path.read_bytes() == original
    assert Path(result.evidence.working_copy_path).suffix == ".jpg"
    assert service.repository.load(result.evidence.id).to_dict() == result.to_dict()
    assert any(event["name"] == "DateTime" for event in result.artifacts["timeline"])
    for exporter, suffix in (
        (JsonReportExporter(), "json"),
        (HtmlReportExporter(), "html"),
        (DocxReportExporter(), "docx"),
        (ZipPackageExporter(), "zip"),
    ):
        destination = tmp_path / f"report.{suffix}"
        exporter.export(result, destination)
        assert destination.stat().st_size > 0


def test_word_changes_comments_macros_links(tmp_path):
    path = tmp_path / "document.bin"
    write_word(
        path,
        {
            "word/vbaProject.bin": b"test-only-not-code",
            "word/embeddings/test.bin": b"test",
        },
    )
    assert detect_file_kind(path) == FileKind.DOCX
    result = service_at(tmp_path / "workspace").analyze_file(
        path, mode=AnalysisMode.CUSTOM
    )
    values = {f.name: f.value for f in result.findings}
    assert not result.errors
    assert values["creator"] == "Тестовый автор"
    assert values["Tracked changes count"] == 1
    assert values["Word comments"][0]["text"] == "Проверить"
    assert values["Macro parts"] == ["word/vbaProject.bin"]
    assert values["External relationships"][0]["Target"] == "https://example.invalid"
    assert (
        len(
            [
                e
                for e in result.artifacts["timeline"]
                if e.get("raw") == "2026-02-02T12:00:00Z"
            ]
        )
        == 1
    )


def test_excel_hidden_sheets(tmp_path):
    path = tmp_path / "book.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "xl/workbook.xml",
            '<workbook><sheets><sheet name="Отчёт" sheetId="1"/><sheet name="Скрытый" sheetId="2" state="veryHidden"/></sheets></workbook>',
        )
    assert detect_file_kind(path) == FileKind.XLSX
    findings = OfficeAnalyzer().analyze(path, FileKind.XLSX).findings
    hidden = next(f for f in findings if f.name == "Hidden worksheets")
    assert hidden.value[0]["name"] == "Скрытый"
    assert hidden.level == FindingLevel.MANUAL_REVIEW


def test_archive_unsafe_path_is_observed_without_extraction(tmp_path):
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../outside.txt", "example")
        archive.writestr("нормальный.txt", "данные")
    values = {
        f.name: f.value for f in ArchiveAnalyzer(OoxmlLimits()).analyze(path).findings
    }
    assert values["Unsafe archive paths"] == ["../outside.txt"]
    assert not (tmp_path.parent / "outside.txt").exists()
    assert values["ZIP entries"] == 2
    with pytest.raises(AnalysisError):
        ArchiveAnalyzer(OoxmlLimits(max_entries=1)).analyze(path)


def test_office_unsafe_paths_and_xml_limits_are_rejected(tmp_path):
    path = tmp_path / "bad.docx"
    write_word(path, {"../outside.txt": "x"})
    with pytest.raises(AnalysisError, match="Unsafe"):
        OfficeAnalyzer().analyze(path, FileKind.DOCX)
    write_word(path)
    with pytest.raises(AnalysisError, match="limit"):
        OfficeAnalyzer(OoxmlLimits(max_xml_part_bytes=2)).analyze(path, FileKind.DOCX)


def test_unknown_files_are_explicitly_basic(tmp_path):
    path = tmp_path / "unknown.xyz"
    path.write_bytes(b"unrecognized specimen")
    result = service_at(tmp_path / "workspace").analyze_file(
        path, mode=AnalysisMode.CUSTOM
    )
    assert result.evidence.kind == FileKind.BINARY
    assert "Базовый анализ" in result.artifacts["analysis_scope"]["coverage"]
    assert not result.errors
    assert all(not f.source.startswith("Built-in OOXML") for f in result.findings)


def test_exif_gps_separated_and_software_preserved():
    output = json.dumps(
        [
            {
                "IFD0:Make": "camera",
                "GPS:GPSLatitude": 51.1,
                "Composite:GPSPosition": "51.1 71.2",
            }
        ]
    )
    findings = ExifToolAdapter._parse_json(output)
    assert [f.category for f in findings] == ["EXIF", "GPS", "GPS"]


def test_non_pdf_comparison_and_attention():
    left, right = sample_result(), sample_result()
    left.findings = [
        Finding("EXIF", "Model", "A", "Pillow"),
        Finding("File properties", "FileModifyDate", "today", "ExifTool/System"),
    ]
    right.findings = [
        Finding("EXIF", "Model", "B", "Pillow"),
        Finding("File properties", "FileModifyDate", "tomorrow", "ExifTool/System"),
    ]
    compared = FileComparator().compare(left, right)
    assert any(
        item["field"] == "EXIF/Model/Pillow" and item["status"] == "changed"
        for item in compared.items
    )
    assert not any("FileModifyDate" in item["field"] for item in compared.items)
    assert needs_attention(Finding("x", "x", 1, "x", FindingLevel.MEDIUM))
    assert "не записана" in original_integrity_label(left)


@pytest.mark.skipif(not shutil.which("ffprobe"), reason="ffprobe is optional")
def test_real_ffprobe_on_generated_wave(tmp_path):
    path = tmp_path / "синтетический.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\0\0" * 800)
    result = FfprobeAdapter(FileKind.WAV, timeout_seconds=10).analyze(path)
    assert result.tool_runs[0].status == ToolRunStatus.COMPLETED
    assert result.artifacts["media_probe"]["streams"][0]["sample_rate"] == "8000"
    assert "-protocol_whitelist" in result.tool_runs[0].command


def test_ffprobe_missing_is_reported(tmp_path):
    result = FfprobeAdapter(FileKind.WAV, command="definitely-missing-ffprobe").analyze(
        tmp_path / "audio.wav"
    )
    assert result.tool_runs[0].status == ToolRunStatus.UNAVAILABLE


def test_version_reader_handles_silent_tool():
    import subprocess

    with patch(
        "app.adapters.base.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, "", ""),
    ):
        with patch.object(CommandRunner, "_missing_component", return_value=None):
            assert CommandRunner()._read_version(["tool"]) == "unknown"


@pytest.mark.parametrize(
    "exporter",
    [
        JsonReportExporter(),
        HtmlReportExporter(),
        DocxReportExporter(),
        ZipPackageExporter(),
    ],
)
def test_export_cannot_overwrite_original_or_working_copy(tmp_path, exporter):
    source = tmp_path / "source.bin"
    source.write_bytes(b"synthetic original")
    result = service_at(tmp_path / "workspace").analyze_file(
        source, mode=AnalysisMode.CUSTOM
    )
    for target in (source, Path(result.evidence.working_copy_path)):
        with pytest.raises(ValueError, match="заменить оригинал"):
            exporter.export(result, target)
    assert source.read_bytes() == b"synthetic original"


def test_export_rejects_hard_link_alias(tmp_path):
    import os

    source = tmp_path / "source.bin"
    source.write_bytes(b"synthetic original")
    alias = tmp_path / "report.json"
    try:
        os.link(source, alias)
    except OSError:
        pytest.skip("hard links unavailable")
    result = service_at(tmp_path / "workspace").analyze_file(
        source, mode=AnalysisMode.CUSTOM
    )
    with pytest.raises(ValueError):
        JsonReportExporter().export(result, alias)
    assert source.read_bytes() == b"synthetic original"


def test_invalid_exiftool_output_marks_run_failed(tmp_path):
    from app.models import ToolRun

    run = ToolRun("ExifTool", [], "test", "[]", "", 0, ToolRunStatus.COMPLETED, "", "")
    adapter = ExifToolAdapter()
    with patch.object(adapter.runner, "run", return_value=run):
        result = adapter.analyze(tmp_path / "test.bin")
    assert result.tool_runs[0].status == ToolRunStatus.FAILED
    assert result.findings[0].category == "Tool diagnostics"
