from __future__ import annotations

import mmap
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models import Finding, FindingLevel


ID_ARRAY = re.compile(
    rb"/ID\s*\[\s*(<[^>]{1,1024}>|\([^)]{0,1024}\))\s*"
    rb"(<[^>]{1,1024}>|\([^)]{0,1024}\))\s*\]",
    re.DOTALL,
)
INFO_VALUE = re.compile(
    rb"/(Author|Creator|Producer|CreationDate|ModDate)\s*"
    rb"(\((?:\\.|[^)]){0,4096}\)|<(?!(?:<))[^>]{0,8192}>)",
    re.DOTALL,
)
LINEAGE_FIELDS = {
    "DocumentID",
    "InstanceID",
    "OriginalDocumentID",
    "VersionID",
    "RenditionClass",
    "CreatorTool",
    "CreateDate",
    "ModifyDate",
    "MetadataDate",
    "Producer",
}
HISTORY_FIELDS = {
    "action",
    "when",
    "softwareAgent",
    "changed",
    "parameters",
    "instanceID",
}


@dataclass(slots=True)
class PdfProvenanceResult:
    findings: list[Finding] = field(default_factory=list)
    artifact: dict[str, Any] = field(default_factory=dict)


class PdfProvenanceAnalyzer:
    """Extracts technical provenance claims without treating them as proof of identity."""

    SOURCE = "Built-in PDF provenance analyzer"

    def analyze(self, path: Path) -> PdfProvenanceResult:
        with path.open("rb") as stream:
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                document_ids = _document_ids(data)
                info_occurrences = _info_occurrences(data)
                packets = _xmp_packets(data)

        lineage: dict[str, list[str]] = {}
        history: list[dict[str, str]] = []
        for packet in packets:
            packet_lineage, packet_history = _parse_xmp(packet)
            for name, values in packet_lineage.items():
                target = lineage.setdefault(name, [])
                for value in values:
                    if value not in target:
                        target.append(value)
            for event in packet_history:
                if event not in history:
                    history.append(event)

        software = _software_traces(lineage, history, info_occurrences)
        findings: list[Finding] = []
        if document_ids:
            findings.append(
                Finding(
                    "PDF provenance",
                    "Trailer document IDs",
                    document_ids,
                    self.SOURCE,
                    details=(
                        "Первое значение обычно связывает документ с исходным экземпляром, "
                        "второе может меняться при сохранениях; реализация зависит от программы."
                    ),
                )
            )
            second_values = {item["current"] for item in document_ids}
            findings.append(
                Finding(
                    "PDF provenance",
                    "Document ID changed across trailers",
                    len(second_values) > 1,
                    self.SOURCE,
                    FindingLevel.LOW if len(second_values) > 1 else FindingLevel.INFO,
                    details=(
                        "Различие второго ID технически совместимо с последовательными "
                        "сохранениями, но само по себе не устанавливает автора правки."
                    ),
                )
            )
        if lineage:
            findings.append(
                Finding(
                    "PDF provenance",
                    "XMP document lineage",
                    lineage,
                    self.SOURCE,
                )
            )
        if history:
            findings.append(
                Finding(
                    "PDF provenance",
                    "XMP editing history",
                    history,
                    self.SOURCE,
                    FindingLevel.LOW,
                    details=(
                        "XMP History является заявленной историей приложения и может быть "
                        "удалена или изменена; сопоставляйте её с ревизиями и подписями."
                    ),
                )
            )
        if software:
            findings.append(
                Finding(
                    "PDF provenance",
                    "Editing software traces",
                    software,
                    self.SOURCE,
                )
            )
        if info_occurrences:
            findings.append(
                Finding(
                    "PDF provenance",
                    "Metadata occurrences with offsets",
                    info_occurrences,
                    self.SOURCE,
                )
            )

        artifact = {
            "document_ids": document_ids,
            "xmp_lineage": lineage,
            "xmp_history": history,
            "software_traces": software,
            "metadata_occurrences": info_occurrences,
            "signals": [],
            "caution": (
                "Метаданные идентифицируют заявленные имена и программы, но не доказывают "
                "фактическое владение файлом без внешнего подтверждения."
            ),
        }
        return PdfProvenanceResult(findings=findings, artifact=artifact)


