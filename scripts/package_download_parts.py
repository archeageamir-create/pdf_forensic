"""Split final distribution files for a transport with a 100 MiB file limit."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package(source: Path, output: Path) -> dict:
    digest = hashlib.sha256()
    parts = []
    with source.open("rb") as stream:
        index = 1
        while data := stream.read(90 * 1024 * 1024):
            path = output / f"{source.name}.{index:03d}"
            path.write_bytes(data)
            parts.append(
                {
                    "file": path.name,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            digest.update(data)
            index += 1
    return {
        "file": source.name,
        "bytes": source.stat().st_size,
        "sha256": digest.hexdigest(),
        "parts": parts,
    }


def main() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from app import __version__

    output = ROOT / "dist" / f"download-parts-{__version__}"
    output.mkdir(parents=True, exist_ok=False)
    catalog = {
        name: package(ROOT / "dist" / filename, output)
        for name, filename in (
            ("installer", f"DocumentForensicInspector-Setup-{__version__}.exe"),
            ("portable", f"DocumentForensicInspector-{__version__}-Windows.zip"),
        )
    }
    (output / "DOWNLOAD-PARTS.json").write_text(
        json.dumps(catalog, indent=2) + "\n", encoding="utf-8"
    )
    shutil.copy2(ROOT / "scripts/Assemble-Distribution.ps1", output)
    for filename, arguments in [
        ("Install.cmd", "-Package installer -LaunchInstaller"),
        ("Portable.cmd", "-Package portable"),
    ]:
        (output / filename).write_text(
            '@echo off\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Assemble-Distribution.ps1" '
            + arguments
            + "\nif errorlevel 1 echo Download failed. Read the error above.\npause\n",
            encoding="ascii",
        )
    (output / "README-RU.txt").write_text(
        "УСТАНОВКА ИЗ КОМПЛЕКТА НА GOOGLE ДИСКЕ\n\n"
        "1. Скачайте эту папку целиком. Если Диск создал ZIP, распакуйте его.\n"
        "2. Откройте Install.cmd двойным щелчком. Он проверит части, соберёт\n"
        "   цельный установщик и откроет обычный мастер установки.\n"
        "3. Дальше следуйте подсказкам мастера. Команды вводить не нужно.\n\n"
        "Для версии без установки откройте Portable.cmd. Он соберёт Windows.zip.\n"
        "Распакуйте весь полученный ZIP и откройте DocumentForensicInspector.exe.\n\n"
        "Программа, Python, Java и анализаторы уже\n"
        "внутри установщика. Интернет при сборке и установке не требуется.\n"
        "Если не хватает части или сумма не совпала, установка не начнётся.\n"
        "Скачайте указанную часть заново. Не переименовывайте файлы комплекта.\n",
        encoding="utf-8-sig",
    )
    print(output)


if __name__ == "__main__":
    main()
