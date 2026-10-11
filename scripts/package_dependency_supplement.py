"""Package the verified source supplement without duplicating the 1.4 GB base archive."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import __version__
from scripts.verify_source_delivery import SOURCES, digest, verify


def main() -> None:
    print(verify(), flush=True)
    lock = json.loads((ROOT / "compliance/SOURCE_DELIVERY.json").read_text(encoding="utf-8"))
    target = ROOT / "dist" / f"dependency-supplement-{__version__}"
    target.mkdir(parents=True, exist_ok=True)
    name = f"Dependency-Source-Supplement-{__version__}.zip"
    output = target / name
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for item in lock["archives"]:
            if item["file"].startswith("supplement/"):
                archive.write(SOURCES / item["file"], item["file"])
        for item in lock["records"]:
            archive.write(ROOT / item["file"], item["file"])
        for file in ("compliance/SOURCE_DELIVERY.json", "compliance/THIRD_PARTY_SOURCES.json", "docs/DEPENDENCY_SOURCES.md", "SOURCE_OFFER.md"):
            archive.write(ROOT / file, file)
        # The exact self-built engine is convenient for rebuilding the shell.
        # Its full corresponding source and build script are also supplied.
        archive.write(ROOT / ".downloads/runtime/ffprobe-8.1.2-anse-lgpl.zip", "build-cache/ffprobe-8.1.2-anse-lgpl.zip")
    parts = []
    with output.open("rb") as stream:
        while chunk := stream.read(90 * 1024 * 1024):
            part = target / f"{name}.{len(parts) + 1:03}"
            part.write_bytes(chunk)
            parts.append({"name": part.name, "bytes": len(chunk), "sha256": hashlib.sha256(chunk).hexdigest()})
    (target / "SUPPLEMENT-PARTS.json").write_text(json.dumps({"archive": name, "sha256": digest(output), "parts": parts}, indent=2), encoding="utf-8")
    shutil.copy2(ROOT / "scripts/Assemble-Source-Supplement.ps1", target)
    (target / "README-RU.txt").write_text(
        "ДОПОЛНЕНИЕ К ИСХОДНИКАМ — 0.5.1\n\n"
        "Для запуска программы эти файлы не нужны.\n"
        "Для изучения и пересборки компонентов скачайте все части .001, .002 и далее,\n"
        "SUPPLEMENT-PARTS.json и Assemble-Source-Supplement.ps1 в одну папку.\n"
        "Запустите сценарий через PowerShell. Он проверит каждую часть и соберёт ZIP.\n"
        "Распакуйте ZIP; порядок пересборки описан в docs/DEPENDENCY_SOURCES.md.\n\n"
        "Это дополнение используют вместе с основным Dependency-Sources-0.5.0.zip\n"
        "из соседней папки. Версии восьми исходных архивов в нём не изменились.\n"
        "Здесь добавлены точные исходники библиотек, рецепты, патчи и записи проверки.\n"
        "Контрольные суммы полного комплекта: compliance/SOURCE_DELIVERY.json.\n",
        encoding="utf-8-sig",
    )
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():
            raise ValueError("Source supplement ZIP is corrupt")
    print(json.dumps({"archive": name, "bytes": output.stat().st_size, "parts": len(parts)}), flush=True)


if __name__ == "__main__":
    main()
