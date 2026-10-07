from __future__ import annotations

import json
import sys
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Any

from app.core.config import AppConfig

TOOL_LOCATIONS = {
    "exiftool_command", "ffprobe_command", "qpdf_command", "pdfcpu_command",
    "java_command", "poppler_bin_dir", "jhove_dir", "verapdf_dir", "pdfbox_jar",
    "pdfid_script", "pdf_parser_script",
}


def _bundled_or_legacy_tool(value: Any) -> bool:
    if value in (None, "", "exiftool", "ffprobe", "qpdf", "pdfcpu", "java"):
        return True
    normalized = str(value).replace("\\", "/").casefold()
    return any(part in normalized for part in ("/app/resources/binaries/", "/app/resources/tools/"))


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, defaults: AppConfig | None = None) -> AppConfig:
        config = defaults or AppConfig.default()
        if not self.path.is_file():
            return config
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return config
        if not isinstance(raw, dict):
            return config
        allowed = {item.name: item for item in fields(AppConfig)}
        updates: dict[str, Any] = {}
        for key, value in raw.items():
            if key not in allowed:
                continue
            if getattr(sys, "frozen", False) and key in TOOL_LOCATIONS and _bundled_or_legacy_tool(value):
                # Settings may come from the earlier lightweight preview or
                # another installation directory. Rebase bundled paths.
                continue
            default_value = getattr(config, key)
            if key.endswith("_path") or key.endswith("_dir") or key in {
                "pdfid_script",
                "pdf_parser_script",
                "report_template",
                "pdfbox_jar",
            }:
                if isinstance(value, str) and value.strip():
                    updates[key] = Path(value)
                elif value in (None, "") and key not in {"data_dir", "database_path", "cases_dir", "reports_dir"}:
                    updates[key] = None
            elif isinstance(default_value, bool):
                if isinstance(value, bool):
                    updates[key] = value
            elif isinstance(default_value, int):
                if type(value) is int and value > 0:
                    updates[key] = value
            elif isinstance(default_value, str):
                if isinstance(value, str):
                    updates[key] = value
            else:
                updates[key] = value
        return replace(config, **updates)

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        defaults = AppConfig.default()
        payload = {
            key: str(value) if isinstance(value, Path) else value
            for key, value in asdict(config).items()
            if key not in TOOL_LOCATIONS or value != getattr(defaults, key)
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
