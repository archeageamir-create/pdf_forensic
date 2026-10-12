from __future__ import annotations

import json

import pytest

from app.analyzers.chronology_guidance import compare_events, event_guidance
from app.analyzers.interpretation import (
    AnswerStatus,
    InterpretationBuilder,
    draft_text,
    working_copy_verified,
)
from app.analyzers.metadata import MetadataConflictDetector
from app.analyzers.overview import original_integrity_label
from app.analyzers.research_guidance import explain_finding, observation_draft
from app.analyzers.timeline import TimelineBuilder, normalize_date
from app.models import FileKind, Finding, IntegrityStatus, ToolRunStatus
from tests.test_persistence_reporting import sample_result


def answers(result):
    return {a.rule_id: a for a in InterpretationBuilder().build(result)}


def test_recorded_author_never_identifies_person_and_retains_duplicate_sources():
    result = sample_result()
    result.findings = [
        Finding("PDF Info", "Author", "А. А.", "one"),
        Finding("PDF Info", "Author", "А. А.", "two"),
    ]
    answer = answers(result)["authorship"]
    assert answer.status == AnswerStatus.INSUFFICIENT
    assert set(answer.finding_ids) == {f.id for f in result.findings}
    assert "не идентифиц" in explain_finding(result.findings[0]).meaning
    assert "не представляется возможным" not in answer.draft
    assert "ст. 39" in draft_text(answer, result)
    assert "ст. 40" in draft_text(answer, result)


def test_pdf_creator_is_software_but_ooxml_creator_is_declared_person():
    result = sample_result()
    producer = Finding("PDF Info", "Creator", "Word", "pdf")
    author = Finding("OOXML Core Properties", "creator", "Лицо", "office")
    result.findings = [producer, author]
    rows = answers(result)
    assert rows["software"].finding_ids == (producer.id,)
    assert rows["authorship"].finding_ids == (author.id,)


@pytest.mark.parametrize(
    "status",
    [
        ToolRunStatus.FAILED,
        ToolRunStatus.UNAVAILABLE,
        ToolRunStatus.TIMED_OUT,
        ToolRunStatus.CANCELLED,
    ],
)
def test_unfinished_method_is_not_absence_or_npv(status):
    result = sample_result()
    result.tool_runs[0].status = status
    result.incomplete = False  # Also protect legacy inconsistent records.
    assert answers(result)["software"].status == AnswerStatus.NOT_CHECKED
    assert "НПВ" not in answers(result)["software"].draft
    assert "не завершена" in draft_text(answers(result)["software"], result)


def test_missing_method_does_not_erase_a_readable_positive_observation():
    result = sample_result()
    result.tool_runs[0].status = ToolRunStatus.UNAVAILABLE
    result.findings.append(Finding("EXIF", "Software", "Editor", "Pillow"))
    assert answers(result)["software"].status == AnswerStatus.INDICATION


def test_filesystem_copy_dates_and_custom_fields_are_not_embedded_authorship():
    result = sample_result()
    result.findings = [
        Finding(
            "File properties",
            "FileCreateDate",
            "2026-01-01T00:00:00Z",
            "ExifTool/System",
        ),
        Finding("OOXML Custom Properties", "Author", "Custom", "OOXML"),
    ]
    assert not answers(result)["authorship"].finding_ids
    assert not answers(result)["event_time"].finding_ids
    assert explain_finding(result.findings[0]).rule == "working-copy-filesystem"


def test_integrity_requires_real_matching_hashes_and_original_recheck():
    result = sample_result()
    result.findings = [
        Finding("Integrity", "Original hash unchanged during analysis", True, "SHA-256")
    ]
    assert answers(result)["integrity"].status == AnswerStatus.FACT
    result.evidence.working_copy_sha256 = ""
    assert not working_copy_verified(result)
    assert answers(result)["integrity"].status == AnswerStatus.NOT_CHECKED
    result.evidence.working_copy_sha256 = result.evidence.sha256
    result.findings[0].value = False
    assert answers(result)["integrity"].status == AnswerStatus.NOT_CHECKED
    assert (
        "Ошибка повторного чтения не доказывает"
        in answers(result)["integrity"].limitation
    )
    result.evidence.integrity_status = IntegrityStatus.CHANGED
    assert not working_copy_verified(result)


