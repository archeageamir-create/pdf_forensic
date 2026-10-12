"""Write a concise validation record from successful, completed local checks."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ROOT / ".verification"


def read(name: str) -> dict:
    return json.loads((CHECKS / name / "summary.json").read_text(encoding="utf-8"))


def main() -> int:
    executable = (
        ROOT
        / "dist/DocumentForensicInspectorPreview/DocumentForensicInspectorPreview.exe"
    )
    exe_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
    matrix = read("format-matrix-release")
    recovery = read("packaged-release-recovery")
    burst = read("portable-release-burst")
    for check in (matrix, recovery, burst):
        assert check["all_checks_passed"] and check["exe_sha256"] == exe_hash
    suite = next(
        ET.parse(CHECKS / "final-release-tests.xml").getroot().iter("testsuite")
    )
    assert (
        suite.get("failures") == "0"
        and suite.get("errors") == "0"
        and suite.get("skipped") == "0"
    )
    source_check = read("source-release-validation")
    assert source_check["all_checks_passed"]
    inventory = json.loads(
        (executable.parent / "_internal/app/resources/BUILD_INVENTORY.json").read_text(
            encoding="utf-8"
        )
    )
    actual = {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT / "app").rglob("*.py")
    }
    assert actual == inventory["source_sha256"]
    names = (
        ("Финальная GUI-сборка", "soak-release-gui-5min"),
        ("Ранний снимок исходников", "soak-frozen-83min"),
        ("Ранняя CLI-сборка", "soak-packaged-48min"),
        ("Ранняя GUI-сборка", "soak-final-gui-30min"),
    )
    rows = []
    soaks = []
    for title, name in names:
        data = read(name)
        assert data["completed"] and not data["failures"], name
        if title == "Финальная GUI-сборка":
            assert data["executable_sha256"] == exe_hash
        rows.append(
            f"| {title} | {data['duration_seconds'] / 60:.2f} | {data['files']} | {data['restarts']} | {data['peak_memory_bytes'] / 1024**2:.1f} | 0 |"
        )
        soaks.append(
            {
                "label": title,
                "check_directory": name,
                **{
                    key: data.get(key)
                    for key in (
                        "duration_seconds",
                        "files",
                        "restarts",
                        "queue",
                        "peak_memory_bytes",
                        "executable_sha256",
                    )
                },
            }
        )
    benchmark = read("benchmark-1000")
    assert benchmark["all_checks_passed"]
    record = {
        "date": "2026-09-14",
        "final_executable_sha256": exe_hash,
        "final_archive_sha256": burst["archive_sha256"],
        "current_application_sources_match_build": True,
        "tests": {
            key: suite.get(key)
            for key in ("tests", "failures", "errors", "skipped", "time")
        },
        "format_matrix_files": matrix["files"],
        "final_gui_burst": {
            key: burst[key]
            for key in (
                "files",
                "burst_seconds",
                "expected_partial_corrupt_files",
                "peak_parent_memory_bytes",
                "archive_entries_verified",
                "clean_system_path",
                "added_during_processing",
            )
        },
        "final_crash_recovery": {
            key: recovery[key]
            for key in (
                "interrupted_status",
                "recovered_status",
                "same_result_id",
                "original_unchanged",
                "saved_results",
            )
        },
        "soaks": soaks,
        "benchmark": benchmark,
    }
    target = ROOT / "docs/validation"
    target.mkdir(exist_ok=True)
    (target / "2026-09-14.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = f"""# Проверка универсальной preview-сборки

Дата: 14 сентября 2026. Локальная Windows-сборка, Python {inventory["python"]},
Qt {inventory["qt"]}. Все проверки использовали синтетические файлы и отдельные
хранилища. Рабочие материалы пользователя в тесты не включались.

## Финальный артефакт

EXE SHA-256: `{exe_hash}`.

ZIP SHA-256: `{burst["archive_sha256"]}`.

