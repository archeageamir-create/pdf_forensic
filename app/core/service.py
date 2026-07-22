from __future__ import annotations

import hashlib
import logging
import mmap
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable

from app.adapters import (
    ExifToolAdapter,
    JhoveAdapter,
    PdfBoxAdapter,
    PdfCpuAdapter,
    PdfIdAdapter,
    PdfParserAdapter,
    PopplerAdapter,
    QpdfAdapter,
    VeraPdfAdapter,
)
from app.adapters.base import (
    AdapterResult,
    AnalysisCancelled,
    CancellationToken,
    CommandRunner,
    ToolAdapter,
)
from app.adapters.pdf_tools import _python_tool_prefix
from app.analyzers import (
    FileComparator,
    MetadataConflictDetector,
    PdfStructureAnalyzer,
    PptxAnalyzer,
    SummaryBuilder,
    TimelineBuilder,
)
from app.analyzers.attachments import PdfAttachmentService
from app.analyzers.pdf_deep import PdfDeepAnalyzer, decode_pdf_stream
from app.analyzers.provenance import PdfProvenanceAnalyzer, enrich_provenance
from app.analyzers.revision_diff import RevisionVisualDiffer
from app.analyzers.pptx import OoxmlLimits
from app.analyzers.signatures import PdfSignatureAnalyzer
from app.core.config import AppConfig
from app.core.database import AnalysisRepository
from app.core.errors import AnalysisError, EvidencePreparationError
from app.core.formats import canonical_extension
from app.core.hashing import sha256_file
from app.core.workspace import EvidenceWorkspace
from app.models import (
    AnalysisMode,
    AnalysisResult,
    ComparisonResult,
    FileKind,
    Finding,
    FindingLevel,
    ResearchProject,
    ToolRun,
    ToolRunStatus,
)

LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[str, int, int], None]