def test_unknown_format_is_not_a_positive_identification():
    result = sample_result()
    result.evidence.kind = FileKind.BINARY
    result.findings = [
        Finding("Integrity", "Signature format", "BINARY", "File signature")
    ]
    assert answers(result)["format"].status == AnswerStatus.NOT_CHECKED


def test_zero_gps_is_present_but_gps_version_is_not_a_location():
    result = sample_result()
    result.evidence.kind = FileKind.JPEG
    result.findings = [Finding("GPS", "GPSVersionID", "2.3", "Pillow/GPS")]
    assert answers(result)["location"].status != AnswerStatus.INDICATION
    result.findings.append(Finding("GPS", "GPSLatitude", 0, "Pillow/GPS"))
    assert answers(result)["location"].status == AnswerStatus.INDICATION
    assert "неполная пара" in answers(result)["location"].limitation


def test_no_tracked_changes_means_scoped_negative_not_no_editing():
    result = sample_result()
    result.evidence.kind = FileKind.DOCX
    result.findings = [
        Finding("Word review", "Tracked changes count", 0, "Built-in OOXML analyzer")
    ]
    answer = answers(result)["word_changes"]
    assert answer.status == AnswerStatus.FACT
    assert "нельзя исключить редактирование" in answer.draft


def test_snapshot_survives_json_and_keeps_source_ids():
    result = sample_result()
    result.findings.append(
        Finding("EXIF", "Software", "x", "Pillow", include_in_report=False)
    )
    snap = InterpretationBuilder().snapshot(result)
    assert json.loads(json.dumps(snap)) == snap
    draft = draft_text(answers(result)["software"], result)
    assert result.findings[-1].id in draft
    assert "исключено пользователем" in draft


@pytest.mark.parametrize(
    "name,category,rule",
    [
        ("Software", "EXIF", "software"),
        ("Incremental updates", "PDF structure", "pdf-revisions"),
        ("Signature count", "PDF signatures", "signature"),
        ("Macro parts", "OOXML structure", "active-content"),
        ("Hidden worksheets", "Excel workbook", "hidden-linked-content"),
        ("DocumentID", "XMP", "lineage"),
        ("ExposureTime", "EXIF", "capture-settings"),
        ("Image width", "Image properties", "image-representation"),
        ("codec_name", "Media metadata", "media-stream"),
        ("UNKNOWN_VENDOR_FIELD", "EXIF", "technical-field"),
    ],
)
def test_field_guidance_is_scoped_and_actionable(name, category, rule):
    finding = Finding(category, name, "example", "reader")
    guide = explain_finding(finding)
    assert guide.rule == rule
    assert guide.meaning and guide.attention and guide.alternatives and guide.check
    assert finding.id in observation_draft(finding)
    if rule == "technical-field":
        assert "пока не описано" in guide.meaning


@pytest.mark.parametrize(
    "raw,precision",
    [
        ("D:2026Z", "year"),
        ("D:202601Z", "month"),
        ("D:20260102Z", "day"),
        ("D:2026010212Z", "hour"),
        ("D:202601021230Z", "minute"),
        ("2026-01-02T12:30Z", "minute"),
        ("2026-01-02", "day"),
    ],
)
def test_partial_date_never_invents_exact_midnight(raw, precision):
    date = normalize_date(raw)
    assert date["parsed"] and date["precision"] == precision
    assert date["timestamp"] is None
    assert date["normalized"] == raw


def test_equivalent_timezones_compare_as_same_moment_and_not_conflict():
    a = {"name": "CreationDate", "raw": "D:20260102120000+05'00'", "source": "A"}
    b = {"name": "CreateDate", "raw": "2026-01-02T07:00:00Z", "source": "B"}
    assert "одному моменту" in compare_events(a, b)
    findings = [
        Finding("PDF Info", a["name"], a["raw"], a["source"]),
        Finding("XMP", b["name"], b["raw"], b["source"]),
    ]
    MetadataConflictDetector().mark(findings)
    assert not any(f.conflict for f in findings)


