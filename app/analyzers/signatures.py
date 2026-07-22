from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models import Finding, FindingLevel


@dataclass(slots=True)
class SignatureAnalysisResult:
    findings: list[Finding] = field(default_factory=list)
    signatures: list[dict[str, Any]] = field(default_factory=list)


class PdfSignatureAnalyzer:
    SOURCE = "Built-in ByteRange and pyHanko"

    def __init__(self, cryptographic_validation: bool = True) -> None:
        self.cryptographic_validation = cryptographic_validation

    def analyze(self, path: Path) -> SignatureAnalysisResult:
        byte_ranges = self._byte_ranges(path)
        crypto = self._validate_crypto(path) if self.cryptographic_validation else []
        for index, item in enumerate(byte_ranges):
            if index < len(crypto):
                item["cryptographic_validation"] = crypto[index]
        signatures = byte_ranges
        if len(crypto) > len(signatures):
            signatures.extend({"cryptographic_validation": item} for item in crypto[len(signatures) :])
        findings = [
            Finding("PDF signatures", "Signatures", signatures, self.SOURCE),
            Finding("PDF signatures", "Signature count", len(signatures), self.SOURCE),
        ]
        for index, signature in enumerate(signatures, start=1):
            crypto_result = signature.get("cryptographic_validation", {})
            if not signature.get("valid_layout", True):
                findings.append(
                    Finding(
                        "PDF signatures",
                        f"Signature {index} ByteRange layout",
                        False,
                        "Built-in ByteRange",
                        FindingLevel.HIGH,
                        details="The declared byte ranges are overlapping, unordered or outside the file.",
                    )
                )
            if "intact" in crypto_result and not crypto_result["intact"]:
                findings.append(
                    Finding(
                        "PDF signatures",
                        f"Signature {index} cryptographic integrity",
                        False,
                        "pyHanko",
                        FindingLevel.HIGH,
                        details="Cryptographic integrity validation did not succeed.",
                    )
                )
        return SignatureAnalysisResult(findings=findings, signatures=signatures)

    def _byte_ranges(self, path: Path) -> list[dict[str, Any]]:
        data = path.read_bytes() if path.stat().st_size <= 128 * 1024 * 1024 else _read_signature_windows(path)
        file_size = path.stat().st_size
        results: list[dict[str, Any]] = []
        for match in re.finditer(rb"/ByteRange\s*\[([^\]]+)\]", data, re.DOTALL):
            numbers = [int(item) for item in re.findall(rb"\d+", match.group(1))]
            pairs = list(zip(numbers[0::2], numbers[1::2], strict=False))
            valid = len(numbers) >= 4 and len(numbers) % 2 == 0
            previous_end = 0
            gaps: list[dict[str, int]] = []
            for offset, length in pairs:
                valid = valid and offset >= previous_end and length >= 0 and offset + length <= file_size
                if offset > previous_end:
                    gaps.append({"offset": previous_end, "length": offset - previous_end})
                previous_end = offset + length
            if previous_end < file_size:
                gaps.append({"offset": previous_end, "length": file_size - previous_end})
            starts_at_zero = bool(pairs and pairs[0][0] == 0)
            internal_gaps = [
                item
                for item in gaps
                if item["offset"] > 0 and item["offset"] + item["length"] < file_size
            ]
            full_coverage = bool(
                valid
                and starts_at_zero
                and previous_end == file_size
                and len(internal_gaps) == 1
                and len(gaps) == 1
            )
            digest = _hash_ranges(path, pairs) if valid else ""
            surrounding = data[max(0, match.start() - 8192) : min(len(data), match.end() + 8192)]
            contents_length = _contents_hex_length(surrounding)
            signed_bytes = sum(length for _, length in pairs) if valid else 0
            results.append(
                {
                    "byte_range": numbers,
                    "range_pairs": [
                        {"offset": offset, "length": length, "end": offset + length}
                        for offset, length in pairs
                    ],
                    "valid_layout": valid,
                    "covers_file_except_signature_container": full_coverage,
                    "excluded_ranges": gaps,
                    "signature_container_bytes": (
                        internal_gaps[0]["length"] if len(internal_gaps) == 1 else None
                    ),
                    "contents_hex_bytes": contents_length,
                    "signed_bytes": signed_bytes,
                    "file_size": file_size,
                    "last_covered_byte": previous_end,
                    "bytes_after_signed_range": max(0, file_size - previous_end),
                    "has_later_incremental_update": bool(valid and previous_end < file_size),
                    "signed_ranges_sha256": digest,
                    "declared_name": _pdf_string(surrounding, b"Name"),
                    "reason": _pdf_string(surrounding, b"Reason"),
                    "location": _pdf_string(surrounding, b"Location"),
                    "signing_time": _pdf_string(surrounding, b"M"),
                }
            )
        return results

    @staticmethod
    def _validate_crypto(path: Path) -> list[dict[str, Any]]:
        try:
            from pyhanko.pdf_utils.reader import PdfFileReader
            from pyhanko.sign.validation import validate_pdf_signature
            from pyhanko_certvalidator import ValidationContext
        except ImportError as exc:
            return [{"available": False, "error": str(exc)}]

        results: list[dict[str, Any]] = []
        try:
            with path.open("rb") as stream:
                reader = PdfFileReader(stream)
                signatures = list(reader.embedded_signatures)
                for embedded in signatures:
                    cert = embedded.signer_cert
                    item: dict[str, Any] = {
                        "available": True,
                        "field_name": embedded.field_name,
                        "subject": cert.subject.human_friendly,
                        "issuer": cert.issuer.human_friendly,
                        "serial_number": str(cert.serial_number),
                        "valid_from": str(cert["tbs_certificate"]["validity"]["not_before"].native),
                        "valid_to": str(cert["tbs_certificate"]["validity"]["not_after"].native),
                    }
                    try:
                        context = ValidationContext(allow_fetching=False, revocation_mode="soft-fail")
                        status = validate_pdf_signature(
                            embedded, signer_validation_context=context, skip_diff=False
                        )
                        item.update(
                            {
                                "intact": bool(status.intact),
                                "cryptographically_valid": bool(status.valid),
                                "trusted": bool(status.trusted),
                                "coverage": str(status.coverage),
                                "modification_level": str(status.modification_level),
                                "docmdp_ok": bool(status.docmdp_ok),
                                "summary": status.summary(),
                                "details": status.pretty_print_details(),
                            }
                        )
                    except Exception as exc:
                        item.update({"intact": False, "trusted": False, "error": str(exc)})
                    results.append(item)
        except Exception as exc:
            return [{"available": True, "error": str(exc)}]
        return results


def _hash_ranges(path: Path, pairs: list[tuple[int, int]]) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for offset, length in pairs:
            stream.seek(offset)
            remaining = length
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                digest.update(chunk)
                remaining -= len(chunk)
    return digest.hexdigest()


def _pdf_string(data: bytes, key: bytes) -> str:
    matches = list(re.finditer(rb"/" + key + rb"\s*\(([^)]{0,4096})\)", data))
    return matches[-1].group(1).decode("latin-1", errors="replace") if matches else ""


def _contents_hex_length(data: bytes) -> int | None:
    matches = list(re.finditer(rb"/Contents\s*<([0-9A-Fa-f\s]+)>", data, re.DOTALL))
    if not matches:
        return None
    clean = re.sub(rb"\s+", b"", matches[-1].group(1))
    return (len(clean) + 1) // 2


def _read_signature_windows(path: Path) -> bytes:
    # ByteRange dictionaries reside in PDF objects; bounded windows keep large files safe.
    chunks: list[bytes] = []
    overlap = b""
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            combined = overlap + chunk
            if b"/ByteRange" in combined:
                chunks.append(combined)
            overlap = combined[-16_384:]
    return b"\n".join(chunks)
