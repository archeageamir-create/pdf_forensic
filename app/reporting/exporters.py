from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from app.models import AnalysisResult, Finding
from app.reporting.safety import atomic_report_path
from app.reporting.timeline import timeline_cells
from app.resources.labels import (
    category_label,
    display_value,
    parameter_description,
    parameter_label,
    source_label,
)


class JsonReportExporter:
    def export(self, result: AnalysisResult, destination: Path) -> Path:
        with atomic_report_path(result, destination) as temporary:
            temporary.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return destination


class HtmlReportExporter:
    def export(self, result: AnalysisResult, destination: Path) -> Path:
        with atomic_report_path(result, destination) as temporary:
            temporary.write_text(self.render(result), encoding="utf-8")
        return destination

    def render(self, result: AnalysisResult) -> str:
        evidence = result.evidence
        grouped: dict[str, list[Finding]] = defaultdict(list)
        for finding in result.findings:
            if finding.include_in_report:
                grouped[finding.category].append(finding)
        findings_html = "".join(
            f"<section><h2>{_h(category_label(category))}</h2>{_findings_table(items)}</section>"
            for category, items in grouped.items()
        )
        tools = "".join(
            "<tr>"
            f"<td>{_h(run.tool_name)}</td><td>{_h(run.version)}</td>"
            f"<td>{_h(display_value(run.status.value))}</td><td>{_h(run.exit_code)}</td>"
            f"<td><code>{_h(json.dumps(run.command, ensure_ascii=False))}</code></td>"
            f"<td><details><summary>Ввод / stdout / stderr</summary><pre>{_h(run.parsed_result.get('stdin_utf8', ''))}\n{_h(run.stdout)}"
            f"\n{_h(run.stderr)}</pre></details></td></tr>"
            for run in result.tool_runs
        )
        errors = "".join(f"<li>{_h(item)}</li>" for item in result.errors) or "<li>Нет</li>"
        summary = "".join(f"<li>{_h(item)}</li>" for item in result.summary) or "<li>Нет</li>"
        timeline = _artifact_table(result.artifacts.get("timeline", []))
        provenance = ("<section><h2>Авторство и история правок PDF</h2>" + _provenance_table(result.artifacts["pdf_provenance"]) + "</section>") if result.artifacts.get("pdf_provenance") else ""
        scope = result.artifacts.get("analysis_scope", {})
        coverage = scope.get("coverage", "Область проверки не записана в этой версии результата.") if isinstance(scope, dict) else ""
        status = "Часть выбранных проверок не завершена" if result.incomplete else "Выбранные проверки завершены"
        return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Технический отчёт</title>
