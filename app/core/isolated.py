"""A disposable process per queued evidence file keeps the desktop responsive.

This is fault isolation, not an OS security sandbox. External tools still run
with the current user's permissions and receive only the evidence working copy.
"""

from __future__ import annotations

import multiprocessing
import os
import subprocess
import time
from pathlib import Path

from app.adapters.base import AnalysisCancelled, CancellationToken
from app.core.errors import AnalysisError
from app.core.service import ForensicsService
from app.models import AnalysisMode


def _analyze_child(
    config, path, project_id, mode, selected, cancel_event, sender, result_id=None
):
    try:
        service = ForensicsService(config)
        result = service.analyze_file(
            Path(path),
            project_id,
            AnalysisMode(mode),
            selected_analyzers=selected,
            cancellation_token=CancellationToken(cancel_event),
            progress=lambda *args: sender.send(("progress", args)),
            result_id=result_id,
        )
        sender.send(("result", result.evidence.id))
    except AnalysisCancelled:
        sender.send(("cancelled", ""))
    except Exception as exc:
        sender.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        sender.close()


def _stop_process_tree(process):
    if not process.is_alive():
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
    else:
        process.terminate()
    process.join(timeout=3)
    if process.is_alive():
        process.kill()
        process.join(timeout=3)


def analyze_isolated(
    service: ForensicsService,
    path: Path,
    project_id: str | None,
    mode: AnalysisMode,
    selected: set[str],
    token: CancellationToken,
    progress,
    result_id=None,
):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    cancelled = context.Event()
    process = context.Process(
        target=_analyze_child,
        args=(
            service.config,
            str(path),
            project_id,
            str(mode),
            selected,
            cancelled,
            sender,
            result_id,
        ),
        name="DFI evidence analyzer",
    )
    started = time.monotonic()
    cancellation_started = None
    try:
        process.start()
        sender.close()
        while True:
            if token.cancelled:
                cancelled.set()
                cancellation_started = cancellation_started or time.monotonic()
                if time.monotonic() - cancellation_started > 3:
                    raise AnalysisCancelled("Анализ отменён; процесс остановлен")
            if time.monotonic() - started > service.config.max_analysis_seconds:
                raise AnalysisError(
                    "Превышено общее время анализа файла; процесс остановлен. Можно увеличить лимит в настройках и повторить задание."
                )
            if receiver.poll(0.1):
                try:
                    event, payload = receiver.recv()
                except EOFError:
                    break
                if event == "progress":
                    progress(*payload)
                elif event == "result":
                    result = service.repository.load(payload)
                    if result is None:
                        raise AnalysisError(
                            "Результат дочернего процесса не найден в базе"
                        )
                    return result
                elif event == "cancelled":
                    raise AnalysisCancelled("Анализ отменён")
                elif event == "error":
                    raise AnalysisError(payload)
            elif not process.is_alive():
                break
        if token.cancelled:
            raise AnalysisCancelled("Анализ отменён")
        process.join(timeout=0.5)
        raise AnalysisError(
            f"Процесс анализа завершился без результата, код {process.exitcode}"
        )
    finally:
        if process.pid is not None:
            process.join(timeout=0.5)
            _stop_process_tree(process)
            process.close()
        receiver.close()
        sender.close()
