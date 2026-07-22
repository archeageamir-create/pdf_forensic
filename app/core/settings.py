from __future__ import annotations

import json
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Any

from app.core.config import AppConfig


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
        allowed = {item.name: item for item in fields(AppConfig)}
        updates: dict[str, Any] = {}
        for key, value in raw.items():
            if key not in allowed:
                continue
            if key.endswith("_path") or key.endswith("_dir") or key in {
                "pdfid_script",
                "pdf_parser_script",
                "report_template",
                "pdfbox_jar",
            }:
                updates[key] = Path(value) if value else None
            else:
                updates[key] = value
        return replace(config, **updates)

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            key: str(value) if isinstance(value, Path) else value
            for key, value in asdict(config).items()
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
