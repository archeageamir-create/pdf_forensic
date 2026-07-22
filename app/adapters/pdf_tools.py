from __future__ import annotations

import json
import mmap
import os
import re
import sys
from pathlib import Path

from app.adapters.base import AdapterResult, CancellationToken, CommandRunner, ToolAdapter
from app.models import Finding, FindingLevel, ToolRunStatus


class QpdfAdapter(ToolAdapter):
    def __init__(
        self,
        command: str = "qpdf",
        timeout_seconds: int = 120,
        cancellation_token: CancellationToken | None = None,
        create_qdf: bool = False,
        create_object_index: bool = False,
        max_objects: int = 250_000,
    ) -> None:
        self.command = command
        self.runner = CommandRunner(timeout_seconds, cancellation_token)
        self.create_qdf = create_qdf
        self.create_object_index = create_object_index
        self.max_objects = max_objects

    def analyze(self, path: Path) -> AdapterResult:
        version = [self.command, "--version"]
        runs = [
            self.runner.run("qpdf/check", [self.command, "--check", str(path)], version),
            self.runner.run(
                "qpdf/encryption", [self.command, "--show-encryption", str(path)], version
            ),
            self.runner.run("qpdf/xref", [self.command, "--show-xref", str(path)], version),
        ]
        if self.create_qdf:
            qdf_path = path.parent / "research-copy.qdf.pdf"
            temporary_qdf = path.parent / "research-copy.qdf.tmp.pdf"
            temporary_qdf.unlink(missing_ok=True)
            runs.append(
                self.runner.run(
                    "qpdf/qdf",
                    [
                        self.command,
                        "--qdf",
                        "--object-streams=disable",
                        str(path),
                        str(temporary_qdf),
                    ],
                    version,
                )
            )
        object_index_path = path.parent / "qpdf-objects.json"
        temporary_index = path.parent / "qpdf-objects.tmp.json"
        if self.create_object_index:
            temporary_index.unlink(missing_ok=True)
            runs.append(
                self.runner.run(
                    "qpdf/json",
                    [
                        self.command,
                        "--json",
                        "--json-key=qpdf",
                        str(path),
                        str(temporary_index),
                    ],
                    version,
                )
            )
        # qpdf uses exit code 3 for a completed check with warnings.
        for run in runs:
            if run.exit_code == 3:
                run.status = ToolRunStatus.COMPLETED
        if self.create_qdf:
            qdf_run = next(run for run in runs if run.tool_name == "qpdf/qdf")
            if qdf_run.status == ToolRunStatus.COMPLETED and temporary_qdf.is_file():
                temporary_qdf.replace(qdf_path)
            elif temporary_qdf.is_file():
                temporary_qdf.unlink(missing_ok=True)
        artifacts: dict[str, object] = {}
        if self.create_object_index:
            json_run = next(run for run in runs if run.tool_name == "qpdf/json")
            if json_run.status == ToolRunStatus.COMPLETED and temporary_index.is_file():
                temporary_index.replace(object_index_path)
                try:
                    qpdf_objects = _parse_qpdf_objects(
                        object_index_path, path, self.max_objects
                    )
                    artifacts["qpdf_json_path"] = str(object_index_path)
                    artifacts["qpdf_objects"] = qpdf_objects
                    expanded = sum(
                        1 for item in qpdf_objects if item.get("storage") == "object_stream"
                    )
                    findings = [
                        Finding(
                            "PDF objects",
                            "qpdf JSON objects",
                            len(qpdf_objects),
                            "qpdf JSON",
                        ),
                        Finding(
                            "PDF objects",
                            "Objects expanded from object streams",
                            expanded,
                            "qpdf JSON",
                        ),
                        Finding(
                            "PDF structure",
                            "JavaScript actions in object dictionaries",
                            _qpdf_marker_count(qpdf_objects, "/JS", "/JavaScript"),
                            "qpdf JSON",
                        ),
                        Finding(
                            "PDF structure",
                            "Open actions in object dictionaries",
                            _qpdf_marker_count(qpdf_objects, "/OpenAction"),
                            "qpdf JSON",
                        ),
                        Finding(
                            "PDF structure",
                            "Additional actions in object dictionaries",
                            _qpdf_marker_count(qpdf_objects, "/AA"),
                            "qpdf JSON",
                        ),
                    ]
                    json_run.parsed_result["object_count"] = len(qpdf_objects)
                    json_run.parsed_result["expanded_object_count"] = expanded
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    json_run.stderr = "\n".join(
                        part for part in (json_run.stderr, f"JSON parsing: {exc}") if part
                    )
                    findings = []
            else:
                temporary_index.unlink(missing_ok=True)
                findings = []
        else:
            findings = []
        for run in runs:
            if run.status == ToolRunStatus.COMPLETED:
                findings.extend(self._parse(run.tool_name, run.stdout, run.stderr))
        qdf_path = path.parent / "research-copy.qdf.pdf"
        if qdf_path.is_file():
            findings.append(
                Finding("PDF artifacts", "QDF research copy", str(qdf_path), "qpdf")
            )
        return AdapterResult(findings=findings, tool_runs=runs, artifacts=artifacts)

    @staticmethod
    def _parse(tool_name: str, stdout: str, stderr: str) -> list[Finding]:
        combined = "\n".join(part for part in (stdout, stderr) if part)
        findings: list[Finding] = []
        if tool_name == "qpdf/check":
            version_match = re.search(r"PDF Version:\s*([^\r\n]+)", combined, re.IGNORECASE)
            if version_match:
                findings.append(
                    Finding("PDF structure", "PDF version", version_match.group(1).strip(), "qpdf")
                )
            findings.append(
                Finding(
                    "PDF structure",
                    "qpdf validation",
                    "warnings" if "WARNING:" in combined else "passed",
                    "qpdf",
                    FindingLevel.LOW if "WARNING:" in combined else FindingLevel.INFO,
                )
            )
        elif tool_name == "qpdf/encryption":
            encrypted = "not encrypted" not in combined.lower()
            findings.append(Finding("PDF structure", "Encrypted", encrypted, "qpdf"))
            if encrypted:
                findings.append(
                    Finding("PDF structure", "Encryption details", combined.strip(), "qpdf")
                )
        elif tool_name == "qpdf/xref":
            entries = sum(1 for line in stdout.splitlines() if re.match(r"^\d+/\d+:\s", line))
            findings.append(Finding("PDF structure", "Xref entries", entries, "qpdf"))
        return findings


