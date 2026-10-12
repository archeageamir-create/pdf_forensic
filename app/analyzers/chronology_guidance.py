"""Comparison of timestamp records; not a reconstruction of real-world events."""

from datetime import UTC, datetime

from app.analyzers.timeline import normalize_date

SCOPE_LABELS = {
    "original_filesystem": "Файловая система оригинала",
    "working_copy_filesystem": "Файловая система рабочей копии",
    "analysis": "Служебное событие анализа",
    "embedded_metadata": "Запись внутри файла",
}


def event_guidance(event: dict) -> str:
    scope = event.get("scope", "embedded_metadata")
    parsed = normalize_date(str(event.get("comparison_raw") or event.get("raw", "")))
    context = {
        "original_filesystem": "Время экземпляра на исходном носителе. Копирование, восстановление и настройки ОС могут влиять на него; это не обязательно время первоначального создания содержания.",
        "working_copy_filesystem": "Время исследовательской копии. Оно может относиться к её созданию или чтению анализатором и не описывает происхождение документа.",
        "analysis": "Время действия программы исследования. Оно не является метаданными создания или редактирования представленного документа.",
        "embedded_metadata": "Временная запись в содержимом файла. Это заявленное значение, которое можно изменить или унаследовать; оно требует сопоставления с независимыми данными.",
    }.get(scope, "Происхождение временной записи требует уточнения.")
    if not parsed.get("parsed"):
        timing = "Дата не распознана. Сортировка и вычисление интервала по этой записи невозможны."
    elif parsed.get("precision") != "second":
        timing = "Дата записана с неполной точностью. Программа не подставляет недостающие компоненты для вычисления точного интервала."
    elif not parsed.get("timezone_present"):
        timing = "Часовой пояс неизвестен. Казахстан или UTC автоматически не подставляются; абсолютный порядок не установлен."
    else:
        utc = datetime.fromtimestamp(parsed["timestamp"], UTC).isoformat()
        timing = f"Нормализованная запись: {utc}. Это перевод записанного времени в UTC, а не подтверждение правильности часов."
    if event.get("timezone_finding_id"):
        timing += (
            f" Пояс взят из отдельного поля {event['timezone_field']} = {event['timezone_value']} "
            f"того же источника; id: {event['timezone_finding_id']}."
        )
    return context + "\n\n" + timing


def compare_events(first: dict, second: dict) -> str:
    a, b = (
        normalize_date(str(e.get("comparison_raw") or e.get("raw", "")))
        for e in (first, second)
    )
    intro = (
        f"А: {first.get('name', '')} — {first.get('raw', '')} ({first.get('source', '')})\n"
        f"Б: {second.get('name', '')} — {second.get('raw', '')} ({second.get('source', '')})\n\n"
    )
    for event in (first, second):
        if event.get("timezone_finding_id"):
            intro += (
                f"Пояс для {event.get('name', '')}: {event['timezone_field']} = {event['timezone_value']} "
                f"(id: {event['timezone_finding_id']}).\n\n"
            )
    if a.get("timestamp") is None or b.get("timestamp") is None:
        return (
            intro
            + "Точный интервал и абсолютный порядок не вычисляются: у одной из записей "
            "неизвестен пояс, неполная точность или не распознана дата. Сначала уточните исходные записи."
        )
    delta = b["timestamp"] - a["timestamp"]
    if delta == 0:
        result = "Записи соответствуют одному моменту после учёта явно указанных часовых поясов. Различие отображения не является временным расхождением."
    else:
        result = f"По записанным значениям Б {'позже' if delta > 0 else 'раньше'} А на {abs(delta):g} с ({abs(delta) / 3600:g} ч)."
    return (
        intro
        + result
        + "\n\nЭто разность временных записей, а не доказанная длительность действий. "
        "Перед интерпретацией сопоставьте смысл событий, версию объекта, происхождение полей и часы устройств. "
        "Дата изменения раньше даты создания может требовать проверки, но сама по себе не доказывает вмешательство."
    )
