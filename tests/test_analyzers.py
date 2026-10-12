from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from app.analyzers.metadata import MetadataConflictDetector
from app.analyzers.pdf import PdfStructureAnalyzer
from app.analyzers.pptx import PptxAnalyzer
from app.core.errors import AnalysisError
from app.models import Finding
from tests.helpers import write_minimal_pdf, write_test_pptx


class AnalyzerTests(unittest.TestCase):
    def test_pdf_structure_and_revision_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.pdf"
            write_minimal_pdf(path, b"\nstartxref\n10\n%%EOF\n/JS /EmbeddedFile /Type /Sig")
            findings = PdfStructureAnalyzer().analyze(path)
            values = {item.name: item.value for item in findings}
            self.assertEqual(values["PDF version"], "1.7")
            self.assertEqual(values["Objects"], 4)
            self.assertEqual(values["EOF markers"], 2)
            self.assertEqual(values["Potential revision sections"], 2)
            self.assertEqual(values["JavaScript markers"], 1)
            self.assertEqual(values["Digital signature markers"], 1)

    def test_pptx_ooxml_properties_comments_notes_and_embeddings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.pptx"
            write_test_pptx(path)
            findings = PptxAnalyzer().analyze(path)
            index = {(item.category, item.name): item.value for item in findings}
            self.assertEqual(index[("OOXML Core Properties", "creator")], "Иван")
            self.assertEqual(index[("OOXML Extended Properties", "Application")], "PowerPoint")
            self.assertEqual(index[("PPTX structure", "Hidden slides")], 1)
            self.assertEqual(index[("PPTX comments", "Comments")][0]["text"], "Проверить")
            self.assertEqual(index[("PPTX notes", "Notes")][0]["text"], "Заметка")
            self.assertEqual(len(index[("PPTX embedded objects", "Objects")]), 1)
            self.assertEqual(len(index[("PPTX relationships", "External relationships")]), 1)

    def test_pptx_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "unsafe.pptx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr("ppt/presentation.xml", "<presentation/>")
                archive.writestr("../escape.bin", b"x")
            with self.assertRaises(AnalysisError):
                PptxAnalyzer().analyze(path)

    def test_metadata_conflict_is_neutral(self) -> None:
        findings = [
            Finding("PDF Info", "Author", "Alice", "ExifTool/PDF"),
            Finding("XMP", "Author", "Bob", "ExifTool/XMP-dc"),
        ]
        MetadataConflictDetector().mark(findings)
        self.assertTrue(all(item.conflict for item in findings))
        self.assertTrue(all("само по себе не доказывает подделку" in item.details for item in findings))

    def test_pdf_author_is_compared_with_xmp_creator(self) -> None:
        findings = [
            Finding("PDF Info", "Author", "Alice", "ExifTool/PDF"),
            Finding("XMP", "Creator", ["Bob"], "ExifTool/XMP-dc"),
        ]
        MetadataConflictDetector().mark(findings)
        self.assertTrue(all(item.conflict for item in findings[:2]))


if __name__ == "__main__":
    unittest.main()
