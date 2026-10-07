"""Validate the shipped manual and create contact sheets for visual inspection."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
NAME = "DocumentForensicInspector-User-Guide-RU.pdf"


def main():
    pdf = ROOT / "output/pdf" / NAME
    bundled = ROOT / "docs/user-guide" / NAME
    assert pdf.read_bytes() == bundled.read_bytes()
    reader = PdfReader(pdf)
    assert len(reader.pages) == 20
    assert len(reader.outline) == 20
    assert sum(len(p.get("/Annots", [])) for p in reader.pages) >= 20
    pages = [p.extract_text() for p in reader.pages]
    assert all("Document Forensic Inspector" in text for text in pages)
    for index, keyword in ((1, "Быстрый старт"), (7, "Сбросить фильтры"), (8, "Запомнить первую дату"), (9, "неизвестен"), (11, "Прямого экспорта"), (17, "Сообщение до исследования"), (18, "%LOCALAPPDATA%")):
        assert keyword in pages[index], (index, keyword)
    assert all("\ufffd" not in text for text in pages)
    embedded = 0
    for font in reader.pages[0]["/Resources"]["/Font"].values():
        descriptor = font.get_object().get("/FontDescriptor")
        if descriptor and "/FontFile2" in descriptor.get_object():
            embedded += 1
    assert embedded >= 2
    render = ROOT / "tmp/pdfs/rendered"
    paths = sorted(render.glob("guide-*.png"))
    assert len(paths) == 20, "Render every PDF page with pdftoppm before verification"
    for group in range(5):
        sheet = Image.new("RGB", (1684, 1230), "#d9dce7")
        draw = ImageDraw.Draw(sheet)
        for i, path in enumerate(paths[group * 4:group * 4 + 4]):
            page = Image.open(path).convert("RGB")
            page.thumbnail((826, 585))
            x, y = (i % 2) * 842 + 8, (i // 2) * 615 + 20
            sheet.paste(page, (x, y))
            draw.text((x, y - 15), f"Page {group * 4 + i + 1}", fill="#252a3b")
        sheet.save(render / f"contact-{group + 1}.png")
    summary = {"pages": len(reader.pages), "bookmarks": len(reader.outline), "embedded_fonts": embedded, "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(), "bytes": pdf.stat().st_size, "text_and_links": "passed", "visual_review": "contact sheets prepared; inspect rendered pages separately"}
    (ROOT / "output/pdf/user-guide-verification.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
