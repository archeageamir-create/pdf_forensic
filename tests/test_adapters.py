from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.adapters.exiftool import ExifToolAdapter
from app.adapters.extended_pdf_tools import (
    _parse_fonts,
    _parse_jhove,
    _parse_jhove_xml,
    _parse_verapdf_validation,
)
from app.models import FindingLevel
from app.adapters.pdf_tools import (
    PdfCpuAdapter,
    PdfIdAdapter,
    PdfParserAdapter,
    QpdfAdapter,
    _python_tool_prefix,
)
from app import tool_runner


class AdapterParserTests(unittest.TestCase):
    def test_bundled_tool_runner_forces_utf8_stdio(self) -> None:
        stdout = Mock()
        stderr = Mock()
        with patch.object(tool_runner.sys, "stdout", stdout), patch.object(
            tool_runner.sys, "stderr", stderr
        ):
            tool_runner._configure_utf8_stdio()

        stdout.reconfigure.assert_called_once_with(
            encoding="utf-8", errors="backslashreplace"
        )
        stderr.reconfigure.assert_called_once_with(
            encoding="utf-8", errors="backslashreplace"
        )

    def test_exiftool_json_separates_pdf_info_and_xmp(self) -> None:
        output = '[{"SourceFile":"copy.pdf","PDF:Author":"A","XMP-dc:Creator":["B"]}]'
        findings = ExifToolAdapter._parse_json(output)
        categories = {(item.category, item.name) for item in findings}
        self.assertIn(("PDF Info", "Author"), categories)
        self.assertIn(("XMP", "Creator"), categories)

    def test_pdfid_counts_required_markers(self) -> None:
        output = """PDF Header: %PDF-1.7
 obj                  10
 /Page                 2
 /JS                   1
 /EmbeddedFile         3
 %%EOF                 2
"""
        values = {item.name: item.value for item in PdfIdAdapter._parse(output)}
        self.assertEqual(values["Objects"], 10)
        self.assertEqual(values["Pages"], 2)
        self.assertEqual(values["JavaScript /JS"], 1)
        self.assertEqual(values["Embedded files"], 3)
        self.assertEqual(values["EOF markers"], 2)

    def test_pdf_parser_statistics(self) -> None:
        findings = PdfParserAdapter._parse("Indirect object: 12\n /Page 3: 4\nnot a count")
        self.assertEqual(findings[0].name, "Indirect object")
        self.assertEqual(findings[0].value, 12)

    def test_qpdf_output(self) -> None:
        check = QpdfAdapter._parse(
            "qpdf/check", "checking file\nPDF Version: 1.6\nFile is not encrypted\n", ""
        )
        self.assertIn("1.6", [str(item.value) for item in check])
        encryption = QpdfAdapter._parse("qpdf/encryption", "File is not encrypted\n", "")
        self.assertFalse(encryption[0].value)

    def test_pdfcpu_validation_is_a_neutral_finding(self) -> None:
        failed = PdfCpuAdapter._parse(
            "pdfcpu/validate-strict",
            "validating(mode=strict) sample.pdf",
            "validation error: missing required entry",
        )
        self.assertFalse(failed[0].value)
        self.assertEqual(failed[0].category, "PDF validation")
        passed = PdfCpuAdapter._parse(
            "pdfcpu/validate-relaxed", "validation ok", ""
        )
        self.assertTrue(passed[0].value)

    def test_poppler_font_inventory_is_structured(self) -> None:
        output = """name                                 type              encoding         emb sub uni object ID
------------------------------------ ----------------- ---------------- --- --- --- ---------
AAAAAA+Example                       TrueType          WinAnsi          yes yes no      12  0
"""
        fonts = _parse_fonts(output)
        self.assertEqual(fonts[0]["name"], "AAAAAA+Example")
        self.assertEqual(fonts[0]["object"], 12)
        self.assertEqual(fonts[0]["unicode"], "no")

    def test_jhove_not_valid_is_not_treated_as_valid(self) -> None:
        findings = _parse_jhove(
            {
                "jhove": {
                    "repInfo": [
                        {"status": "Well-Formed, but not valid", "messages": ["xref"]}
                    ]
                }
            }
        )
        self.assertEqual(findings[0].level, FindingLevel.MEDIUM)

    def test_jhove_xml_fallback_is_normalized(self) -> None:
        payload = _parse_jhove_xml(
            """<?xml version="1.0"?>
<jhove xmlns="http://schema.openpreservation.org/ois/xml/ns/jhove" release="1.34.0">
  <repInfo uri="copy.pdf"><format>PDF</format><version>1.7</version>
    <status>Well-Formed and valid</status><mimeType>application/pdf</mimeType>
    <profiles><profile>Tagged PDF</profile></profiles>
  </repInfo>
</jhove>"""
        )
        report = payload["jhove"]["repInfo"][0]
        self.assertEqual(report["status"], "Well-Formed and valid")
        self.assertEqual(report["profiles"], ["Tagged PDF"])

    def test_verapdf_list_result_is_normalized(self) -> None:
        findings = _parse_verapdf_validation(
            {
                "report": {
                    "jobs": [
                        {
                            "validationResult": [
                                {
                                    "profileName": "PDF/A-1b validation profile",
                                    "statement": "not compliant",
                                    "compliant": False,
                                    "details": {
                                        "passedRules": 10,
                                        "failedRules": 1,
                                        "passedChecks": 30,
                                        "failedChecks": 2,
                                        "ruleSummaries": [
                                            {
                                                "specification": "ISO 19005-1",
                                                "clause": "6.1",
                                                "testNumber": 1,
                                                "description": "example",
                                                "failedChecks": 2,
                                                "checks": ["large raw details"],
                                            }
                                        ],
                                    },
                                }
                            ]
                        }
                    ]
                }
            }
        )
        self.assertFalse(findings[0].value)
        self.assertEqual(findings[1].value["profile"], "PDF/A-1b validation profile")
        self.assertNotIn("checks", findings[2].value[0])

    def test_frozen_build_uses_bundled_subprocess_runner(self) -> None:
        with (
            patch("app.adapters.pdf_tools.sys.frozen", True, create=True),
            patch("app.adapters.pdf_tools.sys._MEIPASS", "C:/bundle", create=True),
        ):
            command = _python_tool_prefix("pdfid", Path("pdfid.py"))
        self.assertEqual(command[1], "pdfid")
        self.assertTrue(command[0].endswith("DocumentForensicToolRunner.exe"))


if __name__ == "__main__":
    unittest.main()
