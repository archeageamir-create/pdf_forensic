from __future__ import annotations

import hashlib
import mimetypes
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from app.core.errors import AnalysisError
from app.models import Finding, FindingLevel


@dataclass(frozen=True, slots=True)
class OoxmlLimits:
    max_entries: int = 100_000
    max_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024
    max_xml_part_bytes: int = 16 * 1024 * 1024
    max_compression_ratio: int = 250


class PptxAnalyzer:
    SOURCE = "Built-in OOXML analyzer"

    CORE_PATH = "docProps/core.xml"
    APP_PATH = "docProps/app.xml"
    CUSTOM_PATH = "docProps/custom.xml"

    def __init__(self, limits: OoxmlLimits | None = None) -> None:
        self.limits = limits or OoxmlLimits()

    def analyze(self, path: Path) -> list[Finding]:
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                self._validate_archive(infos)
                names = {info.filename for info in infos}
                if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
                    raise AnalysisError("ZIP container is not a valid PPTX package")

                findings = self._package_summary(infos)
                findings.extend(self._properties(archive, names))
                findings.extend(self._comment_authors(archive, names))
                findings.extend(self._comments(archive, names))
                findings.extend(self._notes(archive, names))
                findings.extend(self._relationships(archive, names))
                findings.extend(self._embedded_objects(archive, infos))
                findings.extend(self._presentation_details(archive, names))
                return findings
        except zipfile.BadZipFile as exc:
            raise AnalysisError(f"Damaged PPTX ZIP container: {exc}") from exc

    def _validate_archive(self, infos: list[zipfile.ZipInfo]) -> None:
        if len(infos) > self.limits.max_entries:
            raise AnalysisError(f"OOXML entry limit exceeded: {len(infos)}")
        total = 0
        for info in infos:
            _validate_member_name(info.filename)
            total += info.file_size
            if total > self.limits.max_uncompressed_bytes:
                raise AnalysisError("OOXML uncompressed size limit exceeded")
            compressed = max(info.compress_size, 1)
            if info.file_size > 1024 * 1024 and info.file_size / compressed > self.limits.max_compression_ratio:
                raise AnalysisError(f"Suspicious compression ratio in {info.filename}")

    def _package_summary(self, infos: list[zipfile.ZipInfo]) -> list[Finding]:
        names = [info.filename for info in infos]
        groups = {
            "Slides": r"^ppt/slides/slide\d+\.xml$",
            "Notes": r"^ppt/notesSlides/notesSlide\d+\.xml$",
            "Comments": r"^ppt/comments/.+\.xml$",
            "Media": r"^ppt/media/",
            "Embeddings": r"^ppt/embeddings/",
            "Themes": r"^ppt/theme/",
            "Slide masters": r"^ppt/slideMasters/",
            "Relationships": r"_rels/.+\.rels$",
        }
        findings = [
            Finding("PPTX structure", "ZIP entries", len(infos), self.SOURCE),
            Finding(
                "PPTX structure",
                "Uncompressed package size",
                sum(item.file_size for item in infos),
                self.SOURCE,
            ),
        ]
        for name, pattern in groups.items():
            findings.append(
                Finding(
                    "PPTX structure",
                    name,
                    sum(1 for item in names if re.search(pattern, item)),
                    self.SOURCE,
                )
            )
        findings.append(Finding("PPTX structure", "Package tree", sorted(names), self.SOURCE))
        return findings

    def _properties(self, archive: zipfile.ZipFile, names: set[str]) -> list[Finding]:
        findings: list[Finding] = []
        for part, category in (
            (self.CORE_PATH, "OOXML Core Properties"),
            (self.APP_PATH, "OOXML Extended Properties"),
        ):
            if part not in names:
                findings.append(
                    Finding(category, "Part present", False, self.SOURCE, FindingLevel.INFO, location=part, details=f"В пакете отсутствует {part}. Этот набор свойств недоступен; отсутствие необязательных метаданных само по себе не указывает на изменение файла.")
                )
                continue
            root = self._read_xml(archive, part)
            for child in root:
                value = _element_value(child)
                if value not in (None, ""):
                    findings.append(
                        Finding(category, _local_name(child.tag), value, self.SOURCE, location=part)
                    )

        if self.CUSTOM_PATH in names:
            root = self._read_xml(archive, self.CUSTOM_PATH)
            for prop in root:
                name = prop.attrib.get("name", "unnamed")
                value = _element_value(next(iter(prop), prop))
                findings.append(
                    Finding(
                        "OOXML Custom Properties",
                        name,
                        value,
                        self.SOURCE,
                        location=self.CUSTOM_PATH,
                    )
                )
        else:
            findings.append(
                Finding("OOXML Custom Properties", "Part present", False, self.SOURCE, location=self.CUSTOM_PATH, details="В пакете нет docProps/custom.xml: пользовательские свойства не записаны.")
            )
        return findings

    def _comment_authors(self, archive: zipfile.ZipFile, names: set[str]) -> list[Finding]:
        path = "ppt/commentAuthors.xml"
        if path not in names:
            return [Finding("PPTX comment authors", "Authors", [], self.SOURCE)]
        root = self._read_xml(archive, path)
        authors = []
        for element in root.iter():
            if _local_name(element.tag) in {"cmAuthor", "author"}:
                authors.append(dict(element.attrib))
        return [Finding("PPTX comment authors", "Authors", authors, self.SOURCE, location=path)]

    def _comments(self, archive: zipfile.ZipFile, names: set[str]) -> list[Finding]:
        comments: list[dict[str, str]] = []
        for path in sorted(name for name in names if re.match(r"^ppt/comments/.+\.xml$", name)):
            root = self._read_xml(archive, path)
            for element in root.iter():
                if _local_name(element.tag) not in {"cm", "comment"}:
                    continue
                text = "".join(
                    node.text or "" for node in element.iter() if _local_name(node.tag) == "t"
                )
                comments.append(
                    {
                        "part": path,
                        "slide_hint": _number_from_name(path),
                        "author_id": element.attrib.get("authorId", element.attrib.get("authorId", "")),
                        "date": element.attrib.get("dt", element.attrib.get("created", "")),
                        "text": text,
                    }
                )
        return [Finding("PPTX comments", "Comments", comments, self.SOURCE)]

    def _notes(self, archive: zipfile.ZipFile, names: set[str]) -> list[Finding]:
        notes: list[dict[str, str]] = []
        for path in sorted(name for name in names if re.match(r"^ppt/notesSlides/.+\.xml$", name)):
            root = self._read_xml(archive, path)
            text = "\n".join(
                value for node in root.iter() if _local_name(node.tag) == "t" and (value := (node.text or "").strip())
            )
            notes.append({"part": path, "text": text})
        return [Finding("PPTX notes", "Notes", notes, self.SOURCE)]

    def _relationships(self, archive: zipfile.ZipFile, names: set[str]) -> list[Finding]:
        relationships: list[dict[str, str]] = []
        for path in sorted(name for name in names if name.endswith(".rels")):
            root = self._read_xml(archive, path)
            for element in root:
                if _local_name(element.tag) == "Relationship":
                    relationships.append({"part": path, **dict(element.attrib)})
        external = [item for item in relationships if item.get("TargetMode") == "External"]
        return [
            Finding("PPTX relationships", "Relationships", relationships, self.SOURCE),
            Finding(
                "PPTX relationships",
                "External relationships",
                external,
                self.SOURCE,
                FindingLevel.LOW if external else FindingLevel.INFO,
                details="External targets are listed but are never opened by the application.",
            ),
        ]

    def _embedded_objects(
        self, archive: zipfile.ZipFile, infos: list[zipfile.ZipInfo]
    ) -> list[Finding]:
        objects = []
        for info in infos:
            if not info.filename.startswith("ppt/embeddings/") or info.is_dir():
                continue
            digest = hashlib.sha256()
            with archive.open(info, "r") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            objects.append(
                {
                    "internal_name": info.filename,
                    "size": info.file_size,
                    "sha256": digest.hexdigest(),
                    "type": mimetypes.guess_type(info.filename)[0] or "unknown/binary",
                }
            )
        return [Finding("PPTX embedded objects", "Objects", objects, self.SOURCE)]

    def _presentation_details(self, archive: zipfile.ZipFile, names: set[str]) -> list[Finding]:
        hidden = 0
        for path in names:
            if re.match(r"^ppt/slides/slide\d+\.xml$", path):
                root = self._read_xml(archive, path)
                if root.attrib.get("show") in {"0", "false", "False"}:
                    hidden += 1
        return [Finding("PPTX structure", "Hidden slides", hidden, self.SOURCE)]

    def _read_xml(self, archive: zipfile.ZipFile, path: str) -> ElementTree.Element:
        info = archive.getinfo(path)
        if info.file_size > self.limits.max_xml_part_bytes:
            raise AnalysisError(f"XML part exceeds configured limit: {path}")
        with archive.open(info, "r") as stream:
            data = stream.read(self.limits.max_xml_part_bytes + 1)
        if len(data) > self.limits.max_xml_part_bytes:
            raise AnalysisError(f"XML part exceeds configured limit: {path}")
        try:
            return ElementTree.fromstring(data)
        except ElementTree.ParseError as exc:
            raise AnalysisError(f"Malformed XML part {path}: {exc}") from exc


def _validate_member_name(name: str) -> None:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", normalized):
        raise AnalysisError(f"Unsafe path in OOXML package: {name}")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _element_value(element: ElementTree.Element) -> str | None:
    if element.text and element.text.strip():
        return element.text.strip()
    values = [text.strip() for text in element.itertext() if text.strip()]
    return " ".join(values) or None


def _number_from_name(path: str) -> str:
    match = re.search(r"(\d+)", PurePosixPath(path).stem)
    return match.group(1) if match else ""
