from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.models import FileKind


@dataclass(frozen=True, slots=True)
class FormatProfile:
    label: str
    mime: str
    extensions: tuple[str, ...]
    analyzer: str
    coverage: str


PROFILES = {
    FileKind.PDF: FormatProfile("PDF", "application/pdf", (".pdf",), "pdf", "Структура, метаданные, ревизии и подписи PDF — в зависимости от режима и доступных инструментов."),
    FileKind.PPTX: FormatProfile("PowerPoint / OOXML", "application/vnd.openxmlformats-officedocument.presentationml.presentation", (".pptx", ".pptm", ".potx", ".potm", ".ppsx", ".ppsm"), "pptx", "Метаданные, слайды, заметки, комментарии, связи и встроенные объекты."),
    FileKind.DOCX: FormatProfile("Word / OOXML", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", (".docx", ".docm", ".dotx", ".dotm"), "ooxml", "Метаданные, комментарии, сохранённые исправления, связи, наличие макросов и вложений."),
    FileKind.XLSX: FormatProfile("Excel / OOXML", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", (".xlsx", ".xlsm", ".xltx", ".xltm"), "ooxml", "Метаданные, список и видимость листов, внешние связи, наличие макросов и вложений. Формулы не вычисляются."),
    FileKind.ZIP: FormatProfile("ZIP", "application/zip", (".zip",), "archive", "Список записей, размеры, даты и флаги шифрования. Содержимое записей не распаковывается и не анализируется."),
    FileKind.BINARY: FormatProfile("Неизвестный формат", "application/octet-stream", (), "generic", "Базовый анализ: хеши, первые байты, свойства файла и доступные метаданные ExifTool. Специализированный анализатор не выбран."),
}
for kind, mime, extensions in (
    (FileKind.JPEG, "image/jpeg", (".jpg", ".jpeg", ".jpe")),
    (FileKind.PNG, "image/png", (".png",)),
    (FileKind.TIFF, "image/tiff", (".tif", ".tiff")),
    (FileKind.GIF, "image/gif", (".gif",)),
    (FileKind.WEBP, "image/webp", (".webp",)),
    (FileKind.BMP, "image/bmp", (".bmp",)),
):
    PROFILES[kind] = FormatProfile(kind.value.upper(), mime, extensions, "image", "Размеры и режим изображения, EXIF и доступные метаданные. Пиксельная экспертиза монтажа не выполняется.")
for kind, mime, extensions in (
    (FileKind.MP4, "video/mp4", (".mp4", ".m4a", ".m4v", ".3gp", ".3g2")),
    (FileKind.MOV, "video/quicktime", (".mov", ".qt")),
    (FileKind.MP3, "audio/mpeg", (".mp3",)),
    (FileKind.WAV, "audio/wav", (".wav",)),
    (FileKind.FLAC, "audio/flac", (".flac",)),
    (FileKind.OGG, "application/ogg", (".ogg", ".oga", ".ogv", ".opus")),
    (FileKind.MKV, "video/x-matroska", (".mkv", ".webm", ".mka")),
    (FileKind.AVI, "video/x-msvideo", (".avi",)),
):
    PROFILES[kind] = FormatProfile(kind.value.upper(), mime, extensions, "media", "Метаданные ExifTool; контейнер, дорожки и кодеки через ffprobe, если он установлен и выбран. Признаки монтажа автоматически не устанавливаются.")


def detect_file_kind(path: Path) -> FileKind:
    """Identify a container from bytes; filename extensions never select a parser."""
    with path.open("rb") as stream:
        header = stream.read(64)
    for magic, kind in (
        (b"%PDF-", FileKind.PDF), (b"\xff\xd8\xff", FileKind.JPEG),
        (b"\x89PNG\r\n\x1a\n", FileKind.PNG), (b"II*\0", FileKind.TIFF),
        (b"MM\0*", FileKind.TIFF), (b"II+\0", FileKind.TIFF),
        (b"MM\0+", FileKind.TIFF), (b"GIF87a", FileKind.GIF),
        (b"GIF89a", FileKind.GIF), (b"BM", FileKind.BMP),
        (b"fLaC", FileKind.FLAC), (b"OggS", FileKind.OGG),
        (b"ID3", FileKind.MP3), (b"\x1aE\xdf\xa3", FileKind.MKV),
    ):
        if header.startswith(magic):
            return kind
    if header.startswith(b"RIFF"):
        return {b"WEBP": FileKind.WEBP, b"WAVE": FileKind.WAV, b"AVI ": FileKind.AVI}.get(header[8:12], FileKind.BINARY)
    if len(header) >= 12 and header[4:8] == b"ftyp":
        brand = header[8:12]
        if brand == b"qt  ":
            return FileKind.MOV
        if brand in {b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V ", b"M4A ", b"MSNV", b"dash"} or brand.startswith(b"3g"):
            return FileKind.MP4
        # HEIF/AVIF also use ftyp; do not mistake them for video.
    if len(header) >= 3 and header[0] == 255 and header[1] & 0xE6 == 0xE2 and header[2] & 0xF0 not in (0, 0xF0):
        return FileKind.MP3
    if header.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" in names:
                    for part, kind in (("ppt/presentation.xml", FileKind.PPTX), ("word/document.xml", FileKind.DOCX), ("xl/workbook.xml", FileKind.XLSX)):
                        if part in names:
                            return kind
        except (OSError, zipfile.BadZipFile):
            pass
        return FileKind.ZIP
    return FileKind.BINARY


def mime_for_kind(kind: FileKind) -> str:
    return PROFILES[kind].mime


def canonical_extension(kind: FileKind) -> str:
    extensions = PROFILES[kind].extensions
    return extensions[0] if extensions else ".bin"


def extension_matches(extension: str, kind: FileKind) -> bool | None:
    if kind == FileKind.BINARY:
        return None
    return extension.casefold() in PROFILES[kind].extensions
