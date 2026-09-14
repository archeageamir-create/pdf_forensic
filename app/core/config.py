from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def default_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return base / "DocumentForensicsLab"


@dataclass(frozen=True, slots=True)
class AppConfig:
    data_dir: Path
    database_path: Path
    cases_dir: Path
    reports_dir: Path
    settings_path: Path | None = None
    tool_timeout_seconds: int = 120
    max_analysis_seconds: int = 900
    exiftool_command: str = "exiftool"
    ffprobe_command: str = "ffprobe"
    qpdf_command: str = "qpdf"
    pdfcpu_command: str = "pdfcpu"
    poppler_bin_dir: Path | None = None
    java_command: str = "java"
    jhove_dir: Path | None = None
    verapdf_dir: Path | None = None
    pdfbox_jar: Path | None = None
    pdfid_script: Path | None = None
    pdf_parser_script: Path | None = None
    max_file_size_bytes: int = 2 * 1024 * 1024 * 1024
    max_zip_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024
    max_zip_entries: int = 100_000
    max_xml_part_bytes: int = 16 * 1024 * 1024
    max_zip_compression_ratio: int = 250
    max_pdf_objects: int = 250_000
    max_stream_bytes: int = 64 * 1024 * 1024
    max_extracted_bytes: int = 1024 * 1024 * 1024
    max_revision_render_pages: int = 25
    create_qdf_in_full_mode: bool = True
    validate_signatures: bool = True
    report_template: Path | None = None
    update_manifest_url: str = ""

    @classmethod
    def default(cls) -> "AppConfig":
        data_dir = default_data_dir()
        tools_dir = bundled_resource("app", "resources", "tools")
        binaries_dir = bundled_resource("app", "resources", "binaries")
        bundled_exiftool = binaries_dir / "ExifTool.exe"
        bundled_qpdf = binaries_dir / "qpdf" / "qpdf.exe"
        bundled_pdfcpu = binaries_dir / "pdfcpu" / "pdfcpu.exe"
        bundled_poppler = binaries_dir / "poppler" / "bin"
        bundled_java = binaries_dir / "java" / "bin" / "java.exe"
        bundled_jhove = binaries_dir / "jhove"
        bundled_verapdf = binaries_dir / "verapdf"
        bundled_pdfbox = binaries_dir / "pdfbox" / "pdfbox-app-3.0.8.jar"
        return cls(
            data_dir=data_dir,
            database_path=data_dir / "forensics.sqlite3",
            cases_dir=data_dir / "cases",
            reports_dir=data_dir / "reports",
            settings_path=data_dir / "settings.json",
            exiftool_command=str(bundled_exiftool) if bundled_exiftool.exists() else "exiftool",
            qpdf_command=str(bundled_qpdf) if bundled_qpdf.exists() else "qpdf",
            pdfcpu_command=(
                str(bundled_pdfcpu) if bundled_pdfcpu.exists() else "pdfcpu"
            ),
            poppler_bin_dir=_existing_path(bundled_poppler),
            java_command=str(bundled_java) if bundled_java.exists() else "java",
            jhove_dir=_existing_path(bundled_jhove),
            verapdf_dir=_existing_path(bundled_verapdf),
            pdfbox_jar=_existing_path(bundled_pdfbox),
            pdfid_script=_optional_path(os.environ.get("PDFID_SCRIPT"))
            or _existing_path(tools_dir / "pdfid.py"),
            pdf_parser_script=_optional_path(os.environ.get("PDF_PARSER_SCRIPT"))
            or _existing_path(tools_dir / "pdf-parser.py"),
        )

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.cases_dir, self.reports_dir):
            path.mkdir(parents=True, exist_ok=True)


def _optional_path(value: str | None) -> Path | None:
    return Path(value).expanduser().resolve() if value else None


def _existing_path(path: Path) -> Path | None:
    return path.resolve() if path.exists() else None


def bundled_resource(*parts: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root.joinpath(*parts)
