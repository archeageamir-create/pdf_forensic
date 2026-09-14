from __future__ import annotations

import json
from typing import Any

from app.models import AnalysisResult, ComparisonResult
from app.analyzers.overview import observations, original_integrity_label


class SummaryBuilder:
    def build(self, result: AnalysisResult) -> list[str]:
        messages = [
            f"Формат {result.evidence.detected_format}, размер {result.evidence.size_bytes:,} байт.",
            "Целостность рабочей копии подтверждена SHA-256.",
        ]
        conflicts = sum(1 for item in result.findings if item.conflict)
        messages.append(original_integrity_label(result) + ".")
        messages = observations(result) + messages
        if conflicts:
            messages.append(f"Обнаружено различий метаданных: {conflicts}; требуется экспертная оценка.")
        values = {item.name: item.value for item in result.findings}
        confirmed_javascript = int(values.get("JavaScript actions in object dictionaries", 0) or 0)
        raw_javascript = int(values.get("JavaScript markers", 0) or 0)
        if confirmed_javascript:
            messages.append(
                "В словарях PDF-объектов подтверждены JavaScript-действия: "
                f"{confirmed_javascript}. Код автоматически не выполнялся."
            )
        elif raw_javascript:
            messages.append(
                f"В байтах найдено последовательностей /JS: {raw_javascript}, но объектный "
                "индекс qpdf не подтвердил JavaScript-действие."
            )
        if values.get("Signature count"):
            messages.append(f"Обнаружено подписей: {values['Signature count']}.")
        if values.get("Incremental updates"):
            messages.append(f"Инкрементальных обновлений: {values['Incremental updates']}.")
        unavailable = [run.tool_name for run in result.tool_runs if run.status.value != "completed"]
        if unavailable:
            messages.append("Часть методов не завершена: " + ", ".join(unavailable) + ".")
        if not result.errors and not unavailable:
            messages.append("Все выбранные методы анализа завершены.")
        return messages


class FileComparator:
    def compare(self, left: AnalysisResult, right: AnalysisResult) -> ComparisonResult:
        items: list[dict[str, Any]] = []
        self._add(items, "SHA-256", left.evidence.sha256, right.evidence.sha256)
        self._add(items, "Size", left.evidence.size_bytes, right.evidence.size_bytes)
        self._add(items, "Format", left.evidence.kind.value, right.evidence.kind.value)

        left_values = _finding_map(left)
        right_values = _finding_map(right)
        for key in sorted(set(left_values) | set(right_values)):
            self._add(items, key, left_values.get(key), right_values.get(key))

        for artifact in ("pdf_revisions", "pdf_attachments", "pdf_signatures"):
            self._add(
                items,
                artifact,
                left.artifacts.get(artifact),
                right.artifacts.get(artifact),
            )
        return ComparisonResult(left.evidence.id, right.evidence.id, items)

    @staticmethod
    def _add(items: list[dict[str, Any]], field: str, left: Any, right: Any) -> None:
        if left is None and right is not None:
            status = "added"
        elif left is not None and right is None:
            status = "removed"
        elif _stable(left) == _stable(right):
            status = "same"
        else:
            status = "changed"
        items.append({"field": field, "left": left, "right": right, "status": status})


def _finding_map(result: AnalysisResult) -> dict[str, Any]:
    # Work-copy paths/timestamps and execution diagnostics differ on every run.
    excluded_categories = {"Integrity", "Tool diagnostics", "Metadata conflicts"}
    grouped = {}
    for item in result.findings:
        if item.category in excluded_categories or item.source == "ExifTool/System" or item.name in {"FileName", "Directory", "FileAccessDate", "FileCreateDate", "FileModifyDate"}:
            continue
        key = f"{item.category}/{item.name}/{item.source}" + (f" [{item.location}]" if item.location else "")
        grouped.setdefault(key, []).append(item.value)
    return {key: values[0] if len(values) == 1 else values for key, values in grouped.items()}


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