def test_unknown_timezone_does_not_produce_interval_or_local_assumption():
    a = {"raw": "2026-01-02T12:00:00", "name": "created", "source": "A"}
    b = {"raw": "2026-01-02T12:00:00Z", "name": "modified", "source": "B"}
    comparison = compare_events(a, b)
    assert "не вычисляются" in comparison and "неизвестен пояс" in comparison
    assert "Казахстан или UTC автоматически не подставляются" in event_guidance(a)


def test_timeline_links_dates_and_nested_comments_and_separates_file_systems():
    result = sample_result()
    date = Finding(
        "XMP",
        "CreateDate",
        "2026-01-02T07:00:00Z",
        "ExifTool/XMP",
        location="xmp:CreateDate",
    )
    copy = Finding("File properties", "FileCreateDate", date.value, "ExifTool/System")
    comments = Finding(
        "Word review",
        "Tracked changes",
        [{"date": date.value, "part": "word/document.xml"}],
        "OOXML",
    )
    result.findings = [date, copy, comments]
    events = TimelineBuilder().build(result.evidence, result.findings)
    by_id = {e.get("finding_id"): e for e in events}
    assert by_id[date.id]["location"] == "xmp:CreateDate"
    assert by_id[copy.id]["scope"] == "working_copy_filesystem"
    assert by_id[comments.id]["location"] == "word/document.xml"
    assert any(e["scope"] == "analysis" for e in events)


def test_timeline_difference_is_not_duration_of_actions():
    a = {"raw": "2026-01-02T07:00:00Z"}
    b = {"raw": "2026-01-02T08:00:00Z"}
    text = compare_events(a, b)
    assert "3600 с" in text
    assert "не доказанная длительность" in text


def test_separate_exif_offset_preserves_both_sources_and_raw_date():
    result = sample_result()
    date = Finding(
        "EXIF", "DateTimeOriginal", "2026:01:02 12:00:00", "ExifTool/ExifIFD"
    )
    offset = Finding("EXIF", "OffsetTimeOriginal", "+05:00", "ExifTool/ExifIFD")
    result.findings = [date, offset]
    event = next(
        e
        for e in TimelineBuilder().build(result.evidence, result.findings)
        if e.get("finding_id") == date.id
    )
    assert event["raw"] == date.value
    assert event["timezone_finding_id"] == offset.id
    assert "одному моменту" in compare_events(event, {"raw": "2026-01-02T07:00:00Z"})
    assert offset.id in event_guidance(event)
    offset.source = "Other reader"
    event = next(
        e
        for e in TimelineBuilder().build(result.evidence, result.findings)
        if e.get("finding_id") == date.id
    )
    assert event["timestamp"] is None


def test_ambiguous_exif_offset_is_not_guessed():
    result = sample_result()
    date = Finding("EXIF", "DateTimeOriginal", "2026:01:02 12:00:00", "Pillow/EXIF")
    result.findings = [
        date,
        Finding("EXIF", "OffsetTimeOriginal", "+05:00", date.source),
        Finding("EXIF", "OffsetTimeOriginal", "+06:00", date.source),
    ]
    event = next(
        e
        for e in TimelineBuilder().build(result.evidence, result.findings)
        if e.get("finding_id") == date.id
    )
    assert event["timestamp"] is None


@pytest.mark.parametrize(
    "raw",
    [
        "D:20260102120000+05'99'",
        "2026:01:02 12:00:00+05:99",
        "2026-01-02T12:00:00+05:99",
    ],
)
def test_invalid_offset_never_becomes_a_comparable_timestamp(raw):
    value = normalize_date(raw)
    assert not value["parsed"]
    assert value.get("timestamp") is None


def test_custom_property_cannot_impersonate_integrity_recheck():
    result = sample_result()
    result.findings = [Finding("OOXML Custom Properties", "Original hash unchanged during analysis", True, "Built-in OOXML analyzer")]
    assert "не записана" in original_integrity_label(result)
    result.findings.append(Finding("Integrity", "Original hash unchanged during analysis", False, "SHA-256"))
    assert "не подтверждена" in original_integrity_label(result)
