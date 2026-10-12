from dataclasses import replace
import json

import pytest

from app.core.config import AppConfig
from app.core.settings import SettingsStore


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        "text",
        {
            "data_dir": [],
            "tool_timeout_seconds": "fast",
            "validate_signatures": "false",
        },
        {"data_dir": "", "max_analysis_seconds": -1, "max_file_size_bytes": True},
    ],
)
def test_damaged_or_wrong_typed_settings_keep_usable_defaults(tmp_path, payload):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    defaults = AppConfig.default()
    assert SettingsStore(path).load(defaults) == defaults


def test_settings_roundtrip_preserves_tools_and_limits(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    config = replace(
        AppConfig.default(),
        ffprobe_command="C:/My Tools/ffprobe.exe",
        max_analysis_seconds=300,
        validate_signatures=False,
    )
    store.save(config)
    assert store.load(config) == config


def test_optional_tool_folder_can_be_cleared(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    defaults = replace(AppConfig.default(), poppler_bin_dir=tmp_path / "old-poppler")
    updated = replace(defaults, poppler_bin_dir=None)
    store.save(updated)
    assert store.load(defaults).poppler_bin_dir is None