class ForensicsService:
    """Typed service boundary between the GUI and all document parsing logic."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.default()
        self.config.ensure_directories()
        self.repository = AnalysisRepository(self.config.database_path)
        self.repository.initialize()
        self.workspace = EvidenceWorkspace(self.config.cases_dir)
        self.attachments = PdfAttachmentService()

    def analyze_file(
        self,
        original_path: Path,
        project_id: str | None = None,
        mode: AnalysisMode | str = AnalysisMode.FULL,
        selected_analyzers: set[str] | None = None,
        cancellation_token: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> AnalysisResult:
        mode = AnalysisMode(mode)
        token = cancellation_token or CancellationToken()
        selected = selected_analyzers or set()
        self._progress(progress, "Подготовка и хеширование", 0, 8)
        self._check_cancel(token)
        if original_path.stat().st_size > self.config.max_file_size_bytes:
            raise EvidencePreparationError("File exceeds configured size limit")
        evidence = self.workspace.prepare(original_path, project_id, mode)
        if not self.workspace.verify(evidence):
            raise EvidencePreparationError("Working copy failed the integrity check")
        self.repository.log_event("evidence_added", evidence.id, "working copy verified", project_id)

        path = Path(evidence.working_copy_path)
        findings = self._evidence_findings(evidence.extension, evidence.kind)
        tool_runs: list[ToolRun] = []
        errors: list[str] = []
        artifacts: dict[str, object] = {}

        self._progress(progress, "Встроенный структурный анализ", 1, 8)
        self._check_cancel(token)
        try:
            if evidence.kind == FileKind.PDF:
                findings.extend(PdfStructureAnalyzer().analyze(path))
                provenance = PdfProvenanceAnalyzer().analyze(path)
                findings.extend(provenance.findings)
                artifacts["pdf_provenance"] = provenance.artifact
                if self._enabled("deep_pdf", mode, selected):
                    deep = PdfDeepAnalyzer(
                        self.config.max_pdf_objects, self.config.max_stream_bytes
                    ).analyze(path)
                    findings.extend(deep.findings)
                    artifacts.update(deep.artifacts)
                    self._materialize_revisions(path, artifacts)
            else:
                limits = OoxmlLimits(
                    max_entries=self.config.max_zip_entries,
                    max_uncompressed_bytes=self.config.max_zip_uncompressed_bytes,
                    max_xml_part_bytes=self.config.max_xml_part_bytes,
                    max_compression_ratio=self.config.max_zip_compression_ratio,
                )
                findings.extend(PptxAnalyzer(limits).analyze(path))
        except (AnalysisError, OSError, ValueError) as exc:
            LOGGER.exception("Built-in analyzer failed")
            errors.append(f"Built-in analyzer: {exc}")

        self._progress(progress, "Подписи и вложения", 2, 8)
        self._check_cancel(token)
        if evidence.kind == FileKind.PDF and self._enabled("signatures", mode, selected):
            signature_result = PdfSignatureAnalyzer(
                self.config.validate_signatures
            ).analyze(path)
            findings.extend(signature_result.findings)
            artifacts["pdf_signatures"] = signature_result.signatures
        if evidence.kind == FileKind.PDF and self._enabled("attachments", mode, selected):
            try:
                attachment_items = self.attachments.list_attachments(path)
                artifacts["pdf_attachments"] = attachment_items
                findings.append(
                    Finding(
                        "PDF attachments",
                        "Attachments",
                        attachment_items,
                        "pypdf",
                    )
                )
            except Exception as exc:
                errors.append(f"Attachment analyzer: {exc}")

        self._progress(progress, "Внешние инструменты", 3, 8)
        adapters = self._adapters(evidence.kind, mode, selected, token, artifacts)
        for index, adapter in enumerate(adapters, start=1):
            self._check_cancel(token)
            if not self.workspace.verify(evidence):
                raise EvidencePreparationError("Working copy changed during analysis")
            self._progress(
                progress,
                f"Запуск {type(adapter).__name__}",
                3 + min(index, 3),
                8,
            )
            try:
                adapter_result = adapter.analyze(path)
                self._merge_adapter_result(
                    adapter_result, findings, tool_runs, artifacts
                )
            except Exception as exc:
                LOGGER.exception("Adapter failed: %s", type(adapter).__name__)
                errors.append(f"{type(adapter).__name__}: {exc}")
        revision_renders = artifacts.get("revision_renders")
        if evidence.kind == FileKind.PDF and isinstance(revision_renders, list):
            try:
                comparisons, visual_findings = RevisionVisualDiffer().compare(
                    revision_renders, path.parent / "revision-diffs"
                )
                artifacts["revision_visual_diffs"] = comparisons
                findings.extend(visual_findings)
            except (OSError, ValueError) as exc:
                LOGGER.exception("Visual revision comparison failed")
                errors.append(f"Visual revision comparison: {exc}")
        qdf_path = path.parent / "research-copy.qdf.pdf"
        if qdf_path.is_file():
            artifacts["qdf_path"] = str(qdf_path)

        self._progress(progress, "Сопоставление метаданных", 7, 8)
        self._check_cancel(token)
        if not self.workspace.verify(evidence):
            raise EvidencePreparationError("Working copy changed during analysis")
        try:
            original_unchanged = sha256_file(Path(evidence.original_path)) == evidence.sha256
            original_check_details = (
                "The original changed externally while the working copy was being analyzed."
                if not original_unchanged
                else ""
            )
        except OSError as exc:
            original_unchanged = False
            original_check_details = f"The original could not be re-read after analysis: {exc}"
            errors.append(f"Original integrity re-check: {exc}")
        findings.append(
            Finding(
                "Integrity",
                "Original hash unchanged during analysis",
                original_unchanged,
                "SHA-256",
                FindingLevel.HIGH if not original_unchanged else FindingLevel.INFO,
                details=original_check_details,
            )
        )
        MetadataConflictDetector().mark(findings)
        if evidence.kind == FileKind.PDF:
            raw_provenance = artifacts.get("pdf_provenance", {})
            if isinstance(raw_provenance, dict):
                artifacts["pdf_provenance"] = enrich_provenance(
                    raw_provenance, findings, artifacts
                )
        artifacts["timeline"] = TimelineBuilder().build(evidence, findings)
        unavailable = [run.tool_name for run in tool_runs if run.status != ToolRunStatus.COMPLETED]
        if unavailable:
            findings.append(
                Finding(
                    "Tool diagnostics",
                    "Unavailable or failed methods",
                    unavailable,
                    "Analysis service",
                    FindingLevel.LOW,
                    details="Other available methods were still completed.",
                )
            )
        result = AnalysisResult(
            evidence=evidence,
            findings=findings,
            tool_runs=tool_runs,
            errors=errors,
            incomplete=bool(errors or unavailable),
            artifacts=artifacts,
        )
        result.summary = SummaryBuilder().build(result)
        self.repository.save(result)
        self.repository.log_event(
            "analysis_completed",
            evidence.id,
            "partial" if result.incomplete else "completed",
            project_id,
        )
        self._progress(progress, "Исследование завершено", 8, 8)
        return result

    def analyze_batch(
        self,
        paths: Iterable[Path],
        project_id: str | None,
        mode: AnalysisMode,
        cancellation_token: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> list[AnalysisResult]:
        items = list(paths)
        results: list[AnalysisResult] = []
        token = cancellation_token or CancellationToken()
        for index, path in enumerate(items, start=1):
            self._check_cancel(token)
            if progress:
                progress(f"Файл {index}/{len(items)}: {path.name}", index - 1, len(items))
            results.append(
                self.analyze_file(path, project_id, mode, cancellation_token=token)
            )
        return results

    def create_project(self, project: ResearchProject) -> None:
        self.repository.save_project(project)
        self.repository.log_event("project_created", project.id, "created", project.id)

    def save_project(self, project: ResearchProject) -> None:
        from app.models.domain import utc_now_iso

        project.updated_at = utc_now_iso()
        self.repository.save_project(project)
        self.repository.log_event("project_updated", project.id, "saved", project.id)

    def compare(self, left_id: str, right_id: str) -> ComparisonResult:
        left = self.repository.load(left_id)
        right = self.repository.load(right_id)
        if left is None or right is None:
            raise ValueError("Both analysis results must exist")
        return FileComparator().compare(left, right)

    def extract_attachments(self, result: AnalysisResult, destination: Path) -> list[dict]:
        extracted = self.attachments.extract_all(
            Path(result.evidence.working_copy_path),
            destination,
            self.config.max_extracted_bytes,
        )
        self.repository.log_event(
            "attachments_extracted",
            result.evidence.id,
            f"{len(extracted)} files",
            result.evidence.project_id,
        )
        return extracted

    def export_pdf_object(
        self, result: AnalysisResult, object_number: int, generation: int, destination: Path
    ) -> Path:
        selected = self._select_pdf_object(result, object_number, generation)
        length = int(selected["length"])
        if length > self.config.max_stream_bytes:
            raise ValueError("PDF object exceeds the configured export limit")
        with Path(result.evidence.working_copy_path).open("rb") as stream:
            stream.seek(int(selected["offset"]))
            data = stream.read(length)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return destination

    def read_pdf_object(
        self, result: AnalysisResult, object_number: int, generation: int
    ) -> dict[str, object]:
        selected = self._select_pdf_object(result, object_number, generation)
        length = int(selected.get("length", 0))
        if length <= 0 or length > self.config.max_stream_bytes:
            raise ValueError("PDF object exceeds the configured interactive viewing limit")
        path = Path(result.evidence.working_copy_path)
        with path.open("rb") as stream:
            stream.seek(int(selected["offset"]))
            raw = stream.read(length)
        payload: dict[str, object] = {"raw": raw.decode("latin-1", errors="replace")}
        stream_offset = selected.get("stream_offset")
        stream_length = int(selected.get("stream_length", 0))
        if stream_offset is not None and stream_length:
            if stream_length > self.config.max_stream_bytes:
                payload["decode_error"] = "Stream exceeds the configured viewing limit"
            else:
                with path.open("rb") as stream:
                    stream.seek(int(stream_offset))
                    encoded = stream.read(stream_length)
                try:
                    decoded = decode_pdf_stream(encoded, list(selected.get("filters", [])))
                    payload["decoded"] = decoded.decode("utf-8", errors="replace")
                except Exception as exc:
                    payload["decode_error"] = str(exc)
        return payload

    @staticmethod
    def _select_pdf_object(
        result: AnalysisResult, object_number: int, generation: int
    ) -> dict[str, object]:
        objects = result.artifacts.get("pdf_objects", [])
        selected = next(
            (
                item
                for item in reversed(objects if isinstance(objects, list) else [])
                if isinstance(item, dict)
                and item.get("object") == object_number
                and item.get("generation") == generation
            ),
            None,
        )
        if selected is None:
            raise ValueError("PDF object not found")
        return selected

    @staticmethod
    def read_hex(path: Path, offset: int, length: int = 4096) -> bytes:
        with path.open("rb") as stream:
            stream.seek(max(0, offset))
            return stream.read(max(0, min(length, 1024 * 1024)))

    @staticmethod
    def find_bytes(path: Path, needle: bytes, start: int = 0) -> int:
        if not needle:
            return -1
        with path.open("rb") as stream:
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                return data.find(needle, max(0, start))

    def check_installation(self) -> list[ToolRun]:
        runner = CommandRunner(20)
        poppler = PopplerAdapter(self.config.poppler_bin_dir)
        jhove = JhoveAdapter(self.config.java_command, self.config.jhove_dir)
        verapdf = VeraPdfAdapter(self.config.java_command, self.config.verapdf_dir)
        pdfbox_jar = self.config.pdfbox_jar or Path("pdfbox-app.jar")
        commands = [
            ("ExifTool", [self.config.exiftool_command, "-ver"]),
            ("qpdf", [self.config.qpdf_command, "--version"]),
            ("pdfcpu", [self.config.pdfcpu_command, "version"]),
            ("Poppler", [poppler._exe("pdfinfo"), "-v"]),
            ("Java runtime", [self.config.java_command, "-version"]),
            ("JHOVE PDF-hul", [*jhove.command_prefix(), "-h"]),
            ("veraPDF", [*verapdf.command_prefix(), "--version"]),
            (
                "Apache PDFBox",
                [self.config.java_command, "-jar", str(pdfbox_jar), "version"],
            ),
            (
                "pdfid.py",
                [*_python_tool_prefix("pdfid", self.config.pdfid_script or Path("pdfid.py")), "--version"],
            ),
            (
                "pdf-parser.py",
                [
                    *_python_tool_prefix(
                        "pdf-parser", self.config.pdf_parser_script or Path("pdf-parser.py")
                    ),
                    "--version",
                ],
            ),
        ]
        return [runner.run(name, command, command) for name, command in commands]

    def launch_pdfbox_debugger(self, result: AnalysisResult) -> None:
        jar = self.config.pdfbox_jar
        if not jar or not jar.is_file():
            raise FileNotFoundError("Компонент Apache PDFBox не найден.")
        java = Path(self.config.java_command)
        javaw = java.with_name("javaw.exe") if java.name.casefold() == "java.exe" else java
        executable = javaw if javaw.is_file() else java
        subprocess.Popen(
            [
                str(executable),
                "-jar",
                str(jar),
                "debug",
                str(result.evidence.working_copy_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )

    def _adapters(
        self,
        kind: FileKind,
        mode: AnalysisMode,
        selected: set[str],
        token: CancellationToken,
        artifacts: dict[str, object],
    ) -> list[ToolAdapter]:
        adapters: list[ToolAdapter] = []
        if self._enabled("exiftool", mode, selected, quick=True):
            adapters.append(
                ExifToolAdapter(
                    self.config.exiftool_command,
                    self.config.tool_timeout_seconds,
                    token,
                )
            )
        if kind == FileKind.PDF:
            if self._enabled("qpdf", mode, selected, quick=True):
                adapters.append(
                    QpdfAdapter(
                        self.config.qpdf_command,
                        self.config.tool_timeout_seconds,
                        token,
                        create_qdf=(
                            mode == AnalysisMode.FULL and self.config.create_qdf_in_full_mode
                        ),
                        create_object_index=(mode == AnalysisMode.FULL),
                        max_objects=self.config.max_pdf_objects,
                    )
                )
            if self._enabled("pdfcpu", mode, selected):
                adapters.append(
                    PdfCpuAdapter(
                        self.config.pdfcpu_command,
                        self.config.tool_timeout_seconds,
                        token,
                    )
                )
            if self._enabled("poppler", mode, selected):
                revisions: list[tuple[int, Path]] = []
                raw_revisions = artifacts.get("pdf_revisions", [])
                if isinstance(raw_revisions, list):
                    for item in raw_revisions:
                        if not isinstance(item, dict) or not item.get("reconstructed_path"):
                            continue
                        revisions.append(
                            (int(item.get("number", 0)), Path(str(item["reconstructed_path"])))
                        )
                adapters.append(
                    PopplerAdapter(
                        self.config.poppler_bin_dir,
                        self.config.tool_timeout_seconds,
                        token,
                        revisions=revisions,
                        max_render_pages=self.config.max_revision_render_pages,
                    )
                )
            if self._enabled("jhove", mode, selected):
                adapters.append(
                    JhoveAdapter(
                        self.config.java_command,
                        self.config.jhove_dir,
                        self.config.tool_timeout_seconds,
                        token,
                    )
                )
            if self._enabled("verapdf", mode, selected):
                adapters.append(
                    VeraPdfAdapter(
                        self.config.java_command,
                        self.config.verapdf_dir,
                        self.config.tool_timeout_seconds,
                        token,
                    )
                )
            if self._enabled("pdfbox", mode, selected):
                adapters.append(
                    PdfBoxAdapter(
                        self.config.java_command,
                        self.config.pdfbox_jar,
                        self.config.tool_timeout_seconds,
                        token,
                    )
                )
            if self._enabled("pdfid", mode, selected, quick=True):
                adapters.append(
                    PdfIdAdapter(
                        self.config.pdfid_script,
                        self.config.tool_timeout_seconds,
                        token,
                    )
                )
            if self._enabled("pdf_parser", mode, selected):
                adapters.append(
                    PdfParserAdapter(
                        self.config.pdf_parser_script,
                        self.config.tool_timeout_seconds,
                        token,
                    )
                )
        return adapters

    @staticmethod
    def _enabled(
        name: str,
        mode: AnalysisMode,
        selected: set[str],
        quick: bool = False,
    ) -> bool:
        if mode == AnalysisMode.CUSTOM:
            return name in selected
        if mode == AnalysisMode.QUICK:
            return quick
        return True

    @staticmethod
    def _merge_adapter_result(
        result: AdapterResult,
        findings: list[Finding],
        tool_runs: list[ToolRun],
        artifacts: dict[str, object],
    ) -> None:
        findings.extend(result.findings)
        if result.artifacts:
            if "qpdf_objects" in result.artifacts:
                existing = artifacts.get("pdf_objects")
                qpdf_objects = result.artifacts["qpdf_objects"]
                if isinstance(existing, list) and isinstance(qpdf_objects, list):
                    known = {
                        (item.get("object"), item.get("generation"))
                        for item in existing
                        if isinstance(item, dict)
                    }
                    existing.extend(
                        item
                        for item in qpdf_objects
                        if isinstance(item, dict)
                        and (item.get("object"), item.get("generation")) not in known
                    )
                    result.artifacts["pdf_objects"] = existing
                else:
                    result.artifacts["pdf_objects"] = qpdf_objects
                result.artifacts.pop("qpdf_objects", None)
            artifacts.update(result.artifacts)
        parsed = [
            {
                "category": item.category,
                "name": item.name,
                "value": item.value,
                "source": item.source,
            }
            for item in result.findings
        ]
        for run in result.tool_runs:
            run.parsed_result["findings"] = parsed
        tool_runs.extend(result.tool_runs)

    @staticmethod
    def _evidence_findings(extension: str, kind: FileKind) -> list[Finding]:
        expected = canonical_extension(kind)
        mismatch = extension.casefold() != expected
        return [
            Finding("Integrity", "Signature format", kind.value.upper(), "File signature"),
            Finding(
                "Integrity",
                "Extension matches signature",
                not mismatch,
                "File signature",
                FindingLevel.MEDIUM if mismatch else FindingLevel.INFO,
                details=(
                    f"File extension {extension or '(none)'} differs from detected {expected}."
                    if mismatch
                    else ""
                ),
            ),
            Finding("Integrity", "Working copy hash verified", True, "SHA-256"),
        ]

    @staticmethod
    def _progress(callback: ProgressCallback | None, stage: str, current: int, total: int) -> None:
        if callback:
            callback(stage, current, total)

    @staticmethod
    def _check_cancel(token: CancellationToken) -> None:
        if token.cancelled:
            raise AnalysisCancelled("Analysis cancelled by user")

    @staticmethod
    def _materialize_revisions(path: Path, artifacts: dict[str, object]) -> None:
        revisions = artifacts.get("pdf_revisions")
        if not isinstance(revisions, list) or len(revisions) < 2:
            return
        destination = path.parent / "revisions"
        destination.mkdir(parents=True, exist_ok=True)
        with path.open("rb") as source:
            for item in revisions:
                if not isinstance(item, dict):
                    continue
                end = int(item.get("byte_end", 0))
                number = int(item.get("number", 0))
                if end <= 0 or number <= 0:
                    continue
                source.seek(0)
                remaining = end
                target = destination / f"revision-{number:03d}.pdf"
                temporary = target.with_suffix(".pdf.tmp")
                digest = hashlib.sha256()
                with temporary.open("wb") as output:
                    while remaining:
                        chunk = source.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        remaining -= len(chunk)
                temporary.replace(target)
                item["reconstructed_path"] = str(target)
                item["sha256"] = digest.hexdigest()
