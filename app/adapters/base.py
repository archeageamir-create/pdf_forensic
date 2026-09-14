from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from app.models import Finding, ToolRun, ToolRunStatus

LOGGER = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class AdapterResult:
    findings: list[Finding] = field(default_factory=list)
    tool_runs: list[ToolRun] = field(default_factory=list)
    artifacts: dict[str, object] = field(default_factory=dict)


class ToolAdapter(ABC):
    @abstractmethod
    def analyze(self, path: Path) -> AdapterResult:
        raise NotImplementedError


class CancellationToken:
    def __init__(self, event=None) -> None:
        self._event = event if event is not None else threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class AnalysisCancelled(Exception):
    pass


class CommandRunner:
    def __init__(
        self, timeout_seconds: int = 120, cancellation_token: CancellationToken | None = None,
        max_output_bytes: int = 32 * 1024 * 1024,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.cancellation_token = cancellation_token
        self.max_output_bytes = max_output_bytes

    def run(
        self,
        tool_name: str,
        command: Sequence[str | Path],
        version_command: Sequence[str | Path] | None = None,
        *,
        input_bytes: bytes | None = None,
    ) -> ToolRun:
        normalized = [str(part) for part in command]
        started = _now()
        started_clock = datetime.now(UTC)
        missing = self._missing_component(normalized)
        if missing:
            finished = _now()
            return ToolRun(
                tool_name=tool_name,
                command=normalized,
                version="unavailable",
                stdout="",
                stderr=f"Required executable or script is unavailable: {missing}",
                exit_code=None,
                status=ToolRunStatus.UNAVAILABLE,
                started_at=started,
                finished_at=finished,
                duration_ms=0,
            )

        version = self._read_version(version_command) if version_command else "not requested"
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            with tempfile.TemporaryFile() as output_file, tempfile.TemporaryFile() as error_file, tempfile.TemporaryFile() as input_file:
                if input_bytes is not None:
                    input_file.write(input_bytes)
                    input_file.seek(0)
                return self._capture(tool_name, normalized, version, started, started_clock, environment, creation_flags, output_file, error_file, input_file if input_bytes is not None else None)
        except OSError as exc:
            LOGGER.exception("Could not launch %s", tool_name)
            return ToolRun(tool_name=tool_name, command=normalized, version=version, stdout="", stderr=str(exc), exit_code=None, status=ToolRunStatus.FAILED, started_at=started, finished_at=_now(), duration_ms=int((datetime.now(UTC) - started_clock).total_seconds() * 1000))

    def _capture(self, tool_name, normalized, version, started, started_clock, environment, creation_flags, output_file, error_file, input_file=None):
        process = subprocess.Popen(
                normalized,
                stdin=input_file if input_file is not None else subprocess.DEVNULL,
                stdout=output_file,
                stderr=error_file,
                shell=False,
                env=environment,
                creationflags=creation_flags,
            )
        deadline = time.monotonic() + self.timeout_seconds
        status = None
        reason = ""
        try:
            while process.poll() is None:
                if self.cancellation_token and self.cancellation_token.cancelled:
                    status, reason = ToolRunStatus.CANCELLED, "Cancelled by user"
                elif time.monotonic() >= deadline:
                    status, reason = ToolRunStatus.TIMED_OUT, "Tool execution timed out"
                elif any(os.fstat(stream.fileno()).st_size > self.max_output_bytes for stream in (output_file, error_file)):
                    status, reason = ToolRunStatus.FAILED, "Tool output exceeded configured limit; output truncated"
                if status is not None:
                    _terminate_process(process)
                    break
                try:
                    process.wait(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
                except subprocess.TimeoutExpired:
                    pass
            if status is None:
                status = ToolRunStatus.COMPLETED if process.returncode == 0 else ToolRunStatus.FAILED
            outputs = []
            for stream in (output_file, error_file):
                size = os.fstat(stream.fileno()).st_size
                stream.seek(0)
                outputs.append(stream.read(self.max_output_bytes).decode("utf-8", errors="replace"))
                if size > self.max_output_bytes:
                    status = ToolRunStatus.FAILED
                    reason = "Tool output exceeded configured limit; output truncated"
            return ToolRun(tool_name=tool_name, command=normalized, version=version, stdout=outputs[0], stderr=outputs[1] + ("\n" + reason if reason else ""), exit_code=process.returncode, status=status, started_at=started, finished_at=_now(), duration_ms=int((datetime.now(UTC) - started_clock).total_seconds() * 1000))
        finally:
            _terminate_process(process)

    def _read_version(self, command: Sequence[str | Path]) -> str:
        normalized = [str(part) for part in command]
        if self._missing_component(normalized):
            return "unavailable"
        try:
            result = subprocess.run(
                normalized,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=min(15, self.timeout_seconds),
                check=False,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            lines = (result.stdout or result.stderr).strip().splitlines()
            return lines[0][:500] if lines else "unknown"
        except (OSError, subprocess.TimeoutExpired):
            return "unknown"

    @staticmethod
    def _missing_component(command: Sequence[str]) -> str | None:
        if not command:
            return "empty command"
        executable = command[0]
        if not Path(executable).exists() and shutil.which(executable) is None:
            return executable
        if len(command) > 1 and command[1].lower().endswith(".py"):
            script = Path(command[1])
            if not script.is_file():
                return str(script)
        return None


def _decode_timeout_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
    else:
        process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
