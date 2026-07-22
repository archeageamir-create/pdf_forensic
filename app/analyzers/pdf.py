from __future__ import annotations

import re
from pathlib import Path
from typing import BinaryIO, Pattern

from app.models import Finding, FindingLevel


class PdfStructureAnalyzer:
    """Read-only streaming triage used even when external tools are unavailable."""

    SOURCE = "Built-in PDF triage"
    CHUNK_SIZE = 4 * 1024 * 1024
    OVERLAP = 512

    PATTERNS: tuple[tuple[str, Pattern[bytes]], ...] = (
        ("Encrypted", re.compile(rb"/Encrypt\b")),
        ("Digital signature markers", re.compile(rb"/(?:Type\s*/Sig|ByteRange)\b")),
        ("Objects", re.compile(rb"(?m)^\s*\d+\s+\d+\s+obj\b")),
        ("Object streams", re.compile(rb"/ObjStm\b")),
        ("Classic xref sections", re.compile(rb"(?m)^xref\s*$")),
        ("Xref streams", re.compile(rb"/Type\s*/XRef\b")),
        ("Prev references", re.compile(rb"/Prev\s+\d+")),
        ("startxref markers", re.compile(rb"startxref\b")),
        ("EOF markers", re.compile(rb"%%EOF")),
        ("JavaScript markers", re.compile(rb"/(?:JS|JavaScript)\b")),
        ("Additional actions", re.compile(rb"/AA\b")),
        ("Open actions", re.compile(rb"/OpenAction\b")),
        ("Embedded files", re.compile(rb"/EmbeddedFile\b")),
        ("AcroForm references", re.compile(rb"/AcroForm\b")),
        ("XFA references", re.compile(rb"/XFA\b")),
    )

    def analyze(self, path: Path) -> list[Finding]:
        with path.open("rb") as stream:
            header_bytes = stream.read(1024)
            stream.seek(0)
            counts = self._count_patterns(stream)

        header = re.search(rb"%PDF-(\d\.\d)", header_bytes)
        findings: list[Finding] = [
            Finding(
                "PDF structure",
                "PDF version",
                header.group(1).decode("ascii") if header else "not detected",
                self.SOURCE,
                FindingLevel.INFO if header else FindingLevel.MEDIUM,
                location="file header",
            )
        ]
        for name, count in counts.items():
            value: int | bool = bool(count) if name == "Encrypted" else count
            findings.append(Finding("PDF structure", name, value, self.SOURCE))

        findings.append(
            Finding("PDF structure", "xref type", _xref_type(counts), self.SOURCE)
        )
        findings.append(
            Finding(
                "PDF structure",
                "Forms present",
                bool(counts["AcroForm references"] or counts["XFA references"]),
                self.SOURCE,
            )
        )
        revision_count = max(counts["startxref markers"], counts["EOF markers"])
        findings.append(
            Finding(
                "PDF revisions",
                "Potential revision sections",
                revision_count,
                self.SOURCE,
                FindingLevel.LOW if revision_count > 1 else FindingLevel.INFO,
                description="Count inferred from startxref and EOF markers.",
                details=(
                    "Multiple revision markers require expert evaluation and do not alone prove "
                    "unauthorized modification."
                    if revision_count > 1
                    else ""
                ),
            )
        )
        return findings

    def _count_patterns(self, stream: BinaryIO) -> dict[str, int]:
        counts = {name: 0 for name, _ in self.PATTERNS}
        tail = b""
        while chunk := stream.read(self.CHUNK_SIZE):
            combined = tail + chunk
            tail_length = len(tail)
            for name, pattern in self.PATTERNS:
                counts[name] += sum(
                    1 for match in pattern.finditer(combined) if match.end() > tail_length
                )
            tail = combined[-self.OVERLAP :]
        return counts


def _xref_type(counts: dict[str, int]) -> str:
    classic = bool(counts["Classic xref sections"])
    streams = bool(counts["Xref streams"])
    if classic and streams:
        return "hybrid/classic and stream markers"
    if streams:
        return "xref stream"
    if classic:
        return "classic table"
    return "not detected"
