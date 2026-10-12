from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
import unittest
import zipfile
import zlib
from pathlib import Path

from docx import Document
from PIL import Image
from pypdf import PdfWriter

from app.adapters.base import CancellationToken, CommandRunner
from app.adapters.pdf_tools import _parse_qpdf_objects, _qpdf_marker_count
from app.analyzers.attachments import PdfAttachmentService
from app.analyzers.pdf_deep import PdfDeepAnalyzer
from app.analyzers.provenance import PdfProvenanceAnalyzer, enrich_provenance
from app.analyzers.revision_diff import RevisionVisualDiffer
from app.analyzers.signatures import PdfSignatureAnalyzer
from app.analyzers.timeline import normalize_date
from app.core.config import AppConfig
from app.core.service import ForensicsService
from app.core.updater import UpdateService
from app.models import AnalysisMode, Finding, FindingLevel, ToolRunStatus
from app.reporting import DocxReportExporter, ZipPackageExporter
from tests.helpers import write_minimal_pdf
from tests.test_persistence_reporting import sample_result


class DeepPdfTests(unittest.TestCase):
    def test_provenance_extracts_document_ids_and_xmp_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "provenance.pdf"
            path.write_bytes(
                b"%PDF-1.7\n"
                b"trailer << /ID [<AABB><0102>] /Author (Ivan) "
                b"/Creator (Writer) /Producer (PDF Engine) >>\n"
                b"<x:xmpmeta xmlns:x=\"adobe:ns:meta/\" "
                b"xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\" "
                b"xmlns:xmpMM=\"http://ns.adobe.com/xap/1.0/mm/\" "
                b"xmlns:stEvt=\"http://ns.adobe.com/xap/1.0/sType/ResourceEvent#\">"
                b"<rdf:RDF><rdf:Description xmpMM:DocumentID=\"uuid:doc-1\">"
                b"<xmpMM:History><rdf:Seq><rdf:li rdf:parseType=\"Resource\" "
                b"stEvt:action=\"saved\" stEvt:when=\"2026-01-02T10:00:00Z\" "
                b"stEvt:softwareAgent=\"Acrobat\"/></rdf:Seq></xmpMM:History>"
                b"</rdf:Description></rdf:RDF></x:xmpmeta>\n"
                b"trailer << /ID [<AABB><0304>] >>\n%%EOF"
            )
            result = PdfProvenanceAnalyzer().analyze(path)
            self.assertEqual(len(result.artifact["document_ids"]), 2)
            self.assertEqual(
                result.artifact["xmp_lineage"]["DocumentID"], ["uuid:doc-1"]
            )
            self.assertEqual(result.artifact["xmp_history"][0]["action"], "saved")
            changed = next(
                item
                for item in result.findings
                if item.name == "Document ID changed across trailers"
            )
            self.assertTrue(changed.value)

            enriched = enrich_provenance(
                result.artifact,
                [Finding("PDF Info", "Author", "Ivan", "ExifTool")],
                {},
            )
            self.assertEqual(enriched["signals"][0]["role"], "Заявленный автор")

    def test_qpdf_json_adds_objects_hidden_in_object_streams(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "objects.pdf"
            pdf.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF")
            payload = {
                "qpdf": [
                    {"jsonversion": 2, "pdfversion": "1.7"},
                    {
                        "obj:1 0 R": {"value": {"/Type": "/Catalog", "/Pages": "7 0 R"}},
                        "obj:7 0 R": {"value": {"/Type": "/Pages", "/Count": 0}},
                    },
                ]
            }
            index = root / "objects.json"
            index.write_text(json.dumps(payload), encoding="utf-8")
            objects = _parse_qpdf_objects(index, pdf, 100)
            by_number = {item["object"]: item for item in objects}
            self.assertEqual(by_number[1]["storage"], "physical")
            self.assertEqual(by_number[7]["storage"], "object_stream")
            self.assertEqual(by_number[1]["references"][0]["object"], 7)
            self.assertEqual(_qpdf_marker_count(objects, "/JS", "/JavaScript"), 0)

    def test_revision_comparison_and_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "incremental.pdf"
            base = write_minimal_pdf(path)
            second_offset = len(base)
            update = (
                b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Author (Updated) >>\nendobj\n"
                b"xref\n3 1\n"
                + f"{second_offset:010d} 00000 n \n".encode()
                + b"trailer\n<< /Size 5 /Root 1 0 R /Prev 123 >>\nstartxref\n"
                + str(second_offset + 70).encode()
                + b"\n%%EOF\n"
            )
            path.write_bytes(base + update)
            deep = PdfDeepAnalyzer().analyze(path)
            revisions = deep.artifacts["pdf_revisions"]
            comparison = deep.artifacts["pdf_revision_comparison"]
            self.assertEqual(len(revisions), 2)
            self.assertIn(3, comparison[1]["redefined_objects"])

            config = AppConfig(
                data_dir=root / "data",
                database_path=root / "data" / "db.sqlite3",
                cases_dir=root / "data" / "cases",
                reports_dir=root / "data" / "reports",
                create_qdf_in_full_mode=False,
                validate_signatures=False,
            )
            service = ForensicsService(config)
            artifacts = dict(deep.artifacts)
            service._materialize_revisions(path, artifacts)
            first = Path(artifacts["pdf_revisions"][0]["reconstructed_path"])
            self.assertEqual(first.read_bytes(), base.rstrip(b"\n"))
            self.assertEqual(
                artifacts["pdf_revisions"][0]["sha256"],
                hashlib.sha256(first.read_bytes()).hexdigest(),
            )

    def test_stream_is_decoded_and_available_on_demand(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "stream.pdf"
            clear = b"BT /F1 12 Tf (Hello stream) Tj ET"
            encoded = zlib.compress(clear)
            path.write_bytes(
                b"%PDF-1.7\n1 0 obj\n<< /Length "
                + str(len(encoded)).encode()
                + b" /Filter /FlateDecode >>\nstream\n"
                + encoded
                + b"\nendstream\nendobj\nstartxref\n0\n%%EOF"
            )
            deep = PdfDeepAnalyzer().analyze(path)
            self.assertIn("Hello stream", deep.artifacts["pdf_objects"][0]["decoded_preview"])

    def test_byte_range_layout_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "signature.pdf"
            prefix = b"%PDF-1.7 /ByteRange [0 50 100 100] /Contents <001122>"
            path.write_bytes(prefix.ljust(200, b"X"))
            signature = PdfSignatureAnalyzer(False).analyze(path).signatures[0]
            self.assertTrue(signature["valid_layout"])
            self.assertTrue(signature["covers_file_except_signature_container"])
            self.assertEqual(signature["excluded_ranges"], [{"offset": 50, "length": 50}])
            expected = hashlib.sha256(path.read_bytes()[:50] + path.read_bytes()[100:]).hexdigest()
            self.assertEqual(signature["signed_ranges_sha256"], expected)

    def test_visual_revision_diff_creates_review_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            left = root / "revision-001-1.png"
            right = root / "revision-002-1.png"
            Image.new("RGB", (40, 40), "white").save(left)
            changed = Image.new("RGB", (40, 40), "white")
            for x in range(10, 20):
                for y in range(10, 20):
                    changed.putpixel((x, y), (0, 0, 0))
            changed.save(right)
            comparisons, findings = RevisionVisualDiffer().compare(
                [
                    {"revision": 1, "pages": [{"page": 1, "path": str(left)}]},
                    {"revision": 2, "pages": [{"page": 1, "path": str(right)}]},
                ],
                root / "diffs",
            )
            self.assertEqual(comparisons[0]["status"], "changed")
            self.assertGreater(comparisons[0]["changed_percent"], 0)
            self.assertTrue(Path(str(comparisons[0]["diff_path"])).is_file())
            self.assertEqual(findings[0].level, FindingLevel.MANUAL_REVIEW)


class AttachmentAndReportingTests(unittest.TestCase):
    def test_attachment_listing_and_safe_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "attached.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.add_attachment("../evidence.txt", b"payload")
            with path.open("wb") as stream:
                writer.write(stream)
            service = PdfAttachmentService()
            listed = service.list_attachments(path)
            extracted = service.extract_all(path, root / "out", 1024)
            self.assertEqual(listed[0]["name"], "../evidence.txt")
            self.assertEqual(Path(extracted[0]["path"]).read_bytes(), b"payload")
            self.assertEqual(Path(extracted[0]["path"]).parent, (root / "out").resolve())

    def test_docx_and_zip_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = sample_result()
            result.summary = ["Проверка завершена."]
            result.tool_runs[0].stdout = "raw\x00value\x01"
            qpdf_json = root / "qpdf-objects.json"
            qpdf_json.write_text('{"qpdf": []}', encoding="utf-8")
            revision = root / "revision-001.pdf"
            revision.write_bytes(b"%PDF-1.7\n%%EOF")
            poppler_text = root / "poppler-text.txt"
            poppler_text.write_text("independent text", encoding="utf-8")
            result.artifacts.update(
                {
                    "qpdf_json_path": str(qpdf_json),
                    "pdf_revisions": [{"reconstructed_path": str(revision)}],
                    "poppler_text_path": str(poppler_text),
                    "pdf_provenance": {
                        "caution": "Требуется внешнее подтверждение.",
                        "signals": [
                            {
                                "role": "Заявленный автор",
                                "value": "Иван",
                                "source": "XMP",
                                "strength": "заявлено в метаданных",
                                "explanation": "Не доказывает личность.",
                            }
                        ],
                    },
                }
            )
            docx_path = DocxReportExporter().export(result, root / "report.docx")
            document = Document(docx_path)
            text = "\n".join(item.text for item in document.paragraphs)
            self.assertIn("ТЕХНИЧЕСКИЙ ОТЧЁТ", text)
            self.assertIn("4. Область исследования", text)
            self.assertIn("Авторство и история правок PDF", text)
            self.assertIn("ТОО «АНСЭ»", text)
            self.assertIn(r"raw\x00value\x01", text)
            package = ZipPackageExporter().export(result, root / "package.zip")
            with zipfile.ZipFile(package) as archive:
                names = set(archive.namelist())
                self.assertIn("report/report.json", names)
                self.assertIn("report/report.docx", names)
                self.assertIn("raw_results/qpdf-objects.json", names)
                self.assertIn("raw_results/revisions/revision-001.pdf", names)
                self.assertIn("raw_results/poppler-text.txt", names)
                self.assertIn("licenses/poppler/POPPLER-COPYING.txt", names)
                self.assertIn("AUTHORSHIP.txt", names)
                self.assertIn("manifest.sha256", names)


class RuntimeTests(unittest.TestCase):
    def test_service_accepts_mode_string_from_qt_combobox(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "gui-mode.pdf"
            write_minimal_pdf(path)
            config = AppConfig(
                data_dir=root / "data",
                database_path=root / "data" / "db.sqlite3",
                cases_dir=root / "data" / "cases",
                reports_dir=root / "data" / "reports",
                create_qdf_in_full_mode=False,
                validate_signatures=False,
            )
            service = ForensicsService(config)
            result = service.analyze_file(
                path, mode="custom", selected_analyzers=set()
            )
            self.assertEqual(result.evidence.analysis_mode, AnalysisMode.CUSTOM)
            self.assertIsNotNone(service.repository.load(result.evidence.id))

    def test_date_normalization_keeps_timezone_information(self) -> None:
        pdf = normalize_date("D:20260102123456+05'00'")
        exif = normalize_date("2026:01:02 12:34:56+05:00")
        no_zone = normalize_date("2026-01-02T12:34:56")
        self.assertEqual(pdf["normalized"], "2026-01-02T12:34:56+05:00")
        self.assertEqual(exif["normalized"], "2026-01-02T12:34:56+05:00")
        self.assertTrue(pdf["timezone_present"])
        self.assertFalse(no_zone["timezone_present"])

    def test_running_command_can_be_cancelled(self) -> None:
        token = CancellationToken()
        runner = CommandRunner(20, token)
        result: list = []

        def execute() -> None:
            import sys

            result.append(runner.run("wait", [sys.executable, "-c", "import time; time.sleep(10)"]))

        thread = threading.Thread(target=execute)
        thread.start()
        time.sleep(0.4)
        token.cancel()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0].status, ToolRunStatus.CANCELLED)

    def test_update_download_requires_matching_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            installer = root / "setup.exe"
            installer.write_bytes(b"signed-build-placeholder")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "9.1.0",
                        "download_url": installer.as_uri(),
                        "sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            service = UpdateService(manifest.as_uri())
            info = service.check("0.2.0")
            self.assertIsNotNone(info)
            assert info is not None
            downloaded = service.download(info, root / "downloads")
            self.assertEqual(downloaded.read_bytes(), installer.read_bytes())


if __name__ == "__main__":
    unittest.main()
