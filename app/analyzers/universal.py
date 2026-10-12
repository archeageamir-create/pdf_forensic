from __future__ import annotations

import warnings
import zipfile
from pathlib import Path

from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError
from PIL.TiffImagePlugin import IFDRational

from app.adapters.base import AdapterResult
from app.analyzers.pptx import (
    OoxmlLimits,
    PptxAnalyzer,
    _local_name,
    _validate_member_name,
)
from app.core.errors import AnalysisError
from app.core.formats import PROFILES
from app.models import FileKind, Finding, FindingLevel


def json_value(value):
    """Keep EXIF rational/binary values serializable without discarding their type."""
    if isinstance(value, bytes):
        return {
            "encoding": "hex",
            "bytes": len(value),
            "value": value[:4096].hex(),
            "truncated": len(value) > 4096,
        }
    if isinstance(value, IFDRational):
        return {
            "type": "rational",
            "numerator": value.numerator,
            "denominator": value.denominator,
            "display": str(value),
        }
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class ImageMetadataAnalyzer:
    def analyze(self, path: Path) -> AdapterResult:
        findings = []
        artifacts = {}
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    for name, value in (
                        ("Image format", image.format),
                        ("Image width", image.width),
                        ("Image height", image.height),
                        ("Color mode", image.mode),
                    ):
                        findings.append(
                            Finding("Image properties", name, value, "Pillow")
                        )
                    exif = image.getexif()
                    for key, value in exif.items():
                        if key not in (34665, 34853):
                            findings.append(
                                Finding(
                                    "EXIF",
                                    ExifTags.TAGS.get(key, str(key)),
                                    json_value(value),
                                    "Pillow/IFD0",
                                    location=f"EXIF tag {key}",
                                )
                            )
                    for ifd, group, labels in (
                        (34665, "EXIF", ExifTags.TAGS),
                        (34853, "GPS", ExifTags.GPSTAGS),
                    ):
                        if ifd in exif:
                            for key, value in exif.get_ifd(ifd).items():
                                findings.append(
                                    Finding(
                                        group,
                                        labels.get(key, str(key)),
                                        json_value(value),
                                        f"Pillow/{group}",
                                        location=f"IFD {ifd}, tag {key}",
                                    )
                                )
                    for key, value in image.info.items():
                        if key != "exif":
                            findings.append(
                                Finding(
                                    "Image properties", key, json_value(value), "Pillow"
                                )
                            )
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            SyntaxError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise AnalysisError(
                f"Не удалось прочитать метаданные изображения: {exc}"
            ) from exc
        try:
            with Image.open(path) as image:
                if image.width * image.height <= 24_000_000:
                    image.thumbnail((1200, 900))
                    preview = ImageOps.exif_transpose(image).convert("RGB")
                    target = path.parent / "image-preview.png"
                    preview.save(target)
                    artifacts["image_preview_path"] = str(target)
                    artifacts["image_preview_note"] = (
                        "Уменьшенная копия первого кадра с учётом ориентации EXIF. Оригинальные байты не изменены."
                    )
                else:
                    artifacts["image_preview_note"] = (
                        "Предпросмотр пропущен: изображение больше 24 мегапикселей. Метаданные доступны."
                    )
        except (OSError, ValueError, SyntaxError) as exc:
            artifacts["image_preview_note"] = (
                f"Предпросмотр недоступен: {exc}. Метаданные сохранены."
            )
        return AdapterResult(findings=findings, artifacts=artifacts)


class ArchiveAnalyzer:
    def __init__(self, limits: OoxmlLimits):
        self.limits = limits

    def analyze(self, path: Path) -> AdapterResult:
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                if len(infos) > self.limits.max_entries:
                    raise AnalysisError("Превышен лимит количества записей ZIP")
                entries = []
                unsafe = []
                for info in infos:
                    try:
                        _validate_member_name(info.filename)
                    except AnalysisError:
                        unsafe.append(info.filename)
                    entries.append(
                        {
                            "name": info.filename,
                            "size": info.file_size,
                            "compressed_size": info.compress_size,
                            "modified_local": "%04d-%02d-%02dT%02d:%02d:%02d"
                            % info.date_time,
                            "encrypted": bool(info.flag_bits & 1),
                            "crc32_declared": f"{info.CRC:08x}",
                        }
                    )
                encrypted = sum(item["encrypted"] for item in entries)
                findings = [
                    Finding("Archive", "ZIP entries", len(entries), "Python zipfile"),
                    Finding(
                        "Archive",
                        "Encrypted entries",
                        encrypted,
                        "Python zipfile",
                        FindingLevel.MANUAL_REVIEW if encrypted else FindingLevel.INFO,
                        details="Шифрование определено по флагам ZIP. Пароль не подбирался.",
                    ),
                    Finding(
                        "Archive",
                        "Archive inventory",
                        entries,
                        "Python zipfile",
                        details="Даты ZIP обычно не содержат часового пояса. CRC взят из каталога, содержимое не проверялось.",
                    ),
                    Finding(
                        "Archive",
                        "Unsafe archive paths",
                        unsafe,
                        "Python zipfile",
                        FindingLevel.MEDIUM if unsafe else FindingLevel.INFO,
                        details="Записи только перечислены; файлы из архива не извлекались.",
                    ),
                ]
                return AdapterResult(
                    findings=findings, artifacts={"archive_entries": entries}
                )
        except (zipfile.BadZipFile, OSError) as exc:
            raise AnalysisError(f"Не удалось прочитать ZIP: {exc}") from exc


