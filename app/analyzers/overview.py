from __future__ import annotations

from app.models import AnalysisResult, Finding, FindingLevel


def needs_attention(finding: Finding) -> bool:
    return finding.conflict or finding.level in {
        FindingLevel.LOW,
        FindingLevel.MEDIUM,
        FindingLevel.HIGH,
        FindingLevel.MANUAL_REVIEW,
    }


def original_integrity_label(result: AnalysisResult) -> str:
    check = next(
        (
            f
            for f in result.findings
            if f.name == "Original hash unchanged during analysis"
            and f.category == "Integrity" and f.source == "SHA-256"
        ),
        None,
    )
    if check is None:
        return "Повторная проверка оригинала не записана"
    return (
        "Хеш оригинала до и после анализа совпал"
        if check.value is True
        else "Неизменность оригинала не подтверждена — откройте результаты проверки"
    )


def observations(result: AnalysisResult) -> list[str]:
    """Deterministic explanations of recorded facts, never a forgery score."""
    messages = []
    values = {f.name: f.value for f in result.findings}
    if values.get("Extension matches signature") is False:
        messages.append(
            "Расширение имени не совпадает с содержимым. Проверьте, как файл был получен или переименован."
        )
    if any(f.category == "GPS" for f in result.findings):
        messages.append(
            "Есть данные GPS. Откройте группу «GPS / местоположение» и сопоставьте координаты с обстоятельствами съёмки."
        )
    if values.get("Tracked changes count"):
        messages.append(
            f"В Word сохранены исправления: {values['Tracked changes count']}. Доступны их типы, заявленные авторы и даты."
        )
    if values.get("Hidden worksheets"):
        messages.append(
            f"В Excel есть скрытые листы: {len(values['Hidden worksheets'])}. Их имена доступны в результатах."
        )
    if values.get("Macro parts"):
        messages.append("В документе есть части с макросами VBA. Их код не запускался.")
    if values.get("External relationships"):
        messages.append(
            "Документ ссылается на внешние ресурсы. Адреса можно посмотреть; переходы по ним не выполнялись."
        )
    if values.get("Unsafe archive paths"):
        messages.append(
            "В ZIP есть пути за пределы папки распаковки. Архив только перечислен, записи не извлекались."
        )
    if result.errors:
        messages.append(
            "Некоторые проверки завершились с ошибкой. Откройте технические данные; доступные результаты сохранены."
        )
    return messages
