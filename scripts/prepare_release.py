"""Prepare versioned release metadata, corporate artwork and actual inventory."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import __version__
from scripts.prepare_preview_build import prepare


def main() -> None:
    from PySide6.QtCore import Qt, QRectF
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PIL import Image

    application = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(ROOT / "app/resources/branding/anse-logo.svg"))
    if not renderer.isValid():
        raise ValueError("Invalid ANSE logo")
    brand = ROOT / "app/resources/branding"
    for name, width, height in (("wizard.bmp", 164, 314), ("wizard-small.bmp", 55, 55), ("icon.png", 256, 256)):
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        logo_width = width - 12
        logo_height = logo_width * 140 / 620
        renderer.render(painter, QRectF(6, (height - logo_height) / 2, logo_width, logo_height))
        painter.end()
        if not image.save(str(brand / name)):
            raise OSError(f"Cannot render {name}")
    with Image.open(brand / "icon.png") as icon:
        icon.save(ROOT / "app/resources/icons/anse.ico", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    del application
    numbers = tuple(map(int, __version__.split("."))) + (0,)
    version = f'''VSVersionInfo(
 ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)),
 kids=[StringFileInfo([StringTable('040904B0', [
 StringStruct('CompanyName', 'ТОО «АНСЭ»'),
 StringStruct('FileDescription', 'Document Forensic Inspector — АНСЭ'),
 StringStruct('FileVersion', '{__version__}.0'),
 StringStruct('ProductVersion', '{__version__}'),
 StringStruct('InternalName', 'DocumentForensicInspector'),
 StringStruct('OriginalFilename', 'DocumentForensicInspector.exe'),
 StringStruct('ProductName', 'Document Forensic Inspector'),
 StringStruct('LegalCopyright', '© 2026 ТОО «АНСЭ». Права защищены в пределах применимых лицензий.')
 ])]), VarFileInfo([VarStruct('Translation',[1033,1200])])])
'''
    (ROOT / "app/resources/version_info.txt").write_text(version, encoding="utf-8")
    (ROOT / "installer/version.iss").write_text(f'#define MyAppVersion "{__version__}"\n', encoding="utf-8-sig")
    resources = prepare(release=True)
    for name in ("SBOM.spdx.json", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(resources / name, ROOT / name)
        shutil.copy2(resources / name, ROOT / "app/resources" / name)
    for name in ("LICENSE", "NOTICE", "SOURCE_OFFER.md"):
        shutil.copy2(ROOT / name, ROOT / "app/resources/compliance" / name)
    print(f"Release metadata: {__version__}")


if __name__ == "__main__":
    main()