def enrich_provenance(
    provenance: dict[str, Any],
    findings: list[Finding],
    artifacts: dict[str, object],
) -> dict[str, Any]:
    signals: list[dict[str, object]] = []

    identity_roles = {
        "author": "Заявленный автор",
        "creator": "Заявленный создатель",
        "lastmodifiedby": "Заявленный последний редактор",
        "lastsavedby": "Заявленный последний редактор",
        "company": "Заявленная организация",
        "manager": "Заявленный руководитель",
    }
    software_roles = {
        "creatortool": "Программа создания",
        "producer": "PDF-производитель",
        "application": "Приложение",
        "appversion": "Версия приложения",
    }
    lineage_roles = {
        "documentid": "XMP DocumentID",
        "instanceid": "XMP InstanceID",
        "originaldocumentid": "XMP OriginalDocumentID",
        "versionid": "XMP VersionID",
    }
    date_roles = {
        "createdate": "Заявленная дата создания",
        "creationdate": "Заявленная дата создания",
        "modifydate": "Заявленная дата изменения",
        "moddate": "Заявленная дата изменения",
        "metadatadate": "Заявленная дата изменения XMP",
    }
    for finding in findings:
        value = finding.value
        if value in (None, "", [], {}):
            continue
        normalized = _normalized_name(finding.name)
        if normalized in identity_roles:
            role = identity_roles[normalized]
            if normalized == "creator" and finding.category not in {
                "XMP",
                "OOXML Core Properties",
            }:
                role = "Программа или лицо-создатель"
            signals.append(
                _signal(
                    role,
                    value,
                    finding.source,
                    "заявлено в метаданных",
                    "Значение можно изменить; требуется независимое подтверждение.",
                )
            )
        elif normalized in software_roles:
            signals.append(
                _signal(
                    software_roles[normalized],
                    value,
                    finding.source,
                    "технический след программы",
                    "Указывает на программную среду, но не на конкретного пользователя.",
                )
            )
        elif normalized in lineage_roles:
            signals.append(
                _signal(
                    lineage_roles[normalized],
                    value,
                    finding.source,
                    "заявленная связь экземпляров",
                    "Сопоставьте с /ID в trailer и идентификаторами других версий файла.",
                )
            )
        elif normalized in date_roles:
            signals.append(
                _signal(
                    date_roles[normalized],
                    value,
                    finding.source,
                    "заявлено в метаданных",
                    "Проверьте часовой пояс и согласованность с ревизиями и файловой системой.",
                )
            )
        elif normalized in {"historyaction", "historywhen", "historysoftwareagent"}:
            signals.append(
                _signal(
                    "Поле XMP History",
                    {finding.name: value},
                    finding.source,
                    "заявленная история приложения",
                    "Полезно только вместе с другими полями History и структурой ревизий.",
                )
            )

    for signature in artifacts.get("pdf_signatures", []):
        if not isinstance(signature, dict):
            continue
        crypto = signature.get("cryptographic_validation", {})
        if not isinstance(crypto, dict) or not crypto.get("subject"):
            continue
        intact = bool(crypto.get("intact"))
        trusted = bool(crypto.get("trusted"))
        strength = (
            "криптографическая связь, доверенная цепочка"
            if intact and trusted
            else "криптографическая связь без подтверждённого доверия"
            if intact
            else "сертификат обнаружен, целостность не подтверждена"
        )
        signals.append(
            _signal(
                "Подписант сертификата",
                crypto.get("subject"),
                "pyHanko",
                strength,
                str(crypto.get("summary") or crypto.get("error") or ""),
            )
        )

    for item in artifacts.get("pdf_revision_comparison", []):
        if not isinstance(item, dict) or not item.get("metadata_changes"):
            continue
        signals.append(
            _signal(
                f"Изменения метаданных в ревизии {item.get('revision')}",
                item.get("metadata_changes"),
                "Байтовое сравнение ревизий",
                "структурно подтверждено",
                "Показывает изменение значений между сохранениями, но не личность редактора.",
            )
        )

    for event in provenance.get("xmp_history", []):
        if not isinstance(event, dict):
            continue
        signals.append(
            _signal(
                "Запись XMP History",
                event,
                "XMP",
                "заявленная история приложения",
                "Сопоставьте дату, действие и softwareAgent с PDF-ревизиями.",
            )
        )

    deduplicated: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for signal in signals:
        key = (str(signal["role"]), str(signal["value"]), str(signal["source"]))
        if key not in seen:
            seen.add(key)
            deduplicated.append(signal)
    provenance["signals"] = deduplicated
    return provenance


def _document_ids(data: mmap.mmap) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for match in ID_ARRAY.finditer(data):
        result.append(
            {
                "offset": match.start(),
                "original": _pdf_token_hex(match.group(1)),
                "current": _pdf_token_hex(match.group(2)),
            }
        )
    return result


def _info_occurrences(data: mmap.mmap) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for match in INFO_VALUE.finditer(data):
        result.append(
            {
                "name": match.group(1).decode("ascii"),
                "value": _decode_pdf_token(match.group(2)),
                "offset": match.start(),
            }
        )
        if len(result) >= 10_000:
            break
    return result