<style>
body{{font:14px/1.5 Segoe UI,Arial,sans-serif;max-width:1200px;margin:32px auto;padding:0 20px;color:#202124;overflow-wrap:anywhere}}
h1,h2{{color:#17324d}} table{{border-collapse:collapse;width:100%;margin:12px 0 28px}}
th,td{{border:1px solid #ccd5df;padding:7px;text-align:left;vertical-align:top}}
th{{background:#edf3f8}} tr.conflict{{background:#fff1c9}} code,pre{{white-space:pre-wrap;word-break:break-word}} .notes{{white-space:pre-wrap}} small{{display:block;color:#555}}
.notice{{padding:12px;border:1px solid #b8cee0;border-radius:8px;background:#eef6fc}}
</style></head><body>
<h1>Document Forensic Inspector — технический отчёт</h1>
<p><strong>Оболочка, интеграция и сборка:</strong> Amirkhan Smagulov. Сторонние
open-source инструменты сохраняют своё авторство и лицензии.</p>
<p class="notice">Автоматические наблюдения требуют экспертной оценки. Различие метаданных
само по себе не является доказательством подделки.</p>
<h2>Исследуемый файл</h2>
<table><tr><th>Оригинал</th><td>{_h(evidence.original_path)}</td></tr>
<tr><th>Рабочая копия</th><td>{_h(evidence.working_copy_path)}</td></tr>
<tr><th>Формат / MIME</th><td>{_h(evidence.detected_format)} / {_h(evidence.mime_type)}</td></tr>
<tr><th>Размер</th><td>{evidence.size_bytes}</td></tr>
<tr><th>SHA-256</th><td><code>{evidence.sha256}</code></td></tr>
<tr><th>SHA-1</th><td><code>{evidence.sha1}</code></td></tr>
<tr><th>MD5</th><td><code>{evidence.md5}</code></td></tr></table>
<section><h2>Сводка</h2><ul>{summary}</ul></section>
<section><h2>Область проверки</h2><p><strong>{_h(status)}</strong></p><p>{_h(coverage)}</p><p>Режим: {_h(display_value(evidence.analysis_mode.value))}. Полнота относится к выбранным методам.</p></section>
{provenance}
{findings_html}
<section><h2>Хронология</h2>{timeline}</section>
<section><h2>Выводы пользователя</h2><p class="notes">{_h(evidence.user_conclusions) or 'Не заполнены'}</p>
<h3>Заметки</h3><p class="notes">{_h(evidence.user_notes) or 'Не заполнены'}</p></section>
<section><h2>Запуски инструментов</h2><table><thead><tr><th>Инструмент</th><th>Версия</th>
<th>Статус</th><th>Код</th><th>Команда</th><th>Полный вывод</th></tr></thead><tbody>{tools}</tbody></table></section>
<section><h2>Ошибки и ограничения запуска</h2><ul>{errors}</ul></section>
<p>Дата автоматизированного анализа: {_h(result.analyzed_at)}</p>
</body></html>"""


def _findings_table(findings: Iterable[Finding]) -> str:
    rows = "".join(
        f'<tr class="{"conflict" if item.conflict else ""}"><td>{_h(parameter_label(item.name))}</td>'
        f"<td><pre>{_h(display_value(item.value))}</pre></td><td>{_h(source_label(item.source))}<small>{_h(item.location)}</small></td>"
        f"<td>{_h(display_value(item.level.value))}<small>Эксперт: {_h(display_value(item.user_mark))}</small></td>"
        f"<td>{_h(parameter_description(item.name, item.details or item.description))}</td></tr>"
        for item in findings
    )
    return (
        "<table><thead><tr><th>Поле</th><th>Значение</th><th>Источник</th>"
        f"<th>Уровень внимания</th><th>Пояснение</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def _display(value: object) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return str(value)


def _h(value: object) -> str:
    return html.escape("" if value is None else str(value))


def _artifact_table(items: object) -> str:
    if not isinstance(items, list) or not items:
        return "<p>Нет данных</p>"
    rows = "".join(
        "<tr>" + "".join(f'<td class="notes">{_h(cell)}</td>' for cell in timeline_cells(item)) + "</tr>"
        for item in items
        if isinstance(item, dict)
    )
    return (
        "<table><thead><tr><th>Дата</th><th>Источник</th><th>Событие</th>"
        f"<th>Исходная строка</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def _provenance_table(value: object) -> str:
    if not isinstance(value, dict):
        return "<p>Для этого формата данные не формируются.</p>"
    caution = _h(value.get("caution", ""))
    signals = value.get("signals", [])
    if not isinstance(signals, list) or not signals:
        return f'<p class="notice">{caution or "Технические признаки не извлечены."}</p>'
    rows = "".join(
        "<tr>"
        f"<td>{_h(item.get('role', ''))}</td>"
        f"<td>{_h(_display(item.get('value', '')))}</td>"
        f"<td>{_h(source_label(str(item.get('source', ''))))}</td>"
        f"<td>{_h(item.get('strength', ''))}</td>"
        f"<td>{_h(item.get('explanation', ''))}</td></tr>"
        for item in signals
        if isinstance(item, dict)
    )
    return (
        f'<p class="notice">{caution}</p><table><thead><tr><th>Признак</th>'
        "<th>Значение</th><th>Источник</th><th>Сила признака</th>"
        f"<th>Как трактовать</th></tr></thead><tbody>{rows}</tbody></table>"
    )
