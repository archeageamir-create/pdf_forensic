from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from app.models import EvidenceFile, Finding


DATE_WORDS = {"date", "datetime", "moddate", "timestamp"}


def normalize_date(raw: str) -> dict[str, Any]:
    value = raw.strip()
    if not value:
        return {"raw": raw, "parsed": False, "timezone_present": False}
    pdf = re.fullmatch(
        r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?(Z|[+-]\d{2}'?\d{2}'?)?",
        value,
    )
    try:
        if pdf:
            parts = [int(pdf.group(1))]
            parts.extend(int(pdf.group(index) or 1) for index in (2, 3))
            parts.extend(int(pdf.group(index) or 0) for index in (4, 5, 6))
            zone_raw = pdf.group(7)
            zone = None
            if zone_raw == "Z":
                zone = UTC
            elif zone_raw:
                sign = 1 if zone_raw[0] == "+" else -1
                digits = re.sub(r"\D", "", zone_raw[1:])
                zone = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:4])))
            parsed = datetime(*parts, tzinfo=zone)
            return _date_result(raw, parsed, zone_raw is not None)
        exif = re.fullmatch(
            r"(\d{4}):(\d{2}):(\d{2})\s+(\d{2}):(\d{2}):(\d{2})(Z|[+-]\d{2}:?\d{2})?",
            value,
        )
        if exif:
            iso = (
                f"{exif.group(1)}-{exif.group(2)}-{exif.group(3)}T"
                f"{exif.group(4)}:{exif.group(5)}:{exif.group(6)}"
                f"{exif.group(7) or ''}"
            ).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(iso)
            return _date_result(raw, parsed, parsed.tzinfo is not None)
        iso = value.replace("Z", "+00:00") if value.endswith("Z") else value
        parsed = datetime.fromisoformat(iso)
        return _date_result(raw, parsed, parsed.tzinfo is not None)
    except (ValueError, OverflowError):
        return {"raw": raw, "parsed": False, "timezone_present": _has_timezone(value)}


class TimelineBuilder:
    def build(self, evidence: EvidenceFile, findings: list[Finding]) -> list[dict[str, Any]]:
        events = [
            self._event("File system", "File creation time", evidence.file_created_at),
            self._event("File system", "File modification time", evidence.file_modified_at),
            self._event("Analysis", "Evidence added", evidence.added_at),
        ]
        for finding in findings:
            if _is_date_field(finding.name):
                if isinstance(finding.value, (str, int, float)):
                    events.append(self._event(finding.source, finding.name, str(finding.value)))
            if finding.name in {"Word comments", "Tracked changes"} or finding.category == "PPTX comments":
                if not isinstance(finding.value, list):
                    continue
                for comment in finding.value:
                    if isinstance(comment, dict) and comment.get("date"):
                        events.append(
                            self._event(
                                finding.source,
                                f"{finding.name}: {comment.get('type', 'comment')} in {comment.get('part') or finding.location or ''}",
                                str(comment["date"]),
                            )
                        )
        events = [item for item in events if item["raw"]]
        events.sort(key=lambda item: (item.get("timestamp") is None, item.get("timestamp") or 0))
        return events

    @staticmethod
    def _event(source: str, name: str, raw: str) -> dict[str, Any]:
        return {"source": source, "name": name, **normalize_date(raw)}


def _date_result(raw: str, value: datetime, timezone_present: bool) -> dict[str, Any]:
    return {
        "raw": raw,
        "parsed": True,
        "normalized": value.isoformat(),
        "timezone_present": timezone_present,
        # An unknown timezone cannot locate an event on an absolute timeline.
        "timestamp": value.timestamp() if timezone_present else None,
    }


def _has_timezone(value: str) -> bool:
    return bool(re.search(r"(?:Z|[+-]\d{2}:?\d{2})$", value))


def _is_date_field(name: str) -> bool:
    folded = re.sub(r"[^a-z0-9]", "", name.casefold())
    # OOXML's LinksUpToDate is a boolean flag, not a timestamp.
    if folded.endswith("uptodate"):
        return False
    separated = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", separated)
    words = set(re.findall(r"[a-zа-я]+", separated.casefold()))
    if words & DATE_WORDS:
        return True
    # Lowercase keys and time fields with calendar meaning. Generic *Time
    # includes durations (ExposureTime, TotalTime), so is deliberately excluded.
    return folded.endswith(("createdate", "creationdate", "modifydate", "modificationdate", "accessdate", "metadatadate", "datetime", "created", "modified", "moddate", "timestamp", "creationtime", "createtime", "modificationtime", "modifytime", "accesstime", "savedtime")) or folded in {"datetimeoriginal", "datetimedigitized", "subsecdatetimeoriginal", "lastprinted"}
