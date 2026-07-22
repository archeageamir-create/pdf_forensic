from __future__ import annotations

import zipfile
from pathlib import Path

from app.models import FileKind


def detect_file_kind(path: Path) -> FileKind | None:
    with path.open("rb") as stream:
        header = stream.read(8)
    if header.startswith(b"%PDF-"):
        return FileKind.PDF
    if header.startswith(b"PK\x03\x04") and _is_pptx(path):
        return FileKind.PPTX
    return None


def mime_for_kind(kind: FileKind) -> str:
    if kind == FileKind.PDF:
        return "application/pdf"
    return "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def canonical_extension(kind: FileKind) -> str:
    return f".{kind.value}"


def _is_pptx(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            return "[Content_Types].xml" in names and "ppt/presentation.xml" in names
    except (OSError, zipfile.BadZipFile):
        return False
