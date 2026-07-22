from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
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
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class AnalysisCancelled(Exception):
    pass


class CommandRunner:
    def __init__(
        self, timeout_seconds: int = 120, cancellation_token: CancellationToken | None = None
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.cancellation_token = cancellation_token

    def run(
        self,
        tool_name: str,
        command: Sequence[str | Path],
        version_command: Sequence[str | Path] | None = None,
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
            process = subprocess.Popen(
                normalized,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                env=environment,
                creationflags=creation_flags,
            )
            deadline = time.monotonic() + self.timeout_seconds
            while True:
                if self.cancellation_token and self.cancellation_token.cancelled:
                    _terminate_process(process)
                    stdout, stderr = process.communicate()
                    return ToolRun(
                        tool_name=tool_name,
                        command=normalized,
                        version=version,
                        stdout=stdout.decode("utf-8", errors="replace"),
                        stderr=stderr.decode("utf-8", errors="replace") or "Cancelled by user",
                        exit_code=process.returncode,
                        status=ToolRunStatus.CANCELLED,
                        started_at=started,
                        finished_at=_now(),
                        duration_ms=int((datetime.now(UTC) - started_clock).total_seconds() * 1000),
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _terminate_process(process)
                    stdout, stderr = process.communicate()
                    return ToolRun(
                        tool_name=tool_name,
                        command=normalized,
                        version=version,
                        stdout=stdout.decode("utf-8", errors="replace"),
                        stderr=stderr.decode("utf-8", errors="replace") or "Tool execution timed out",
                        exit_code=process.returncode,
                        status=ToolRunStatus.TIMED_OUT,
                        started_at=started,
                        finished_at=_now(),
                        duration_ms=int((datetime.now(UTC) - started_clock).total_seconds() * 1000),
                    )
                try:
                    stdout_bytes, stderr_bytes = process.communicate(timeout=min(0.25, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            status = (
                ToolRunStatus.COMPLETED
                if process.returncode == 0
                else ToolRunStatus.FAILED
            )
            return ToolRun(
                tool_name=tool_name,
                command=normalized,
                version=version,
                stdout=stdout,
                stderr=stderr,
                exit_code=process.returncode,
                status=status,
                started_at=started,
                finished_at=_now(),
                duration_ms=int((datetime.now(UTC) - started_clock).total_seconds() * 1000),
            )
        except OSError as exc:
            LOGGER.exception("Could not launch %s", tool_name)
            return ToolRun(
                tool_name=tool_name,
                command=normalized,
                version=version,
                stdout="",
                stderr=str(exc),
                exit_code=None,
                status=ToolRunStatus.FAILED,
                started_at=started,
                finished_at=_now(),
                duration_ms=int((datetime.now(UTC) - started_clock).total_seconds() * 1000),
            )

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
            return (result.stdout or result.stderr).strip().splitlines()[0][:500] or "unknown"
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
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
