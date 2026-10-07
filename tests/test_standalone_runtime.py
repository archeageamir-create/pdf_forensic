import json
import sys
from dataclasses import asdict
from pathlib import Path
import zipfile

import pytest

from app.core import config as config_module
from app.core.config import AppConfig
from app.core.settings import SettingsStore, TOOL_LOCATIONS
from scripts import prepare_runtime_dependencies as runtime


def test_frozen_tools_stay_inside_package_even_when_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    config = AppConfig.default()
    for name in TOOL_LOCATIONS - {"pdfid_script", "pdf_parser_script"}:
        assert Path(getattr(config, name)).is_relative_to(tmp_path)
    assert Path(config.ffprobe_command) == tmp_path / "app/resources/binaries/ffmpeg/ffprobe.exe"


def test_source_checkout_prefers_local_bundle_and_falls_back_for_developers(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(config_module, "bundled_resource", lambda *parts: tmp_path.joinpath(*parts))
    assert AppConfig.default().ffprobe_command == "ffprobe"
    probe = tmp_path / "app/resources/binaries/ffmpeg/ffprobe.exe"
    probe.parent.mkdir(parents=True)
    probe.write_bytes(b"test")
    assert Path(AppConfig.default().ffprobe_command) == probe


def test_settings_relocate_old_bundle_and_keep_explicit_custom_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "new-install"), raising=False)
    store = SettingsStore(tmp_path / "settings.json")
    old = {
        "exiftool_command": "C:/old/_internal/app/resources/binaries/ExifTool.exe",
        "qpdf_command": "qpdf",
        "ffprobe_command": "C:/My Tools/ffprobe.exe",
        "java_command": "java",
        "poppler_bin_dir": None,
        "pdfbox_jar": "C:/old/_internal/app/resources/binaries/pdfbox/pdfbox-app-3.0.8.jar",
    }
    store.path.write_text(json.dumps(old), encoding="utf-8")
    defaults = AppConfig.default()
    loaded = store.load(defaults)
    for name in set(old) - {"ffprobe_command"}:
        assert getattr(loaded, name) == getattr(defaults, name)
    assert loaded.ffprobe_command == old["ffprobe_command"]
    store.save(loaded)
    saved = json.loads(store.path.read_text(encoding="utf-8"))
    assert (set(saved) & TOOL_LOCATIONS) == {"ffprobe_command"}


@pytest.fixture
def payload(tmp_path, monkeypatch):
    lock = tmp_path / "lock.json"
    lock.write_text("{}")
    folder = tmp_path / "payload"
    folder.mkdir()
    monkeypatch.setattr(runtime, "LOCK", lock)
    monkeypatch.setattr(runtime, "REQUIRED", ("tool.exe",))
    for name in ("tool.exe", "dependency.dll"):
        (folder / name).write_bytes(b"test content")
    manifest = {"lock_sha256": runtime.digest(lock), "files": [
        {"path": p.name, "size": p.stat().st_size, "sha256": runtime.digest(p)}
        for p in folder.iterdir()
    ]}
    (folder / "RUNTIME_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def test_runtime_validation_requires_transitive_files_and_exact_bytes(payload):
    runtime.verify_bundle(payload)
    (payload / "dependency.dll").unlink()
    with pytest.raises(ValueError, match="file set differs"):
        runtime.verify_bundle(payload)
    (payload / "dependency.dll").write_bytes(b"wrong content")
    with pytest.raises(ValueError, match="file modified"):
        runtime.verify_bundle(payload)


def test_runtime_validation_rejects_lock_drift_and_omitted_required_tool(payload, monkeypatch):
    monkeypatch.setattr(runtime, "REQUIRED", ("another-engine.exe",))
    with pytest.raises(ValueError, match="Required runtime files missing"):
        runtime.verify_bundle(payload)
    runtime.LOCK.write_text('{"changed": true}')
    with pytest.raises(ValueError, match="Runtime lock changed"):
        runtime.verify_bundle(payload)


def test_dependency_archive_cannot_escape_staging_directory(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("../outside.txt", "outside")
    with pytest.raises(ValueError, match="Unsafe archive member"):
        runtime.extract_zip(archive, tmp_path / "stage")
    assert not (tmp_path / "outside.txt").exists()


@pytest.mark.parametrize("healthy", [True, False])
def test_headless_tool_check_reports_real_failure(tmp_path, monkeypatch, healthy):
    from app import main as entry
    from app.models import ToolRun, ToolRunStatus
    run = ToolRun("test", ["test.exe"], "1", "", "", 0 if healthy else None,
                  ToolRunStatus.COMPLETED if healthy else ToolRunStatus.UNAVAILABLE, "", "")
    monkeypatch.setattr(entry.ForensicsService, "check_installation", lambda self: [run])
    destination = tmp_path / "tools.json"
    monkeypatch.setattr(sys, "argv", ["app", "--data-dir", str(tmp_path / "workspace"), "--check-tools", "--output", str(destination)])
    assert entry.main() == (0 if healthy else 2)
    assert json.loads(destination.read_text(encoding="utf-8")) == {"all_tools_available": healthy, "tools": [asdict(run)]}
