"""Package the tested onedir preview, verifying that it matches current app sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLICATION = "DocumentForensicInspectorPreview"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "dist" / f"{APPLICATION}-Windows.zip"
    )
    args = parser.parse_args()
    folder = ROOT / "dist" / APPLICATION
    executable = folder / f"{APPLICATION}.exe"
    inventory = json.loads(
        (folder / "_internal/app/resources/BUILD_INVENTORY.json").read_text(
            encoding="utf-8"
        )
    )
    actual_sources = {
        path.relative_to(ROOT).as_posix(): sha256(path)
        for path in (ROOT / "app").rglob("*.py")
    }
    if actual_sources != inventory["source_sha256"]:
        raise RuntimeError(
            "The application sources changed after this build. Rebuild and validate before packaging."
        )
    if not executable.is_file():
        raise FileNotFoundError(executable)
    output = args.output.resolve()
    if output.is_relative_to(folder.resolve()):
        raise ValueError(
            "The output archive must be outside the application directory."
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError(f"Unexpected linked file: {path}")
    manifest = {
        "created_utc": datetime.now(UTC).isoformat(),
        "build": "universal-preview",
        "base_version": inventory["base_version"],
        "executable_sha256": sha256(executable),
        "current_app_sources_match_build": True,
        "files": [
            {
                "path": p.relative_to(folder).as_posix(),
                "size": p.stat().st_size,
                "sha256": sha256(p),
            }
            for p in files
        ],
    }
    readme = """ФОРЕНЗИК-ЛАБОРАТОРИЯ ФАЙЛОВ — UNIVERSAL PREVIEW

Распакуйте всю папку и откройте DocumentForensicInspectorPreview.exe.
Папка _internal должна оставаться рядом с EXE. Python устанавливать не нужно.

Добавьте файлы кнопкой или перетаскиванием. Начните с обзора, затем откройте
«Результаты»: поиск, исходные значения, источники и пояснения. «Поиск по проекту»
ищет по всем сохранённым исследованиям. «Очередь» позволяет наблюдать за папками.

Помощник исследования: пояснения к артефактам, основания, пределы интерпретации
и заготовки для заметок. В «Хронологии» выделите две записи с Ctrl, чтобы
сопоставить даты. НПВ в ходе исследования и сообщение до исследования разделены;
решение и вывод формулирует эксперт. Руководство: _internal/RESEARCH_ASSISTANT_KZ.md.

В этой сборке: PDF, Office OOXML, распространённые изображения, аудио/видео,
ZIP и базовая карточка других файлов. Глубина анализа зависит от формата.
ExifTool, qpdf, ffprobe и другие CLI-движки устанавливаются отдельно; их
доступность и пути показывает меню инструментов. Встроенные проверки работают
и без них. OCR, старые DOC/XLS и восстановление удалённых данных пока не входят.

Данные сохраняются в %LOCALAPPDATA%/DocumentForensicsLab. Наблюдение работает,
пока открыто приложение или запущен отдельный процесс демона. Файлы не
отправляются в облако. Сборка для Windows, на базе проекта версии 0.4.2;
это предварительная версия без цифровой подписи.

Состав и SHA-256 файлов: PREVIEW_MANIFEST.json.
Лицензии и инвентарь: _internal/app/resources.
"""
    with tempfile.NamedTemporaryFile(
        dir=output.parent, suffix=".tmp", delete=False
    ) as temporary:
        staged = Path(temporary.name)
    try:
        with zipfile.ZipFile(
            staged, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            for path in files:
                archive.write(
                    path, f"{APPLICATION}/{path.relative_to(folder).as_posix()}"
                )
            archive.writestr(
                f"{APPLICATION}/PREVIEW_MANIFEST.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            archive.writestr(
                f"{APPLICATION}/START_HERE.txt", readme.encode("utf-8-sig")
            )
        with zipfile.ZipFile(staged) as archive:
            bad_file = archive.testzip()
            if bad_file:
                raise RuntimeError(f"Archive validation failed: {bad_file}")
        staged.replace(output)
    finally:
        staged.unlink(missing_ok=True)
    digest = sha256(output)
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest}  {output.name}\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "archive": str(output),
                "bytes": output.stat().st_size,
                "sha256": digest,
                "files": len(files),
                "app_sources_match_build": True,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
