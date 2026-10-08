from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from app.adapters.base import AdapterResult, CancellationToken, CommandRunner, ToolAdapter
from app.models import Finding, FindingLevel, ToolRunStatus
from app.core.config import default_data_dir


def _poppler_output_path(path: Path) -> str:
    """Use extended Windows paths for pdftotext output beyond MAX_PATH."""
    if os.name != "nt":
        return str(path)
    absolute = str(path.absolute())
    if absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


class PopplerAdapter(ToolAdapter):
    """Independent content inventory and rendering through Poppler utilities."""

    def __init__(
        self,
        bin_dir: Path | None,
        timeout_seconds: int = 120,
        cancellation_token: CancellationToken | None = None,
        revisions: Iterable[tuple[int, Path]] = (),
        max_render_pages: int = 25,
    ) -> None:
        self.bin_dir = bin_dir
        self.runner = CommandRunner(timeout_seconds, cancellation_token)
        self.revisions = list(revisions)
        self.max_render_pages = max(1, max_render_pages)

    def analyze(self, path: Path) -> AdapterResult:
        version = [self._exe("pdfinfo"), "-v"]
        text_temp = path.parent / "poppler-text.tmp.txt"
        text_path = path.parent / "poppler-text.txt"
        text_temp.unlink(missing_ok=True)
        commands = (
            (
                "poppler/pdfinfo",
                [self._exe("pdfinfo"), "-isodates", "-box", str(path)],
            ),
            ("poppler/pdffonts", [self._exe("pdffonts"), str(path)]),
            ("poppler/pdfimages", [self._exe("pdfimages"), "-list", str(path)]),
            ("poppler/pdfdetach", [self._exe("pdfdetach"), "-list", str(path)]),
            (
                "poppler/pdftotext",
                [
                    self._exe("pdftotext"),
                    "-layout",
                    "-enc",
                    "UTF-8",
                    str(path),
                    _poppler_output_path(text_temp),
                ],
            ),
        )
        runs = [self.runner.run(name, command, version) for name, command in commands]
        artifacts: dict[str, object] = {}
        findings: list[Finding] = []
        for run in runs:
            if run.status == ToolRunStatus.COMPLETED:
                findings.extend(self._parse(run.tool_name, run.stdout, run.stderr))
        text_run = next(run for run in runs if run.tool_name == "poppler/pdftotext")
        if text_run.status == ToolRunStatus.COMPLETED and text_temp.is_file():
            text_temp.replace(text_path)
            text = text_path.read_text(encoding="utf-8", errors="replace")
            artifacts["poppler_text_path"] = str(text_path)
            findings.extend(
                [
                    Finding("PDF content", "Poppler extracted characters", len(text), "Poppler"),
                    Finding(
                        "PDF content",
                        "Poppler extracted text file",
                        str(text_path),
                        "Poppler",
                    ),
                ]
            )
        else:
            text_temp.unlink(missing_ok=True)

        render_root = path.parent / "revision-renders"
        render_groups: list[dict[str, object]] = []
        if len(self.revisions) >= 2:
            render_root.mkdir(parents=True, exist_ok=True)
            ppm_version = [self._exe("pdftoppm"), "-v"]
            for revision_number, revision_path in self.revisions:
                if not revision_path.is_file():
                    continue
                prefix = render_root / f"revision-{revision_number:03d}"
                # Poppler's PNG writer uses a fixed MAX_PATH buffer even for
                # extended paths. Render in a short private temp directory and
                # copy the completed images into the case with Python's Unicode IO.
                pages = []
                with tempfile.TemporaryDirectory(prefix="dfi-pdf-render-") as temporary:
                    staging = Path(temporary).resolve()
                    if not staging.is_relative_to(Path(tempfile.gettempdir()).resolve()):
                        raise ValueError("Unexpected rendering staging path")
                    staged_prefix = staging / prefix.name
                    render_run = self.runner.run(
                        f"poppler/render-revision-{revision_number:03d}",
                        [
                            self._exe("pdftoppm"), "-png", "-r", "96", "-f", "1",
                            "-l", str(self.max_render_pages), str(revision_path), str(staged_prefix),
                        ],
                        ppm_version,
                    )
                    runs.append(render_run)
                    if render_run.status == ToolRunStatus.COMPLETED:
                        for rendered in sorted(staging.glob(f"{prefix.name}-*.png")):
                            image_path = render_root / rendered.name
                            shutil.copyfile(rendered, image_path)
                            match = re.search(r"-(\d+)\.png$", image_path.name)
                            pages.append({
                                "page": int(match.group(1)) if match else len(pages) + 1,
                                "path": str(image_path),
                                "sha256": _sha256(image_path),
                            })
                        if not pages:
                            render_run.status = ToolRunStatus.FAILED
                            render_run.stderr += "\nRenderer returned success without any page images"
                    render_run.parsed_result["output_directory"] = str(render_root)
                    render_run.parsed_result["copied_pages"] = len(pages)
                render_groups.append(
                    {
                        "revision": revision_number,
                        "source": str(revision_path),
                        "pages": pages,
                    }
                )
            artifacts["revision_renders"] = render_groups
            findings.append(
                Finding(
                    "PDF revisions",
                    "Rendered revision pages",
                    sum(len(group["pages"]) for group in render_groups),
                    "Poppler",
                )
            )
        return AdapterResult(findings=findings, tool_runs=runs, artifacts=artifacts)

    def _exe(self, name: str) -> str:
        if self.bin_dir:
            return str(self.bin_dir / f"{name}.exe")
        return name

    @staticmethod
    def _parse(tool_name: str, stdout: str, stderr: str) -> list[Finding]:
        combined = "\n".join(part for part in (stdout, stderr) if part).strip()
        if tool_name == "poppler/pdfinfo":
            values: dict[str, str] = {}
            for line in stdout.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                if key.strip() and key.strip() not in values:
                    values[key.strip()] = value.strip()
            return [Finding("PDF inventory", "Poppler document information", values, "Poppler")]
        if tool_name == "poppler/pdffonts":
            fonts = _parse_fonts(stdout)
            return [
                Finding("PDF fonts", "Poppler font inventory", fonts, "Poppler"),
                Finding(
                    "PDF fonts",
                    "Fonts not embedded",
                    sum(1 for font in fonts if font.get("embedded") == "no"),
                    "Poppler",
                    FindingLevel.MEDIUM
                    if any(font.get("embedded") == "no" for font in fonts)
                    else FindingLevel.INFO,
                ),
                Finding(
                    "PDF fonts",
                    "Fonts without Unicode mapping",
                    sum(1 for font in fonts if font.get("unicode") == "no"),
                    "Poppler",
                ),
            ]
        if tool_name == "poppler/pdfimages":
            rows = [
                line.strip()
                for line in stdout.splitlines()[2:]
                if line.strip() and re.match(r"^\s*\d+\s+\d+\s+", line)
            ]
            return [Finding("PDF content", "Poppler image inventory", rows, "Poppler")]
        if tool_name == "poppler/pdfdetach":
            match = re.search(r"(\d+)\s+embedded files?", combined, re.IGNORECASE)
            return [
                Finding(
                    "PDF attachments",
                    "Poppler attachment count",
                    int(match.group(1)) if match else combined,
                    "Poppler",
                )
            ]
        return []