class PdfCpuAdapter(ToolAdapter):
    """Independent, offline PDF validation and inventory through pdfcpu."""

    def __init__(
        self,
        command: str = "pdfcpu",
        timeout_seconds: int = 120,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self.command = command
        self.runner = CommandRunner(timeout_seconds, cancellation_token)

    def analyze(self, path: Path) -> AdapterResult:
        version = [self.command, "version"]
        config_dir = path.parent / "pdfcpu-config"
        config_dir.mkdir(parents=True, exist_ok=True)
        prefix = [self.command, "--conf", str(config_dir), "--offline"]
        commands = (
            (
                "pdfcpu/validate-strict",
                [*prefix, "validate", "--mode", "strict", str(path)],
            ),
            (
                "pdfcpu/validate-relaxed",
                [*prefix, "validate", "--mode", "relaxed", str(path)],
            ),
            ("pdfcpu/info", [*prefix, "info", "--json", str(path)]),
            ("pdfcpu/permissions", [*prefix, "permissions", "list", str(path)]),
            (
                "pdfcpu/signatures",
                [*prefix, "signatures", "validate", "--all", "--full", str(path)],
            ),
            ("pdfcpu/attachments", [*prefix, "attachments", "list", str(path)]),
            ("pdfcpu/forms", [*prefix, "form", "list", "--json", str(path)]),
        )
        runs = [
            self.runner.run(name, command, version)
            for name, command in commands
        ]
        findings: list[Finding] = []
        for run in runs:
            combined = "\n".join(part for part in (run.stdout, run.stderr) if part)
            if run.tool_name.startswith("pdfcpu/validate") and run.exit_code == 1:
                # A standards violation is a completed analytical result, not a launch failure.
                if "validation error" in combined.casefold():
                    run.status = ToolRunStatus.COMPLETED
            if run.exit_code == 1 and (
                (run.tool_name == "pdfcpu/signatures" and "no signatures present" in combined.casefold())
                or (run.tool_name == "pdfcpu/forms" and "no form available" in combined.casefold())
            ):
                run.status = ToolRunStatus.COMPLETED
            if run.status == ToolRunStatus.COMPLETED:
                findings.extend(self._parse(run.tool_name, run.stdout, run.stderr))
        return AdapterResult(findings=findings, tool_runs=runs)

    @staticmethod
    def _parse(tool_name: str, stdout: str, stderr: str) -> list[Finding]:
        combined = "\n".join(part for part in (stdout, stderr) if part).strip()
        if tool_name.startswith("pdfcpu/validate"):
            strict = tool_name.endswith("strict")
            passed = "validation error" not in combined.casefold()
            return [
                Finding(
                    "PDF validation",
                    "pdfcpu strict validation" if strict else "pdfcpu relaxed validation",
                    passed,
                    "pdfcpu",
                    FindingLevel.MEDIUM if not passed else FindingLevel.INFO,
                    details=combined[:16_384] if not passed else combined[:4096],
                )
            ]
        if tool_name == "pdfcpu/info":
            try:
                value = json.loads(stdout)
            except json.JSONDecodeError:
                value = {"raw": combined[:32_768]}
            return [Finding("PDF inventory", "pdfcpu document info", value, "pdfcpu")]
        if tool_name == "pdfcpu/permissions":
            return [
                Finding(
                    "PDF security",
                    "pdfcpu permissions",
                    combined[:32_768],
                    "pdfcpu",
                )
            ]
        if tool_name == "pdfcpu/signatures":
            return [
                Finding(
                    "PDF signatures",
                    "pdfcpu signature validation",
                    combined[:64_000],
                    "pdfcpu",
                )
            ]
        if tool_name == "pdfcpu/attachments":
            return [
                Finding(
                    "PDF attachments",
                    "pdfcpu attachment inventory",
                    combined[:32_768],
                    "pdfcpu",
                )
            ]
        if tool_name == "pdfcpu/forms":
            try:
                value = json.loads(stdout)
            except json.JSONDecodeError:
                value = {"raw": combined[:32_768]}
            return [Finding("PDF forms", "pdfcpu form inventory", value, "pdfcpu")]
        return []


class PdfIdAdapter(ToolAdapter):
    def __init__(
        self,
        script_path: Path | None,
        timeout_seconds: int = 120,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self.script_path = script_path
        self.runner = CommandRunner(timeout_seconds, cancellation_token)

    def analyze(self, path: Path) -> AdapterResult:
        script = self.script_path or Path("pdfid.py")
        prefix = _python_tool_prefix("pdfid", script)
        command = [*prefix, "-a", "-e", str(path)]
        run = self.runner.run("pdfid.py", command, [*prefix, "--version"])
        findings = self._parse(run.stdout) if run.status == ToolRunStatus.COMPLETED else []
        return AdapterResult(findings=findings, tool_runs=[run])

    @staticmethod
    def _parse(output: str) -> list[Finding]:
        findings: list[Finding] = []
        header = re.search(r"PDF Header:\s*%PDF-([^\s]+)", output)
        if header:
            findings.append(Finding("PDF structure", "PDF version", header.group(1), "pdfid.py"))

        labels = {
            "obj": "Objects",
            "endobj": "End objects",
            "stream": "Streams",
            "endstream": "End streams",
            "/Page": "Pages",
            "/ObjStm": "Object streams",
            "xref": "xref markers",
            "trailer": "Trailers",
            "startxref": "startxref markers",
            "/Encrypt": "Encryption references",
            "/JS": "JavaScript /JS",
            "/JavaScript": "JavaScript /JavaScript",
            "/AA": "Additional actions",
            "/OpenAction": "Open actions",
            "/EmbeddedFile": "Embedded files",
            "/AcroForm": "AcroForm references",
            "/XFA": "XFA references",
            "/JBIG2Decode": "JBIG2Decode filters",
            "/RichMedia": "Rich media",
            "/Launch": "Launch actions",
            "/Sig": "Signature references",
            "%%EOF": "EOF markers",
        }
        for raw_name, display_name in labels.items():
            match = re.search(
                rf"(?m)^\s*{re.escape(raw_name)}\s+(\d+)(?:\s|$)", output
            )
            if match:
                findings.append(
                    Finding("PDF structure", display_name, int(match.group(1)), "pdfid.py")
                )
        return findings


class PdfParserAdapter(ToolAdapter):
    def __init__(
        self,
        script_path: Path | None,
        timeout_seconds: int = 120,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self.script_path = script_path
        self.runner = CommandRunner(timeout_seconds, cancellation_token)

    def analyze(self, path: Path) -> AdapterResult:
        script = self.script_path or Path("pdf-parser.py")
        prefix = _python_tool_prefix("pdf-parser", script)
        command = [*prefix, "--stats", str(path)]
        run = self.runner.run(
            "pdf-parser.py", command, [*prefix, "--version"]
        )
        findings = self._parse(run.stdout) if run.status == ToolRunStatus.COMPLETED else []
        return AdapterResult(findings=findings, tool_runs=[run])

    @staticmethod
    def _parse(output: str) -> list[Finding]:
        findings: list[Finding] = []
        context = ""
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.endswith(":") and not re.search(r":\s*\d+\s*$", stripped):
                context = stripped[:-1]
                continue
            match = re.match(r"^\s*([^:]{2,80}):\s*(\d+)\s*$", line)
            if match:
                name = match.group(1).strip()
                if context and (name.isdigit() or name.startswith("/")):
                    name = f"{context} — {name}"
                findings.append(
                    Finding(
                        "PDF parser statistics",
                        name,
                        int(match.group(2)),
                        "pdf-parser.py",
                    )
                )
        return findings


def _parse_qpdf_objects(
    json_path: Path,
    source_pdf: Path,
    max_objects: int,
) -> list[dict[str, object]]:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    qpdf = payload.get("qpdf")
    if not isinstance(qpdf, list) or len(qpdf) < 2 or not isinstance(qpdf[1], dict):
        raise ValueError("qpdf JSON does not contain an objects dictionary")
    physical_offsets = _physical_object_offsets(source_pdf, max_objects)
    rows: list[dict[str, object]] = []
    for key, item in qpdf[1].items():
        match = re.fullmatch(r"obj:(\d+)\s+(\d+)\s+R", str(key))
        if not match or not isinstance(item, dict):
            continue
        object_number = int(match.group(1))
        generation = int(match.group(2))
        object_key = (object_number, generation)
        stream = item.get("stream")
        has_stream = isinstance(stream, dict)
        value = stream.get("dict", {}) if has_stream else item.get("value")
        references = _qpdf_references(value)
        raw_preview = json.dumps(
            value, ensure_ascii=False, indent=2, default=str
        )[:32_768]
        rows.append(
            {
                "object": object_number,
                "generation": generation,
                "offset": physical_offsets.get(object_key, 0),
                "length": 0,
                "revision": 0,
                "category": _qpdf_object_category(value),
                "has_stream": has_stream,
                "stream_offset": None,
                "stream_length": 0,
                "filters": _qpdf_filters(value),
                "references": references[:500],
                "dictionary": raw_preview,
                "raw_preview": raw_preview,
                "decoded_preview": "",
                "decode_error": (
                    "Данные stream не включались в индекс qpdf; откройте объект через QDF-копию."
                    if has_stream
                    else ""
                ),
                "storage": "physical" if object_key in physical_offsets else "object_stream",
                "qpdf_indexed": True,
            }
        )
        if len(rows) >= max_objects:
            break
    return rows


def _physical_object_offsets(path: Path, max_objects: int) -> dict[tuple[int, int], int]:
    pattern = re.compile(rb"(?m)^\s*(\d+)\s+(\d+)\s+obj\b")
    offsets: dict[tuple[int, int], int] = {}
    with path.open("rb") as stream:
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            for match in pattern.finditer(data):
                offsets[(int(match.group(1)), int(match.group(2)))] = match.start()
                if len(offsets) >= max_objects:
                    break
    return offsets


def _qpdf_references(value: object) -> list[dict[str, int]]:
    references: list[dict[str, int]] = []

    def visit(item: object) -> None:
        if isinstance(item, str):
            match = re.fullmatch(r"(\d+)\s+(\d+)\s+R", item)
            if match:
                reference = {
                    "object": int(match.group(1)),
                    "generation": int(match.group(2)),
                }
                if reference not in references:
                    references.append(reference)
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return references


def _qpdf_object_category(value: object) -> str:
    if not isinstance(value, dict):
        return "Objects"
    object_type = value.get("/Type")
    subtype = value.get("/Subtype")
    if object_type == "/Page":
        return "Pages"
    if object_type == "/Metadata":
        return "Metadata"
    if object_type == "/Sig":
        return "Signatures"
    if object_type == "/ObjStm":
        return "Object streams"
    if object_type == "/XRef":
        return "XRef"
    if object_type == "/EmbeddedFile":
        return "Attachments"
    if subtype in {"/XML", "/Form"}:
        return "Metadata" if subtype == "/XML" else "Forms"
    if "/FT" in value or "/AcroForm" in value:
        return "Forms"
    return "Objects"


def _qpdf_filters(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    raw = value.get("/Filter")
    if isinstance(raw, str):
        return [raw.removeprefix("/")]
    if isinstance(raw, list):
        return [str(item).removeprefix("/") for item in raw]
    return []


def _qpdf_marker_count(objects: list[dict[str, object]], *markers: str) -> int:
    quoted = tuple(f'"{marker}"' for marker in markers)
    return sum(
        1
        for item in objects
        if any(marker in str(item.get("dictionary", "")) for marker in quoted)
    )


def _python_tool_prefix(tool: str, script: Path) -> list[str]:
    """Use a bundled subprocess helper when running from a windowed PyInstaller EXE."""
    configured = os.environ.get("PDF_FORENSICS_TOOL_RUNNER")
    if configured:
        return [configured, tool]
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        helper = root / "app" / "resources" / "bin" / "DocumentForensicToolRunner.exe"
        return [str(helper), tool]
    return [sys.executable, str(script)]
