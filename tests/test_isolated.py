from __future__ import annotations

import os
import sys
from dataclasses import replace
from unittest.mock import patch

import pytest

from app.adapters.base import AnalysisCancelled, CancellationToken, CommandRunner
from app.core.errors import AnalysisError
from app.core.isolated import analyze_isolated
from app.models import AnalysisMode, ToolRunStatus
from tests.test_universal import service_at


def crash_child(*_):
    os._exit(17)


def sleeping_child(*_):
    import time

    time.sleep(60)


def test_real_process_returns_saved_result_and_progress(tmp_path):
    path = tmp_path / "test.bin"
    path.write_bytes(b"synthetic evidence")
    service = service_at(tmp_path / "workspace")
    progress = []
    result = analyze_isolated(
        service,
        path,
        None,
        AnalysisMode.CUSTOM,
        set(),
        CancellationToken(),
        lambda *args: progress.append(args),
    )
    assert result.evidence.original_name == "test.bin"
    assert service.repository.load(result.evidence.id) is not None
    assert progress[-1][1:] == (8, 8)


def test_crashed_process_is_reported_without_hanging(tmp_path):
    service = service_at(tmp_path / "workspace")
    with patch("app.core.isolated._analyze_child", crash_child):
        with pytest.raises(AnalysisError, match="без результата"):
            analyze_isolated(
                service,
                tmp_path / "test.bin",
                None,
                AnalysisMode.CUSTOM,
                set(),
                CancellationToken(),
                lambda *_: None,
            )


def test_total_timeout_stops_unresponsive_parser(tmp_path):
    service = service_at(tmp_path / "workspace")
    service.config = replace(service.config, max_analysis_seconds=0.5)
    with patch("app.core.isolated._analyze_child", sleeping_child):
        with pytest.raises(AnalysisError, match="Превышено"):
            analyze_isolated(
                service,
                tmp_path / "test.bin",
                None,
                AnalysisMode.CUSTOM,
                set(),
                CancellationToken(),
                lambda *_: None,
            )


def test_cancellation_stops_unresponsive_parser(tmp_path):
    service = service_at(tmp_path / "workspace")
    token = CancellationToken()
    token.cancel()
    with patch("app.core.isolated._analyze_child", sleeping_child):
        with pytest.raises(AnalysisCancelled):
            analyze_isolated(
                service,
                tmp_path / "test.bin",
                None,
                AnalysisMode.CUSTOM,
                set(),
                token,
                lambda *_: None,
            )


def test_tool_output_is_bounded_and_marked_incomplete():
    run = CommandRunner(timeout_seconds=5, max_output_bytes=1024).run(
        "synthetic loud tool", [sys.executable, "-c", "print('x' * 65536)"]
    )
    assert run.status == ToolRunStatus.FAILED
    assert len(run.stdout) <= 1024
    assert "truncated" in run.stderr


def test_tool_timeout_keeps_partial_output():
    run = CommandRunner(timeout_seconds=0.4).run(
        "synthetic sleeping tool",
        [
            sys.executable,
            "-c",
            "import time; print('before timeout', flush=True); time.sleep(20)",
        ],
    )
    assert run.status == ToolRunStatus.TIMED_OUT
    assert "before timeout" in run.stdout


def test_tool_cancel_is_distinct_from_failure():
    token = CancellationToken()
    token.cancel()
    run = CommandRunner(timeout_seconds=2, cancellation_token=token).run(
        "synthetic tool", [sys.executable, "-c", "import time; time.sleep(20)"]
    )
    assert run.status == ToolRunStatus.CANCELLED