Хеши всех Python-файлов приложения совпадают с инвентарём сборки. После распаковки
архива проверены {burst["archive_entries_verified"]} файлов по манифесту. GUI запускается
из нового пути с кириллицей при PATH, содержащем только каталоги Windows.
Без установленного Python работают встроенные профили и упакованный PDFiD;
отсутствующие внешние движки отображаются как недоступные.

## Автоматические и практические проверки

- **{suite.get("tests")} тестов**, ошибок, падений и пропусков нет; {float(suite.get("time")):.2f} секунды.
  Проверены форматы, целостность, очередь, отмена, таймауты, восстановление,
  поиск, настройки, GUI и экспорт. Тесты также прошли из распакованного исходного архива.
- **{matrix["files"]} образца в настоящей EXE**: изображения, документы OOXML/PDF,
  ZIP, неизвестный файл и созданные ffmpeg медиаконтейнеры, включая M4A/WebM.
  JPEG с расширением PDF распознан по содержимому. EXIF rational сохраняет
  числитель и знаменатель, GPS извлекается, Unicode-пути ExifTool не искажаются.
  Выдержка, длительность и флаг LinksUpToDate не попадают в хронологию.
- **Очередь из {burst["files"]} файлов в GUI за {burst["burst_seconds"]:.2f} секунды**.
  Вторую половину добавили во время обработки первой. {burst["expected_partial_corrupt_files"]} намеренно повреждённых
  JPEG получили частичный результат, остальные завершены. Оригиналы сохранены.
  Это небольшие образцы для проверки очереди, а не прогноз скорости на любых файлах.
- **Аварийное восстановление EXE**: процесс принудительно завершён после взятия
  задания. Повторный запуск сохранил ровно один результат с прежним ID и тем же
  SHA-256 исходного файла размером {recovery["source_bytes"]:,} байт.
- **Поиск по проекту**: 1000 синтетических сохранённых исследований, 50 001 факт;
  поиск {benchmark["project_search_seconds"]:.3f} с, создание GUI {benchmark["gui_constructor_seconds"]:.3f} с.
  Это измерение чтения сохранённых данных, а не анализа 1000 исходных файлов.
- **DOCX-отчёты** проверены через отрисовку LibreOffice/Poppler: кириллица,
  длинные пути, EXIF-дроби, источники, повтор заголовков таблиц и страницы.
  Дополнительно проверены HTML-экранирование, полный JSON и ZIP-манифесты.

## Непрерывные прогоны

| Что проверялось | Минуты | Файлы | Перезапуски | Пиковая память, МиБ | Неожиданные сбои |
| --- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

Память измерена у родительского процесса, без суммирования дочерних анализаторов.
Повреждённые образцы входят в числа файлов и ожидаемо дают частичный результат.
Проверялись сохранение результатов, SHA-256 оригиналов и отсутствие дубликатов
после перезапусков. Ранние прогоны выполнялись на зафиксированных снимках до
последних исправлений хронологии, Unicode-ввода ExifTool и форматирования DOCX;
они не выдаются за длительный тест финального EXE. Для финального артефакта
отдельно выполнены матрица форматов, восстановление, перенос, пакетная очередь
и указанный выше непрерывный прогон GUI.

## Воспроизведение

Используйте `.venv/Scripts/python.exe` для сценариев в `scripts`:
`verify_format_matrix.py`, `verify_packaged_recovery.py`, `verify_preview_archive.py`,
`verify_source_archive.py`, `soak-queue.py`, `benchmark_project.py`.
Каждый запуск получает новый каталог `--output` либо соответствующий параметр,
чтобы не смешивать результаты. `build-preview.ps1` сам проверяет запуск GUI.

Структурированный итог: [validation/2026-09-14.json](validation/2026-09-14.json).
Локальные журналы и исходные результаты находятся в `.verification` и не
включены в исходный архив. Проверка на этом наборе не означает поддержку всех
вариантов файлов или сертификацию экспертной методики; конкретные границы
описаны в [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).
"""
    (ROOT / "docs/VALIDATION_UNIVERSAL_PREVIEW.md").write_text(report, encoding="utf-8")
    print(
        "Wrote docs/VALIDATION_UNIVERSAL_PREVIEW.md and docs/validation/2026-09-14.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
