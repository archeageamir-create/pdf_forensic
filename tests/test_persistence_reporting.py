from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.core.database import AnalysisRepository
from app.models import (
    AnalysisResult,
    EvidenceFile,
    FileKind,
    Finding,
    ResearchProject,
    ToolRun,
    ToolRunStatus,
)
from app.reporting import HtmlReportExporter, JsonReportExporter
from app.analyzers.analytics import SummaryBuilder


def sample_result() -> AnalysisResult:
    evidence = EvidenceFile(
        original_path="C:/evidence/<original>.pdf",
        working_copy_path="C:/case/copy.pdf",
        sha256="a" * 64,
        sha1="b" * 40,
        md5="c" * 32,
        working_copy_sha256="a" * 64,
        size_bytes=42,
        kind=FileKind.PDF,
        original_name="<original>.pdf",
        extension=".pdf",
        detected_format="PDF",
        mime_type="application/pdf",
    )
    run = ToolRun(
        tool_name="test-tool",
        command=["test-tool", "--json", "copy.pdf"],
        version="1.0",
        stdout="{}",
        stderr="",
        exit_code=0,
        status=ToolRunStatus.COMPLETED,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
        duration_ms=1000,
        parsed_result={"ok": True},
    )
    return AnalysisResult(
        evidence=evidence,
        findings=[Finding("PDF Info", "Title", "A & B", "test-tool")],
        tool_runs=[run],
    )


class PersistenceAndReportingTests(unittest.TestCase):
    def test_database_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repository = AnalysisRepository(Path(temp) / "db.sqlite3")
            repository.initialize()
            result = sample_result()
            repository.save(result)
            loaded = repository.load(result.evidence.id)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.evidence.sha256, result.evidence.sha256)
            self.assertEqual(loaded.findings[0].value, "A & B")
            self.assertEqual(loaded.tool_runs[0].parsed_result, {"ok": True})

    def test_json_and_html_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = sample_result()
            json_path = JsonReportExporter().export(result, root / "report.json")
            html_path = HtmlReportExporter().export(result, root / "report.html")
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["evidence"]["kind"], "pdf")
            html = html_path.read_text(encoding="utf-8")
            self.assertIn("A &amp; B", html)
            self.assertIn("&lt;original&gt;.pdf", html)
            self.assertIn("не является доказательством подделки", html)
            self.assertIn("Amirkhan Smagulov", html)

    def test_project_card_marks_notes_and_empty_project_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repository = AnalysisRepository(Path(temp) / "db.sqlite3")
            repository.initialize()
            project = ResearchProject("Исследование", "42", "PDF")
            repository.save_project(project)
            repository.log_event("project_created", project.id, "created", project.id)
            result = sample_result()
            result.evidence.project_id = project.id
            repository.save(result)
            repository.update_finding_mark(result.findings[0].id, "explained", False)
            repository.update_evidence_notes(result.evidence.id, "заметка", "вывод")
            loaded = repository.load(result.evidence.id)
            assert loaded is not None
            self.assertEqual(loaded.findings[0].user_mark, "explained")
            self.assertFalse(loaded.findings[0].include_in_report)
            self.assertEqual(loaded.evidence.user_conclusions, "вывод")
            with self.assertRaises(ValueError):
                repository.delete_project(project.id)

            empty = ResearchProject("Пустой", "43", "PDF")
            repository.save_project(empty)
            repository.log_event("project_created", empty.id, "created", empty.id)
            repository.delete_project(empty.id)
            self.assertIsNone(repository.get_project(empty.id))

    def test_summary_distinguishes_raw_js_bytes_from_object_action(self) -> None:
        result = sample_result()
        result.findings.extend(
            [
                Finding("PDF structure", "JavaScript markers", 1, "raw scan"),
                Finding(
                    "PDF structure",
                    "JavaScript actions in object dictionaries",
                    0,
                    "qpdf JSON",
                ),
            ]
        )
        summary = " ".join(SummaryBuilder().build(result))
        self.assertIn("не подтвердил JavaScript-действие", summary)


if __name__ == "__main__":
    unittest.main()
