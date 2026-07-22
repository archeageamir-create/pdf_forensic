from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.core.errors import AnalysisError


class PdfAttachmentService:
    def list_attachments(self, path: Path) -> list[dict[str, Any]]:
        reader = PdfReader(path, strict=False)
        items: list[dict[str, Any]] = []
        try:
            for index, attachment in enumerate(reader.attachment_list):
                items.append(
                    {
                        "index": index,
                        "name": attachment.name,
                        "alternative_name": attachment.alternative_name,
                        "size": int(attachment.size or 0),
                        "subtype": str(attachment.subtype or ""),
                        "description": attachment.description or "",
                        "creation_date": str(attachment.creation_date or ""),
                        "modification_date": str(attachment.modification_date or ""),
                        "checksum": attachment.checksum.hex() if attachment.checksum else "",
                        "relationship": str(attachment.associated_file_relationship or ""),
                    }
                )
        finally:
            reader.close()
        return items

    def extract_all(
        self, path: Path, destination: Path, max_total_bytes: int
    ) -> list[dict[str, Any]]:
        destination.mkdir(parents=True, exist_ok=True)
        root = destination.resolve()
        reader = PdfReader(path, strict=False)
        extracted: list[dict[str, Any]] = []
        total = 0
        try:
            for index, attachment in enumerate(reader.attachment_list):
                declared_size = int(attachment.size or 0)
                if declared_size and total + declared_size > max_total_bytes:
                    raise AnalysisError("Attachment extraction size limit exceeded")
                content = attachment.content
                total += len(content)
                if total > max_total_bytes:
                    raise AnalysisError("Attachment extraction size limit exceeded")
                safe_name = _safe_name(attachment.name or f"attachment-{index}.bin")
                target = _unique_target(root, f"{index:03d}-{safe_name}")
                if root not in target.parents:
                    raise AnalysisError("Attachment path escaped the extraction directory")
                temporary = target.with_suffix(target.suffix + ".tmp")
                temporary.write_bytes(content)
                temporary.replace(target)
                extracted.append(
                    {
                        "internal_name": attachment.name,
                        "path": str(target),
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "subtype": str(attachment.subtype or ""),
                    }
                )
        finally:
            reader.close()
        return extracted


def _safe_name(value: str) -> str:
    name = Path(value.replace("\\", "/")).name
    name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", name).strip(" .")
    return name[:180] or "attachment.bin"


def _unique_target(root: Path, name: str) -> Path:
    candidate = (root / name).resolve()
    counter = 1
    while candidate.exists():
        candidate = (root / f"{Path(name).stem}-{counter}{Path(name).suffix}").resolve()
        counter += 1
    return candidate
