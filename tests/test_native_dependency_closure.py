from unittest.mock import patch

import pytest

from scripts.verify_native_dependencies import closure


def test_crt_is_required_locally_even_if_installed_on_windows(tmp_path):
    (tmp_path / "tool.exe").touch()
    with patch("scripts.verify_native_dependencies.imports", return_value={"vcruntime140.dll"}), pytest.raises(ValueError, match="vcruntime140.dll"):
        closure(tmp_path, ["tool.exe"])


def test_transitive_and_delay_imports_resolve_case_insensitively(tmp_path):
    for name in ("tool.exe", "First.DLL", "second.dll"):
        (tmp_path / name).touch()
    graph = {"tool.exe": {"first.dll", "kernel32.dll"}, "first.dll": {"second.dll"}, "second.dll": {"FIRST.DLL".lower(), "api-ms-win-crt-runtime-l1-1-0.dll"}}
    with patch("scripts.verify_native_dependencies.imports", side_effect=lambda p: graph[p.name.lower()]):
        assert closure(tmp_path, ["tool.exe"]) == {"tool.exe", "first.dll", "second.dll"}


def test_missing_second_level_library_fails(tmp_path):
    (tmp_path / "tool.exe").touch()
    (tmp_path / "first.dll").touch()
    graph = {"tool.exe": {"first.dll"}, "first.dll": {"not-installed.dll"}}
    with patch("scripts.verify_native_dependencies.imports", side_effect=lambda p: graph[p.name]), pytest.raises(ValueError, match="not-installed.dll"):
        closure(tmp_path, ["tool.exe"])