class OfficeAnalyzer(PptxAnalyzer):
    """Shared bounded OOXML reader plus Word/Excel observations; no Office automation."""

    def analyze(self, path: Path, kind: FileKind) -> AdapterResult:
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                self._validate_archive(infos)
                names = {item.filename for item in infos}
                findings = self._properties(archive, names)
                relationships = self._relationships(archive, names)
                for finding in relationships:
                    finding.category = "OOXML relationships"
                findings.extend(relationships)
                macros = sorted(
                    n for n in names if n.casefold().endswith("vbaproject.bin")
                )
                embeddings = sorted(
                    n for n in names if "/embeddings/" in n and not n.endswith("/")
                )
                findings.extend(
                    [
                        Finding(
                            "OOXML structure", "ZIP entries", len(infos), self.SOURCE
                        ),
                        Finding(
                            "OOXML structure",
                            "Macro parts",
                            macros,
                            self.SOURCE,
                            FindingLevel.MANUAL_REVIEW if macros else FindingLevel.INFO,
                            details="Обнаруженные части VBA только перечислены. Код макросов не запускался и не исследовался.",
                        ),
                        Finding(
                            "OOXML structure",
                            "OOXML embedded files",
                            embeddings,
                            self.SOURCE,
                            FindingLevel.LOW if embeddings else FindingLevel.INFO,
                        ),
                    ]
                )
                if kind == FileKind.DOCX:
                    findings.extend(self._word(archive, names))
                elif kind == FileKind.XLSX:
                    findings.extend(self._excel(archive))
                return AdapterResult(findings=findings)
        except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError) as exc:
            raise AnalysisError(f"Не удалось прочитать OOXML: {exc}") from exc

    def _word(self, archive, names):
        comments = []
        if "word/comments.xml" in names:
            for element in self._read_xml(archive, "word/comments.xml"):
                if _local_name(element.tag) == "comment":
                    attributes = {_local_name(k): v for k, v in element.attrib.items()}
                    comments.append(
                        {
                            **attributes,
                            "part": "word/comments.xml",
                            "text": "".join(
                                node.text or ""
                                for node in element.iter()
                                if _local_name(node.tag) == "t"
                            ),
                        }
                    )
        changes = []
        count = 0
        for part in sorted(
            n for n in names if n.startswith("word/") and n.endswith(".xml")
        ):
            if not (
                part == "word/document.xml"
                or part.startswith(("word/header", "word/footer"))
                or part in {"word/footnotes.xml", "word/endnotes.xml"}
            ):
                continue
            for element in self._read_xml(archive, part).iter():
                tag = _local_name(element.tag)
                if tag in {"ins", "del", "moveFrom", "moveTo"} or tag.endswith(
                    "PrChange"
                ):
                    count += 1
                    if len(changes) < 5000:
                        changes.append(
                            {
                                "type": tag,
                                "part": part,
                                **{
                                    _local_name(k): v for k, v in element.attrib.items()
                                },
                            }
                        )
        return [
            Finding(
                "Word review",
                "Word comments",
                comments,
                self.SOURCE,
                location="word/comments.xml",
            ),
            Finding(
                "Word review",
                "Tracked changes count",
                count,
                self.SOURCE,
                FindingLevel.MANUAL_REVIEW if count else FindingLevel.INFO,
                details="Сохранённые исправления Word. Они показывают заявленные правки, но не доказывают автора или подделку.",
            ),
            Finding(
                "Word review",
                "Tracked changes",
                changes,
                self.SOURCE,
                details="Показано не более 5000 записей; полное число указано отдельно. Принятые или удалённые исправления восстановить по этому списку нельзя.",
            ),
        ]

    def _excel(self, archive):
        sheets = []
        for element in self._read_xml(archive, "xl/workbook.xml").iter():
            if _local_name(element.tag) == "sheet":
                sheets.append(
                    {
                        "name": element.get("name", ""),
                        "sheet_id": element.get("sheetId", ""),
                        "state": element.get("state", "visible"),
                    }
                )
        hidden = [s for s in sheets if s["state"] in {"hidden", "veryHidden"}]
        return [
            Finding(
                "Excel workbook",
                "Worksheets",
                sheets,
                self.SOURCE,
                location="xl/workbook.xml",
            ),
            Finding(
                "Excel workbook",
                "Hidden worksheets",
                hidden,
                self.SOURCE,
                FindingLevel.MANUAL_REVIEW if hidden else FindingLevel.INFO,
                details="Листы сохранены в книге, но скрыты в обычном интерфейсе Excel. Это может быть штатной частью шаблона.",
            ),
        ]


def analyze_universal(path: Path, kind: FileKind, limits: OoxmlLimits) -> AdapterResult:
    analyzer = PROFILES[kind].analyzer
    if analyzer == "image":
        return ImageMetadataAnalyzer().analyze(path)
    if analyzer == "archive":
        return ArchiveAnalyzer(limits).analyze(path)
    if analyzer == "ooxml":
        return OfficeAnalyzer(limits).analyze(path, kind)
    with path.open("rb") as stream:
        header = stream.read(64)
    return AdapterResult(
        findings=[
            Finding(
                "File properties",
                "Header bytes",
                header.hex(" "),
                "Built-in file reader",
                location="offset 0, up to 64 bytes",
            )
        ]
    )