def _xmp_packets(data: mmap.mmap) -> list[bytes]:
    packets: list[bytes] = []
    position = 0
    while len(packets) < 32:
        start = data.find(b"<x:xmpmeta", position)
        closing = b"</x:xmpmeta>"
        if start < 0:
            start = data.find(b"<rdf:RDF", position)
            closing = b"</rdf:RDF>"
        if start < 0:
            break
        end = data.find(closing, start)
        if end < 0:
            break
        end += len(closing)
        if end - start <= 8 * 1024 * 1024:
            packets.append(bytes(data[start:end]))
        position = end
    return packets


def _parse_xmp(packet: bytes) -> tuple[dict[str, list[str]], list[dict[str, str]]]:
    try:
        root = ET.fromstring(packet.decode("utf-8", errors="replace"))
    except ET.ParseError:
        return {}, []
    lineage: dict[str, list[str]] = {}
    history: list[dict[str, str]] = []
    for element in root.iter():
        element_name = _local_name(element.tag)
        if element_name in LINEAGE_FIELDS and (element.text or "").strip():
            _append_lineage(lineage, element_name, (element.text or "").strip())
        for attribute, value in element.attrib.items():
            name = _local_name(attribute)
            if name in LINEAGE_FIELDS and value.strip():
                _append_lineage(lineage, name, value.strip())
        if element_name != "li":
            continue
        event: dict[str, str] = {}
        for attribute, value in element.attrib.items():
            name = _local_name(attribute)
            if name in HISTORY_FIELDS and value.strip():
                event[name] = value.strip()
        for child in element:
            name = _local_name(child.tag)
            value = (child.text or "").strip()
            if name in HISTORY_FIELDS and value:
                event[name] = value
        if event and any(name in event for name in {"action", "when", "softwareAgent"}):
            history.append(event)
    return lineage, history


def _software_traces(
    lineage: dict[str, list[str]],
    history: list[dict[str, str]],
    info_occurrences: list[dict[str, object]],
) -> list[str]:
    values: list[str] = []
    for name in ("CreatorTool", "Producer"):
        values.extend(lineage.get(name, []))
    values.extend(
        str(event["softwareAgent"])
        for event in history
        if event.get("softwareAgent")
    )
    values.extend(
        str(item["value"])
        for item in info_occurrences
        if item.get("name") in {"Creator", "Producer"} and item.get("value")
    )
    return list(dict.fromkeys(values))


def _pdf_token_hex(token: bytes) -> str:
    if token.startswith(b"<"):
        return re.sub(rb"\s+", b"", token[1:-1]).decode("ascii", errors="replace").lower()
    return _decode_pdf_literal(token[1:-1]).hex()


def _decode_pdf_token(token: bytes) -> str:
    if token.startswith(b"("):
        raw = _decode_pdf_literal(token[1:-1])
    else:
        clean = re.sub(rb"\s+", b"", token[1:-1])
        if len(clean) % 2:
            clean += b"0"
        try:
            raw = bytes.fromhex(clean.decode("ascii"))
        except ValueError:
            raw = clean
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="replace")
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


def _decode_pdf_literal(value: bytes) -> bytes:
    output = bytearray()
    index = 0
    escapes = {
        ord("n"): b"\n",
        ord("r"): b"\r",
        ord("t"): b"\t",
        ord("b"): b"\b",
        ord("f"): b"\f",
        ord("("): b"(",
        ord(")"): b")",
        ord("\\"): b"\\",
    }
    while index < len(value):
        byte = value[index]
        if byte != ord("\\") or index + 1 >= len(value):
            output.append(byte)
            index += 1
            continue
        index += 1
        escaped = value[index]
        if escaped in escapes:
            output.extend(escapes[escaped])
            index += 1
        elif ord("0") <= escaped <= ord("7"):
            end = index
            while end < min(len(value), index + 3) and ord("0") <= value[end] <= ord("7"):
                end += 1
            output.append(int(value[index:end], 8))
            index = end
        elif escaped in {ord("\r"), ord("\n")}:
            if escaped == ord("\r") and index + 1 < len(value) and value[index + 1] == ord("\n"):
                index += 1
            index += 1
        else:
            output.append(escaped)
            index += 1
    return bytes(output)


def _append_lineage(target: dict[str, list[str]], name: str, value: str) -> None:
    values = target.setdefault(name, [])
    if value not in values:
        values.append(value)


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _normalized_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _signal(
    role: str,
    value: object,
    source: str,
    strength: str,
    explanation: str,
) -> dict[str, object]:
    return {
        "role": role,
        "value": value,
        "source": source,
        "strength": strength,
        "explanation": explanation,
    }
