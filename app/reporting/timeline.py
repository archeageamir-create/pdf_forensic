"""Shared timeline presentation; preserve source/offset provenance in reports."""
from app.analyzers.chronology_guidance import SCOPE_LABELS
from app.analyzers.timeline import normalize_date
from app.resources.labels import parameter_label, source_label


def timeline_cells(item: dict) -> tuple[str, str, str, str]:
    parsed = normalize_date(str(item.get("comparison_raw") or item.get("raw", "")))
    date = str(parsed.get("normalized") or item.get("raw", ""))
    if not parsed.get("timezone_present"):
        date += "\nЧасовой пояс не указан"
    if parsed.get("parsed") and parsed.get("precision") != "second":
        date += "\nНеполная точность: точный интервал не вычисляется"
    if not parsed.get("parsed"):
        date += "\nДата не распознана"
    source = source_label(str(item.get("source", "")))
    if item.get("scope") in SCOPE_LABELS:
        source += "\n" + SCOPE_LABELS[item["scope"]]
    raw = str(item.get("raw", ""))
    if item.get("timezone_finding_id"):
        raw += f"\nПояс из {item.get('timezone_field')}: {item.get('timezone_value')}; id: {item['timezone_finding_id']}"
    if item.get("finding_id"):
        raw += "\nid: " + str(item["finding_id"])
    return date, source, parameter_label(str(item.get("name", ""))), raw
