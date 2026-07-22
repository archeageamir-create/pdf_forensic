from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app.core.errors import EvidencePreparationError, UnsupportedFileError
from datetime import UTC, datetime

from app.core.formats import detect_file_kind, mime_for_kind
from app.core.hashing import calculate_hashes, sha256_file
from app.models import AnalysisMode, EvidenceFile, IntegrityStatus

LOGGER = logging.getLogger(__name__)


class EvidenceWorkspace:
    """Creates a private byte-for-byte copy and never writes to the original."""

    def __init__(self, cases_dir: Path) -> None:
        self.cases_dir = cases_dir

    def prepare(
        self,
        original_path: Path,
        project_id: str | None = None,
        analysis_mode: AnalysisMode = AnalysisMode.FULL,
    ) -> EvidenceFile:
        source = original_path.expanduser().resolve(strict=True)
        if not source.is_file():
            raise EvidencePreparationError(f"Not a regular file: {source}")
        if source.stat().st_size == 0:
            raise EvidencePreparationError("The selected file is empty")
        kind = detect_file_kind(source)
        if kind is None:
            raise UnsupportedFileError("File signature is not a supported PDF or PPTX format")

        source_hashes = calculate_hashes(source)
        source_hash = source_hashes["sha256"]
        project_part = project_id or "quick-analysis"
        case_dir = self.cases_dir / project_part / source_hash
        case_dir.mkdir(parents=True, exist_ok=True)
        copy_path = case_dir / f"working-copy{source.suffix.lower()}"

        if not copy_path.exists() or sha256_file(copy_path) != source_hash:
            temporary = case_dir / f".{copy_path.name}.tmp"
            try:
                shutil.copyfile(source, temporary)
                if sha256_file(temporary) != source_hash:
                    raise EvidencePreparationError("Working copy hash mismatch")
                if copy_path.exists():
                    copy_path.chmod(0o666)
                temporary.replace(copy_path)
            except Exception as exc:
                temporary.unlink(missing_ok=True)
                if isinstance(exc, EvidencePreparationError):
                    raise
                raise EvidencePreparationError(f"Cannot create working copy: {exc}") from exc

        # A read-only flag is defense in depth. Analyzers also open files read-only.
        try:
            copy_path.chmod(0o444)
        except OSError:
            LOGGER.warning("Could not mark working copy read-only: %s", copy_path)

        if sha256_file(source) != source_hash:
            raise EvidencePreparationError("Original file changed while it was being copied")

        stat = source.stat()

        return EvidenceFile(
            original_path=str(source),
            working_copy_path=str(copy_path),
            sha256=source_hash,
            size_bytes=source.stat().st_size,
            kind=kind,
            original_name=source.name,
            extension=source.suffix.lower(),
            detected_format=kind.value.upper(),
            mime_type=mime_for_kind(kind),
            sha1=source_hashes["sha1"],
            md5=source_hashes["md5"],
            working_copy_sha256=source_hash,
            integrity_status=IntegrityStatus.VERIFIED,
            file_created_at=datetime.fromtimestamp(stat.st_ctime, UTC).isoformat(),
            file_modified_at=datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
            project_id=project_id,
            analysis_mode=analysis_mode,
        )

    @staticmethod
    def verify(evidence: EvidenceFile) -> bool:
        copy_path = Path(evidence.working_copy_path)
        if not copy_path.is_file():
            return False
        return sha256_file(copy_path) == evidence.sha256
