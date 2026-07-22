from __future__ import annotations

import base64
import binascii
import bisect
import itertools
import mmap
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models import Finding, FindingLevel


OBJECT_HEADER = re.compile(rb"(?m)^\s*(\d+)\s+(\d+)\s+obj\b")
REFERENCE = re.compile(rb"\b(\d+)\s+(\d+)\s+R\b")
FILTER_NAME = re.compile(rb"/([A-Za-z0-9]+Decode)\b")


@dataclass(slots=True)
class PdfDeepResult:
    findings: list[Finding] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)


class PdfDeepAnalyzer:
    SOURCE = "Built-in deep PDF analyzer"

    def __init__(self, max_objects: int = 250_000, max_stream_bytes: int = 64 * 1024 * 1024):
        self.max_objects = max_objects
        self.max_stream_bytes = max_stream_bytes

    def analyze(self, path: Path) -> PdfDeepResult:
        with path.open("rb") as stream:
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                revisions = self._revisions(data)
                objects = self._objects(data, revisions)
                comparison = self._compare_revisions(revisions)
        findings = [
            Finding("PDF revisions", "Revision details", revisions, self.SOURCE),
            Finding("PDF revisions", "Revision comparison", comparison, self.SOURCE),
            Finding("PDF objects", "Indexed objects", len(objects), self.SOURCE),
            Finding(
                "PDF objects",
                "Objects with streams",
                sum(1 for item in objects if item["has_stream"]),
                self.SOURCE,
            ),
            Finding(
                "PDF revisions",
                "Incremental updates",
                max(0, len(revisions) - 1),
                self.SOURCE,
                FindingLevel.LOW if len(revisions) > 1 else FindingLevel.INFO,
                details=(
                    "Multiple revisions are a structural fact and require expert interpretation."
                    if len(revisions) > 1
                    else ""
                ),
            ),
        ]
        return PdfDeepResult(
            findings=findings,
            artifacts={
                "pdf_revisions": revisions,
                "pdf_revision_comparison": comparison,
                "pdf_objects": objects,
            },
        )

    def _revisions(self, data: mmap.mmap) -> list[dict[str, Any]]:
        size = len(data)
        eof_ends = [match.end() for match in re.finditer(rb"%%EOF", data)]
        boundaries = eof_ends or [size]
        trailing_bytes = max(0, size - boundaries[-1])
        trailing_non_whitespace = bool(
            trailing_bytes and bytes(data[boundaries[-1] :]).strip()
        )

        revisions: list[dict[str, Any]] = []
        start = 0
        for index, end in enumerate(boundaries, start=1):
            segment = data[start:end]
            startxref_values = [
                int(match.group(1))
                for match in re.finditer(rb"startxref\s+(\d+)", segment)
            ]
            prev_values = [int(match.group(1)) for match in re.finditer(rb"/Prev\s+(\d+)", segment)]
            object_numbers = list(dict.fromkeys(
                int(match.group(1)) for match in OBJECT_HEADER.finditer(segment)
            ))[: self.max_objects]
            revisions.append(
                {
                    "number": index,
                    "byte_start": start,
                    "byte_end": end,
                    "length": end - start,
                    "startxref": startxref_values[-1] if startxref_values else None,
                    "prev": prev_values[-1] if prev_values else None,
                    "changed_objects": object_numbers,
                    "metadata": _metadata_snapshot(bytes(data[:end])),
                    "metadata_delta": _metadata_snapshot(segment),
                    "notes": (
                        ["Trailing data exists after the last complete %%EOF marker"]
                        if index == len(boundaries) and trailing_non_whitespace
                        else []
                    ),
                    "trailing_bytes_after_revision": (
                        trailing_bytes if index == len(boundaries) else 0
                    ),
                }
            )
            start = end
        return revisions

    @staticmethod
    def _compare_revisions(revisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        comparison: list[dict[str, Any]] = []
        seen_objects: set[int] = set()
        previous_metadata: dict[str, str] = {}
        for revision in revisions:
            changed = [int(item) for item in revision.get("changed_objects", [])]
            current_metadata = dict(revision.get("metadata", {}))
            comparison.append(
                {
                    "revision": revision.get("number"),
                    "introduced_objects": [item for item in changed if item not in seen_objects],
                    "redefined_objects": [item for item in changed if item in seen_objects],
                    "metadata_changes": {
                        key: {"before": previous_metadata.get(key), "after": value}
                        for key, value in current_metadata.items()
                        if previous_metadata.get(key) != value
                    },
                }
            )
            seen_objects.update(changed)
            previous_metadata = current_metadata
        return comparison

    def _objects(
        self, data: mmap.mmap, revisions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        matches = list(itertools.islice(OBJECT_HEADER.finditer(data), self.max_objects + 1))
        truncated = len(matches) > self.max_objects
        matches = matches[: self.max_objects]
        revision_ends = [int(item["byte_end"]) for item in revisions]
        objects: list[dict[str, Any]] = []
        for position, match in enumerate(matches):
            start = match.start()
            next_start = matches[position + 1].start() if position + 1 < len(matches) else len(data)
            end_marker = data.find(b"endobj", match.end(), next_start)
            end = end_marker + len(b"endobj") if end_marker >= 0 else next_start
            raw = bytes(data[start:end])
            stream_info = self._stream_info(raw, start)
            dictionary = _first_dictionary(raw)
            filters = _filters(dictionary)
            decoded_preview = ""
            decode_error = ""
            if stream_info and stream_info["length"] <= self.max_stream_bytes:
                stream_bytes = bytes(
                    data[
                        int(stream_info["offset"]) : int(stream_info["offset"])
                        + int(stream_info["length"])
                    ]
                )
                try:
                    decoded = decode_pdf_stream(stream_bytes, filters)
                    decoded_preview = _preview(decoded, 16_384)
                except (ValueError, zlib.error, binascii.Error) as exc:
                    decode_error = str(exc)
            refs = [
                {"object": int(item.group(1)), "generation": int(item.group(2))}
                for item in REFERENCE.finditer(dictionary)
            ][:500]
            revision = bisect.bisect_left(revision_ends, start) + 1
            objects.append(
                {
                    "object": int(match.group(1)),
                    "generation": int(match.group(2)),
                    "offset": start,
                    "length": end - start,
                    "revision": revision,
                    "category": _object_category(dictionary),
                    "has_stream": stream_info is not None,
                    "stream_offset": stream_info["offset"] if stream_info else None,
                    "stream_length": stream_info["length"] if stream_info else 0,
                    "filters": filters,
                    "references": refs,
                    "dictionary": _preview(dictionary, 16_384),
                    "raw_preview": _preview(raw, 16_384),
                    "decoded_preview": decoded_preview,
                    "decode_error": decode_error,
                }
            )
        if truncated:
            objects.append(
                {
                    "object": -1,
                    "generation": 0,
                    "offset": 0,
                    "length": 0,
                    "revision": 0,
                    "category": "Limit",
                    "has_stream": False,
                    "references": [],
                    "raw_preview": f"Object index truncated at configured limit {self.max_objects}",
                }
            )
        return objects

    @staticmethod
    def _stream_info(raw: bytes, absolute_start: int) -> dict[str, int] | None:
        marker = re.search(rb"stream(?:\r\n|\n|\r)", raw)
        if not marker:
            return None
        end = raw.find(b"endstream", marker.end())
        if end < 0:
            return None
        stream_end = end
        if stream_end >= 2 and raw[stream_end - 2 : stream_end] == b"\r\n":
            stream_end -= 2
        elif stream_end >= 1 and raw[stream_end - 1 : stream_end] in {b"\r", b"\n"}:
            stream_end -= 1
        return {
            "offset": absolute_start + marker.end(),
            "length": max(0, stream_end - marker.end()),
        }


def decode_pdf_stream(data: bytes, filters: list[str]) -> bytes:
    decoded = data
    for filter_name in filters:
        if filter_name == "FlateDecode":
            decoded = zlib.decompress(decoded)
        elif filter_name == "ASCIIHexDecode":
            clean = re.sub(rb"\s+", b"", decoded).rstrip(b">")
            if len(clean) % 2:
                clean += b"0"
            decoded = binascii.unhexlify(clean)
        elif filter_name == "ASCII85Decode":
            decoded = base64.a85decode(decoded, adobe=b"<~" in decoded)
        elif filter_name == "RunLengthDecode":
            decoded = _run_length_decode(decoded)
        elif filter_name in {"DCTDecode", "JPXDecode", "CCITTFaxDecode", "JBIG2Decode"}:
            raise ValueError(f"Binary image filter is not decoded in the text viewer: {filter_name}")
        else:
            raise ValueError(f"Unsupported stream filter: {filter_name}")
    return decoded


def _run_length_decode(data: bytes) -> bytes:
    output = bytearray()
    index = 0
    while index < len(data):
        length = data[index]
        index += 1
        if length == 128:
            break
        if length <= 127:
            count = length + 1
            output.extend(data[index : index + count])
            index += count
        else:
            if index >= len(data):
                raise ValueError("Truncated RunLengthDecode stream")
            output.extend(data[index : index + 1] * (257 - length))
            index += 1
    return bytes(output)


def _first_dictionary(raw: bytes) -> bytes:
    start = raw.find(b"<<")
    if start < 0:
        return b""
    end = raw.find(b">>", start + 2)
    return raw[start : end + 2] if end >= 0 else raw[start : min(len(raw), start + 16_384)]


def _filters(dictionary: bytes) -> list[str]:
    match = re.search(rb"/Filter\s*(\[[^\]]*\]|/[A-Za-z0-9]+)", dictionary, re.DOTALL)
    return [item.decode("ascii", errors="replace") for item in FILTER_NAME.findall(match.group(1))] if match else []


def _object_category(dictionary: bytes) -> str:
    for token, category in (
        (b"/Type /Page", "Pages"),
        (b"/Type /Metadata", "Metadata"),
        (b"/Type /Sig", "Signatures"),
        (b"/EmbeddedFile", "Attachments"),
        (b"/ObjStm", "Object streams"),
        (b"/XRef", "XRef"),
        (b"/AcroForm", "Forms"),
    ):
        if token in dictionary:
            return category
    return "Objects"


def _metadata_snapshot(segment: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for key in (b"Author", b"Creator", b"Producer", b"CreationDate", b"ModDate"):
        matches = list(re.finditer(rb"/" + key + rb"\s*\(([^)]{0,2048})\)", segment))
        if matches:
            values[key.decode("ascii")] = matches[-1].group(1).decode("latin-1", errors="replace")
    return values


def _preview(data: bytes, limit: int) -> str:
    clipped = data[:limit]
    try:
        text = clipped.decode("utf-8")
    except UnicodeDecodeError:
        text = clipped.decode("latin-1", errors="replace")
    return text + ("\n… [preview truncated]" if len(data) > limit else "")
