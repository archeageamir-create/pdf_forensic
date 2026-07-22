from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class FileKind(StrEnum):
    PDF = "pdf"
    PPTX = "pptx"

    @classmethod
    def from_path(cls, path: Path) -> "FileKind":
        suffix = path.suffix.lower().lstrip(".")
        try:
            return cls(suffix)
        except ValueError as exc:
            raise ValueError(f"Unsupported file type: {path.suffix or '(none)'}") from exc


class ToolRunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class AnalysisMode(StrEnum):
    QUICK = "quick"
    FULL = "full"
    CUSTOM = "custom"


class UserMark(StrEnum):
    NONE = ""
    SIGNIFICANT = "significant"
    INSIGNIFICANT = "insignificant"
    EXPLAINED = "explained"
    FURTHER_REVIEW = "further_review"


class FindingLevel(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MANUAL_REVIEW = "manual_review"


class IntegrityStatus(StrEnum):
    VERIFIED = "verified"
    CHANGED = "changed"


@dataclass(slots=True)
class ResearchProject:
    title: str
    case_number: str
    object_description: str
    initiator: str = ""
    legal_basis: str = ""
    source_description: str = ""
    examiner_name: str = ""
    notes: str = ""
    user_conclusions: str = ""
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class EvidenceFile:
    original_path: str
    working_copy_path: str
    sha256: str
    size_bytes: int
    kind: FileKind
    original_name: str = ""
    extension: str = ""
    detected_format: str = ""
    mime_type: str = "application/octet-stream"
    sha1: str = ""
    md5: str = ""
    working_copy_sha256: str = ""
    integrity_status: IntegrityStatus = IntegrityStatus.VERIFIED
    file_created_at: str = ""
    file_modified_at: str = ""
    project_id: str | None = None
    analysis_mode: AnalysisMode = AnalysisMode.FULL
    user_notes: str = ""
    user_conclusions: str = ""
    id: str = field(default_factory=lambda: str(uuid4()))
    added_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ToolRun:
    tool_name: str
    command: list[str]
    version: str
    stdout: str
    stderr: str
    exit_code: int | None
    status: ToolRunStatus
    started_at: str
    finished_at: str
    duration_ms: int = 0
    parsed_result: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(slots=True)
class Finding:
    category: str
    name: str
    value: Any
    source: str
    level: FindingLevel = FindingLevel.INFO
    conflict: bool = False
    description: str = ""
    details: str = ""
    location: str = ""
    user_mark: str = ""
    include_in_report: bool = True
    id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(slots=True)
class AnalysisResult:
    evidence: EvidenceFile
    findings: list[Finding] = field(default_factory=list)
    tool_runs: list[ToolRun] = field(default_factory=list)
    analyzed_at: str = field(default_factory=utc_now_iso)
    errors: list[str] = field(default_factory=list)
    incomplete: bool = False
    artifacts: dict[str, Any] = field(default_factory=dict)
    summary: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"]["kind"] = self.evidence.kind.value
        data["evidence"]["integrity_status"] = self.evidence.integrity_status.value
        data["evidence"]["analysis_mode"] = self.evidence.analysis_mode.value
        for finding in data["findings"]:
            finding["level"] = str(finding["level"])
        for tool_run in data["tool_runs"]:
            tool_run["status"] = str(tool_run["status"])
        return data


@dataclass(slots=True)
class ComparisonResult:
    left_evidence_id: str
    right_evidence_id: str
    items: list[dict[str, Any]] = field(default_factory=list)
    compared_at: str = field(default_factory=utc_now_iso)