class JhoveAdapter(ToolAdapter):
    def __init__(
        self,
        java_command: str,
        jhove_dir: Path | None,
        timeout_seconds: int = 120,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self.java_command = java_command
        self.jhove_dir = jhove_dir
        self.runner = CommandRunner(timeout_seconds, cancellation_token)

    def analyze(self, path: Path) -> AdapterResult:
        prefix = self.command_prefix()
        version = [*prefix, "-h"]
        run = self.runner.run(
            "jhove/pdf-hul",
            [*prefix, "-m", "PDF-hul", "-h", "JSON", "-k", str(path)],
            version,
        )
        findings: list[Finding] = []
        artifacts: dict[str, object] = {}
        runs = [run]
        if run.status == ToolRunStatus.COMPLETED:
            try:
                payload = json.loads(run.stdout)
                report_path = path.parent / "jhove-report.json"
                report_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                artifacts.update(
                    {"jhove_report": payload, "jhove_report_path": str(report_path)}
                )
                findings.extend(_parse_jhove(payload))
            except json.JSONDecodeError as exc:
                run.stderr = "\n".join(
                    part for part in (run.stderr, f"JSON parsing: {exc}") if part
                )
        if not artifacts:
            fallback = self.runner.run(
                "jhove/pdf-hul-xml-fallback",
                [*prefix, "-m", "PDF-hul", "-h", "XML", "-k", str(path)],
                version,
            )
            runs.append(fallback)
            if fallback.status == ToolRunStatus.COMPLETED:
                try:
                    payload = _parse_jhove_xml(fallback.stdout)
                    report_path = path.parent / "jhove-report.xml"
                    report_path.write_text(fallback.stdout, encoding="utf-8")
                    artifacts.update(
                        {"jhove_report": payload, "jhove_report_path": str(report_path)}
                    )
                    findings.extend(_parse_jhove(payload))
                    run.status = ToolRunStatus.COMPLETED
                    run.parsed_result["recovered_by"] = fallback.tool_name
                except (ET.ParseError, ValueError) as exc:
                    fallback.stderr = "\n".join(
                        part for part in (fallback.stderr, f"XML parsing: {exc}") if part
                    )
        return AdapterResult(findings=findings, tool_runs=runs, artifacts=artifacts)

    def command_prefix(self) -> list[str]:
        root = self.jhove_dir or Path("jhove")
        return [
            self.java_command,
            "-Xss1024k",
            "-classpath",
            str(root / "bin" / "*"),
            "edu.harvard.hul.ois.jhove.Jhove",
            "-c",
            str(root / "conf" / "jhove.conf"),
        ]


class VeraPdfAdapter(ToolAdapter):
    FEATURES = (
        "actions,annotations,colorSpace,embeddedFile,font,informationDict,"
        "interactiveFormField,lowLevelInfo,metadata,signature"
    )

    def __init__(
        self,
        java_command: str,
        verapdf_dir: Path | None,
        timeout_seconds: int = 120,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self.java_command = java_command
        self.verapdf_dir = verapdf_dir
        self.runner = CommandRunner(timeout_seconds, cancellation_token)

    def analyze(self, path: Path) -> AdapterResult:
        prefix = self.command_prefix(path.parent / "verapdf-config")
        version = [*prefix, "--version"]
        runs = [
            self.runner.run(
                "verapdf/validation",
                [
                    *prefix,
                    "--format",
                    "json",
                    "--maxfailuresdisplayed",
                    "50",
                    str(path),
                ],
                version,
            ),
            self.runner.run(
                "verapdf/features",
                [
                    *prefix,
                    "--off",
                    "--format",
                    # veraPDF 1.30.2's JSON serializer fails on lowLevelInfo.
                    # XML retains the complete report, including that section.
                    "xml",
                    "--extract",
                    self.FEATURES,
                    str(path),
                ],
                version,
            ),
        ]
        findings: list[Finding] = []
        artifacts: dict[str, object] = {}
        for run in runs:
            try:
                if run.tool_name == "verapdf/features":
                    root = ET.fromstring(run.stdout)
                    if not any(node.tag.rsplit("}", 1)[-1] == "featuresReport" for node in root.iter()):
                        raise ValueError("XML has no featuresReport")
                    payload = {"format": "xml", "xml": run.stdout}
                else:
                    payload = json.loads(run.stdout)
                    if not isinstance(payload, dict) or not isinstance(payload.get("report"), dict):
                        raise ValueError("JSON has no report object")
            except (json.JSONDecodeError, ET.ParseError, ValueError) as exc:
                if run.status == ToolRunStatus.COMPLETED:
                    run.status = ToolRunStatus.FAILED
                run.stderr += f"\nCannot read veraPDF report: {exc}"
                continue
            # veraPDF returns 1 when validation is complete but non-conformant.
            if run.exit_code == 1 and isinstance(payload.get("report"), dict):
                run.status = ToolRunStatus.COMPLETED
            if run.status != ToolRunStatus.COMPLETED:
                continue
            if run.tool_name == "verapdf/validation":
                report_path = path.parent / "verapdf-validation.json"
                report_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                artifacts.update(
                    {
                        "verapdf_validation": payload,
                        "verapdf_validation_path": str(report_path),
                    }
                )
                findings.extend(_parse_verapdf_validation(payload))
            else:
                xml_path = path.parent / "verapdf-features.xml"
                xml_path.write_text(run.stdout, encoding="utf-8")
                report_path = path.parent / "verapdf-features.json"
                report_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                artifacts.update(
                    {
                        "verapdf_features": payload,
                        "verapdf_features_path": str(report_path),
                        "verapdf_features_xml_path": str(xml_path),
                    }
                )
                findings.append(
                    Finding(
                        "PDF conformance",
                        "veraPDF feature report",
                        "сформирован",
                        "veraPDF",
                    )
                )
        return AdapterResult(findings=findings, tool_runs=runs, artifacts=artifacts)

    def command_prefix(self, home_dir: Path | None = None) -> list[str]:
        root = self.verapdf_dir or Path("verapdf")
        bin_dir = root / "bin"
        # veraPDF creates configuration files at app.home. Keep the installed
        # engines immutable and the analysis configuration with its case.
        home = home_dir or default_data_dir() / "tool-config" / "verapdf"
        home.mkdir(parents=True, exist_ok=True)
        return [
            self.java_command,
            "-classpath",
            str(bin_dir / "*"),
            "-Dfile.encoding=UTF8",
            "-Dapp.name=veraPDF CLI",
            f"-Dapp.repo={bin_dir}",
            f"-Dapp.home={home}",
            f"-Dbasedir={root}",
            "--add-exports=java.base/sun.security.pkcs=ALL-UNNAMED",
            "org.verapdf.apps.GreenfieldCliWrapper",
        ]


class PdfBoxAdapter(ToolAdapter):
    def __init__(
        self,
        java_command: str,
        jar_path: Path | None,
        timeout_seconds: int = 120,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self.java_command = java_command
        self.jar_path = jar_path
        self.runner = CommandRunner(timeout_seconds, cancellation_token)

    def analyze(self, path: Path) -> AdapterResult:
        jar = self.jar_path or Path("pdfbox-app.jar")
        prefix = [self.java_command, "-jar", str(jar)]
        version = [*prefix, "version"]
        text_temp = path.parent / "pdfbox-text.tmp.txt"
        text_path = path.parent / "pdfbox-text.txt"
        xmp_temp = path.parent / "pdfbox-xmp.tmp.xml"
        xmp_path = path.parent / "pdfbox-xmp.xml"
        decoded_temp = path.parent / "pdfbox-decoded.tmp.pdf"
        decoded_path = path.parent / "pdfbox-decoded.pdf"
        for temporary in (text_temp, xmp_temp, decoded_temp):
            temporary.unlink(missing_ok=True)
        runs = [
            self.runner.run(
                "pdfbox/text",
                [
                    *prefix,
                    "export:text",
                    f"-i={path}",
                    f"-o={text_temp}",
                    "-encoding=UTF-8",
                    "-sort",
                ],
                version,
            ),
            self.runner.run(
                "pdfbox/xmp",
                [*prefix, "export:xmp", f"-i={path}", f"-o={xmp_temp}"],
                version,
            ),
            self.runner.run(
                "pdfbox/decoded-copy",
                [*prefix, "decode", "-skipImages", str(path), str(decoded_temp)],
                version,
            ),
        ]
        artifacts: dict[str, object] = {}
        findings: list[Finding] = []
        outputs = (
            (runs[0], text_temp, text_path, "pdfbox_text_path"),
            (runs[1], xmp_temp, xmp_path, "pdfbox_xmp_path"),
            (runs[2], decoded_temp, decoded_path, "pdfbox_decoded_path"),
        )
        for run, temporary, final_path, key in outputs:
            if run.status == ToolRunStatus.COMPLETED and temporary.is_file():
                temporary.replace(final_path)
                artifacts[key] = str(final_path)
            else:
                temporary.unlink(missing_ok=True)
        if text_path.is_file():
            text = text_path.read_text(encoding="utf-8", errors="replace")
            findings.append(
                Finding("PDF content", "PDFBox extracted characters", len(text), "PDFBox")
            )
        findings.append(
            Finding(
                "PDF artifacts",
                "PDFBox decoded research copy",
                str(decoded_path) if decoded_path.is_file() else "не создана",
                "PDFBox",
            )
        )
        return AdapterResult(findings=findings, tool_runs=runs, artifacts=artifacts)


def _parse_fonts(output: str) -> list[dict[str, object]]:
    fonts: list[dict[str, object]] = []
    pattern = re.compile(
        r"^(.+?)\s{2,}(.+?)\s{2,}(\S+)\s+(yes|no)\s+(yes|no)\s+(yes|no)\s+(\d+)\s+(\d+)\s*$",
        re.IGNORECASE,
    )
    for line in output.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        fonts.append(
            {
                "name": match.group(1).strip(),
                "type": match.group(2).strip(),
                "encoding": match.group(3),
                "embedded": match.group(4).lower(),
                "subset": match.group(5).lower(),
                "unicode": match.group(6).lower(),
                "object": int(match.group(7)),
                "generation": int(match.group(8)),
            }
        )
    return fonts


def _parse_jhove(payload: dict[str, object]) -> list[Finding]:
    root = payload.get("jhove", {})
    if not isinstance(root, dict):
        return []
    reports = root.get("repInfo", [])
    if not isinstance(reports, list) or not reports or not isinstance(reports[0], dict):
        return []
    report = reports[0]
    status = str(report.get("status", "не установлен"))
    valid = status.casefold() == "well-formed and valid"
    messages = report.get("messages", [])
    return [
        Finding(
            "PDF preservation",
            "JHOVE PDF-hul status",
            status,
            "JHOVE PDF-hul",
            FindingLevel.MEDIUM if not valid else FindingLevel.INFO,
        ),
        Finding(
            "PDF preservation",
            "JHOVE declared profiles",
            report.get("profiles", []),
            "JHOVE PDF-hul",
        ),
        Finding(
            "PDF preservation",
            "JHOVE validation messages",
            messages,
            "JHOVE PDF-hul",
            FindingLevel.LOW if messages else FindingLevel.INFO,
        ),
    ]


def _parse_jhove_xml(output: str) -> dict[str, object]:
    root = ET.fromstring(output)
    report = root.find(".//{*}repInfo")
    if report is None:
        raise ValueError("JHOVE XML does not contain repInfo")

    def text(name: str) -> str:
        element = report.find(f"{{*}}{name}")
        return (element.text or "").strip() if element is not None else ""

    messages = []
    for message in report.findall(".//{*}message"):
        value = "".join(message.itertext()).strip()
        if value:
            messages.append(value)
    profiles = [
        "".join(profile.itertext()).strip()
        for profile in report.findall(".//{*}profile")
        if "".join(profile.itertext()).strip()
    ]
    normalized = {
        "uri": report.attrib.get("uri", ""),
        "format": text("format"),
        "version": text("version"),
        "status": text("status"),
        "mimeType": text("mimeType"),
        "profiles": profiles,
        "messages": messages,
    }
    return {
        "jhove": {
            "name": root.attrib.get("name", "Jhove"),
            "release": root.attrib.get("release", ""),
            "date": root.attrib.get("date", ""),
            "repInfo": [normalized],
        }
    }


def _parse_verapdf_validation(payload: dict[str, object]) -> list[Finding]:
    report = payload.get("report", {})
    if not isinstance(report, dict):
        return []
    jobs = report.get("jobs", [])
    if not isinstance(jobs, list) or not jobs or not isinstance(jobs[0], dict):
        return []
    validation = jobs[0].get("validationResult", {})
    if isinstance(validation, list):
        validation = validation[0] if validation else {}
    if not isinstance(validation, dict):
        return []
    details = validation.get("details", {})
    if not isinstance(details, dict):
        return []
    compliant = bool(validation.get("compliant", False))
    raw_rules = details.get("ruleSummaries", [])
    failed_rules = []
    if isinstance(raw_rules, list):
        for rule in raw_rules[:250]:
            if not isinstance(rule, dict):
                continue
            failed_rules.append(
                {
                    key: rule.get(key)
                    for key in (
                        "specification",
                        "clause",
                        "testNumber",
                        "description",
                        "failedChecks",
                    )
                }
            )
    summary = {
        "profile": validation.get("profileName"),
        "statement": validation.get("statement"),
        "compliant": compliant,
        "passed_rules": details.get("passedRules", 0),
        "failed_rules": details.get("failedRules", 0),
        "passed_checks": details.get("passedChecks", 0),
        "failed_checks": details.get("failedChecks", 0),
    }
    return [
        Finding(
            "PDF conformance",
            "veraPDF standards conformance",
            compliant,
            "veraPDF",
            FindingLevel.MEDIUM if not compliant else FindingLevel.INFO,
            details=str(validation.get("statement", "")),
        ),
        Finding(
            "PDF conformance",
            "veraPDF validation summary",
            summary,
            "veraPDF",
        ),
        Finding(
            "PDF conformance",
            "veraPDF failed rule details",
            failed_rules,
            "veraPDF",
            FindingLevel.LOW if details.get("failedRules", 0) else FindingLevel.INFO,
        ),
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
