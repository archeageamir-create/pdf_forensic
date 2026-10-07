from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from app.models import AnalysisResult, ResearchProject
from app.reporting.safety import atomic_report_path, validate_report_destination
from app.reporting.docx_exporter import DocxReportExporter
from app.reporting.exporters import HtmlReportExporter, JsonReportExporter


class ZipPackageExporter:
    def __init__(self, docx_template: Path | None = None) -> None:
        self.docx_template = docx_template

    def export(
        self,
        result: AnalysisResult,
        destination: Path,
        project: ResearchProject | None = None,
        audit_log: list[dict] | None = None,
    ) -> Path:
        validate_report_destination(result, destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="dfi-export-") as temp:
            root = Path(temp) / "project_export"
            report_dir = root / "report"
            raw_dir = root / "raw_results"
            evidence_dir = root / "evidence"
            logs_dir = root / "logs"
            licenses_dir = root / "licenses"
            for path in (report_dir, raw_dir, evidence_dir, logs_dir, licenses_dir):
                path.mkdir(parents=True, exist_ok=True)

            JsonReportExporter().export(result, report_dir / "report.json")
            HtmlReportExporter().export(result, report_dir / "report.html")
            DocxReportExporter(self.docx_template).export(
                result, report_dir / "report.docx", project
            )
            manifest = {
                "original_name": result.evidence.original_name,
                "original_path": result.evidence.original_path,
                "working_copy_path": result.evidence.working_copy_path,
                "sha256": result.evidence.sha256,
                "sha1": result.evidence.sha1,
                "md5": result.evidence.md5,
                "size_bytes": result.evidence.size_bytes,
                "integrity_status": result.evidence.integrity_status.value,
            }
            (evidence_dir / "file_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            for index, run in enumerate(result.tool_runs, start=1):
                name = f"{index:03d}-{_safe_name(run.tool_name)}"
                (raw_dir / f"{name}.stdout.txt").write_text(run.stdout, encoding="utf-8")
                (raw_dir / f"{name}.stderr.txt").write_text(run.stderr, encoding="utf-8")
                (raw_dir / f"{name}.run.json").write_text(
                    json.dumps(
                        {
                            "command": run.command,
                            "version": run.version,
                            "exit_code": run.exit_code,
                            "status": run.status.value,
                            "started_at": run.started_at,
                            "finished_at": run.finished_at,
                            "duration_ms": run.duration_ms,
                            "parsed_result": run.parsed_result,
                        },
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    ),
                    encoding="utf-8",
                )
            (logs_dir / "project_audit.json").write_text(
                json.dumps(audit_log or [], ensure_ascii=False, indent=2), encoding="utf-8"
            )
            resources = Path(__file__).resolve().parents[1] / "resources"
            compliance_files = {
                "THIRD_PARTY.md": licenses_dir / "THIRD_PARTY.md",
                "THIRD_PARTY_NOTICES.md": licenses_dir / "THIRD_PARTY_NOTICES.md",
                "SBOM.spdx.json": root / "SBOM.spdx.json",
            }
            for source_name, target in compliance_files.items():
                source = resources / source_name
                if source.is_file():
                    shutil.copyfile(source, target)
            compliance_root = resources / "compliance"
            if compliance_root.is_dir():
                for source in compliance_root.rglob("*"):
                    if source.is_file():
                        target = root / "compliance" / source.relative_to(compliance_root)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, target)
            authorship = resources / "AUTHORSHIP.txt"
            if authorship.is_file():
                shutil.copyfile(authorship, root / "AUTHORSHIP.txt")
            license_root = resources / "licenses"
            if license_root.is_dir():
                for license_file in license_root.rglob("*"):
                    if not license_file.is_file():
                        continue
                    target = licenses_dir / license_file.relative_to(license_root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(license_file, target)
            qdf = result.artifacts.get("qdf_path")
            if qdf and Path(str(qdf)).is_file():
                shutil.copyfile(Path(str(qdf)), raw_dir / "research-copy.qdf.pdf")
            qpdf_json = result.artifacts.get("qpdf_json_path")
            if qpdf_json and Path(str(qpdf_json)).is_file():
                shutil.copyfile(Path(str(qpdf_json)), raw_dir / "qpdf-objects.json")
            artifact_files = {
                "image_preview_path": "image-preview.png",
                "poppler_text_path": "poppler-text.txt",
                "verapdf_validation_path": "verapdf-validation.json",
                "verapdf_features_path": "verapdf-features.json",
                "verapdf_features_xml_path": "verapdf-features.xml",
                "pdfbox_text_path": "pdfbox-text.txt",
                "pdfbox_xmp_path": "pdfbox-xmp.xml",
                "pdfbox_decoded_path": "pdfbox-decoded.pdf",
            }
            for key, name in artifact_files.items():
                source_value = result.artifacts.get(key)
                if source_value and Path(str(source_value)).is_file():
                    shutil.copyfile(Path(str(source_value)), raw_dir / name)
            jhove_value = result.artifacts.get("jhove_report_path")
            if jhove_value and Path(str(jhove_value)).is_file():
                jhove_source = Path(str(jhove_value))
                suffix = jhove_source.suffix.lower()
                jhove_name = "jhove-report.xml" if suffix == ".xml" else "jhove-report.json"
                shutil.copyfile(jhove_source, raw_dir / jhove_name)
            revision_dir = raw_dir / "revisions"
            for item in result.artifacts.get("pdf_revisions", []):
                if not isinstance(item, dict) or not item.get("reconstructed_path"):
                    continue
                source = Path(str(item["reconstructed_path"]))
                if source.is_file():
                    revision_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, revision_dir / source.name)
            visual_dir = raw_dir / "revision-visual"
            for item in result.artifacts.get("revision_renders", []):
                if not isinstance(item, dict):
                    continue
                for page in item.get("pages", []):
                    if not isinstance(page, dict) or not page.get("path"):
                        continue
                    source = Path(str(page["path"]))
                    if source.is_file():
                        visual_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, visual_dir / source.name)
            for item in result.artifacts.get("revision_visual_diffs", []):
                if not isinstance(item, dict) or not item.get("diff_path"):
                    continue
                source = Path(str(item["diff_path"]))
                if source.is_file():
                    visual_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, visual_dir / source.name)

            checksums = []
            for file in sorted(path for path in root.rglob("*") if path.is_file()):
                checksums.append(f"{_sha256(file)}  {file.relative_to(root).as_posix()}")
            (root / "manifest.sha256").write_text("\n".join(checksums) + "\n", encoding="utf-8")

            with atomic_report_path(result, destination) as temporary:
                with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                    for file in sorted(path for path in root.rglob("*") if path.is_file()):
                        archive.write(file, file.relative_to(root).as_posix())
        return destination


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value).strip("_")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
