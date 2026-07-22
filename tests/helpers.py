from __future__ import annotations

import zipfile
from pathlib import Path


def write_minimal_pdf(path: Path, extra: bytes = b"") -> bytes:
    parts = [b"%PDF-1.7\n"]
    offsets: list[int] = []
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R /AcroForm 4 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Fields [] >>\nendobj\n",
    ]
    current = len(parts[0])
    for item in objects:
        offsets.append(current)
        parts.append(item)
        current += len(item)
    xref_offset = current
    xref = b"xref\n0 5\n0000000000 65535 f \n" + b"".join(
        f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets
    )
    trailer = (
        b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    data = b"".join(parts) + xref + trailer + extra
    path.write_bytes(data)
    return data


def write_test_pptx(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "ppt/presentation.xml",
            '<p:presentation xmlns:p="urn:p"><p:sldIdLst><p:sldId id="1"/></p:sldIdLst></p:presentation>',
        )
        archive.writestr(
            "docProps/core.xml",
            '<cp:coreProperties xmlns:cp="urn:cp" xmlns:dc="urn:dc" '
            'xmlns:dcterms="urn:dcterms"><dc:creator>Иван</dc:creator>'
            '<cp:lastModifiedBy>Ольга</cp:lastModifiedBy>'
            '<dcterms:created>2026-01-01T10:00:00Z</dcterms:created>'
            '<cp:revision>7</cp:revision></cp:coreProperties>',
        )
        archive.writestr(
            "docProps/app.xml",
            '<Properties xmlns="urn:app"><Application>PowerPoint</Application>'
            '<AppVersion>16.0</AppVersion><Company>ANSE</Company><Slides>1</Slides></Properties>',
        )
        archive.writestr(
            "docProps/custom.xml",
            '<Properties xmlns="urn:custom"><property name="Case">'
            '<value>42</value></property></Properties>',
        )
        archive.writestr(
            "ppt/commentAuthors.xml",
            '<p:cmAuthorLst xmlns:p="urn:p"><p:cmAuthor id="0" name="Эксперт" '
            'initials="Э"/></p:cmAuthorLst>',
        )
        archive.writestr(
            "ppt/comments/comment1.xml",
            '<p:cmLst xmlns:p="urn:p" xmlns:a="urn:a"><p:cm authorId="0" '
            'dt="2026-01-02T12:00:00Z"><p:text><a:t>Проверить</a:t></p:text>'
            '</p:cm></p:cmLst>',
        )
        archive.writestr(
            "ppt/notesSlides/notesSlide1.xml",
            '<p:notes xmlns:p="urn:p" xmlns:a="urn:a"><a:t>Заметка</a:t></p:notes>',
        )
        archive.writestr(
            "ppt/slides/slide1.xml", '<p:sld xmlns:p="urn:p" show="0"/>'
        )
        archive.writestr(
            "ppt/slides/_rels/slide1.xml.rels",
            '<Relationships xmlns="urn:rels"><Relationship Id="rId1" '
            'Type="hyperlink" Target="https://example.invalid" TargetMode="External"/>'
            '</Relationships>',
        )
        archive.writestr("ppt/embeddings/embedded.xlsx", b"PK\x03\x04embedded")

