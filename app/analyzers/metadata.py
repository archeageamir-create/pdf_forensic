from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.analyzers.timeline import normalize_date
from app.models import Finding, FindingLevel


class MetadataConflictDetector:
    """Flags source differences with neutral language and reproducible rule details."""

    ALIASES = {
        "author": "author",
        "creator": "creator_application",
        "creatortool": "creator_application",
        "createdby": "author",
        "lastmodifiedby": "last_editor",
        "lastsavedby": "last_editor",
        "title": "title",
        "subject": "subject",
        "description": "description",
        "keywords": "keywords",
        "createdate": "created",
        "creationdate": "created",
        "created": "created",
        "modifydate": "modified",
        "moddate": "modified",
        "modified": "modified",
        "metadatadate": "metadata_date",
        "producer": "producer",
        "application": "application",
        "appversion": "application_version",
        "company": "organization",
        "manager": "manager",
        "revision": "revision",
    }

    def mark(self, findings: list[Finding]) -> list[Finding]:
        grouped: dict[str, list[Finding]] = defaultdict(list)
        for finding in findings:
            canonical = self._canonical(finding)
            if canonical and finding.value not in (None, "", [], {}):
                grouped[canonical].append(finding)

        appended: list[Finding] = []
        for canonical, items in grouped.items():
            sources = {item.source for item in items}
            values = {_normalize_value(item.value) for item in items}
            if len(sources) < 2 or len(values) <= 1:
                continue
            originals = [{"source": item.source, "value": item.value, "finding_id": item.id,
                          "location": item.location} for item in items]
            normalized = sorted(values)
            detail = (
                "Различаются записи или представления метаданных. Разные анализаторы могут читать одно "
                "и то же поле и не являются независимыми подтверждениями события. Расхождение требует "
                "проверки смысла полей и само по себе не доказывает подделку."
            )
            for item in items:
                item.conflict = True
                item.level = FindingLevel.LOW
                item.details = "\n".join(part for part in (item.details, detail) if part)
            appended.append(
                Finding(
                    "Metadata conflicts",
                    f"Different values: {canonical}",
                    {"original": originals, "normalized": normalized},
                    "Metadata comparison rule",
                    FindingLevel.LOW,
                    conflict=True,
                    description=f"Compared field: {canonical}",
                    details=detail,
                )
            )

        appended.extend(self._date_rules(grouped))
        findings.extend(appended)
        return findings

    def _canonical(self, finding: Finding) -> str | None:
        normalized = _normalize_name(finding.name)
        if normalized == "creator" and (
            finding.category == "XMP"
            or finding.category == "OOXML Core Properties"
        ):
            return "author"
        return self.ALIASES.get(normalized)

    def _date_rules(self, grouped: dict[str, list[Finding]]) -> list[Finding]:
        results: list[Finding] = []
        created = grouped.get("created", [])
        modified = grouped.get("modified", [])
        for created_item in created:
            for modified_item in modified:
                if created_item.source != modified_item.source:
                    continue
                left = normalize_date(str(created_item.value))
                right = normalize_date(str(modified_item.value))
                if left.get("timezone_present") != right.get("timezone_present"):
                    continue
                if left.get("timestamp") is not None and right.get("timestamp") is not None:
                    if float(right["timestamp"]) < float(left["timestamp"]):
                        results.append(
                            Finding(
                                "Metadata conflicts",
                                "Modification date precedes creation date",
                                {
                                    "source": created_item.source,
                                    "created": created_item.value,
                                    "modified": modified_item.value,
                                },
                                "Chronology rule",
                                FindingLevel.MEDIUM,
                                conflict=True,
                                details="Dates were compared only after successful normalization.",
                            )
                        )
        all_dates = created + modified + grouped.get("metadata_date", [])
        timezone_flags = {
            bool(normalize_date(str(item.value)).get("timezone_present")) for item in all_dates
        }
        if len(timezone_flags) > 1:
            results.append(
                Finding(
                    "Metadata conflicts",
                    "Mixed timezone presence",
                    [{"source": item.source, "value": item.value} for item in all_dates],
                    "Timezone comparison rule",
                    FindingLevel.LOW,
                    conflict=True,
                    details="Some date strings specify a timezone and others do not; none was added automatically.",
                )
            )
        return results


def _normalize_name(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _normalize_value(value: Any) -> str:
    if isinstance(value, list):
        return "|".join(sorted(_normalize_value(item) for item in value))
    if isinstance(value, dict):
        return "|".join(
            f"{key}:{_normalize_value(item)}" for key, item in sorted(value.items())
        )
    date = normalize_date(str(value))
    if date.get("parsed"):
        if date.get("timestamp") is not None:
            return f"UTC timestamp: {date['timestamp']}"
        return str(date["normalized"])
    return " ".join(str(value).strip().split()).casefold()
