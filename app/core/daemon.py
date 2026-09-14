from __future__ import annotations

import logging
import json
import os
import threading
import time
from pathlib import Path

from app.adapters.base import AnalysisCancelled, CancellationToken
from app.core.job_queue import JobQueue, QueueExecutionLock
from app.core.service import ForensicsService
from app.models import AnalysisMode

LOGGER = logging.getLogger(__name__)


class FolderScanner:
    """Two unchanged observations and a settling interval before enqueueing a file."""

    def __init__(self, queue: JobQueue, excluded: list[Path], settle_seconds=3.0):
        self.queue = queue
        self.excluded = [path.resolve() for path in excluded]
        self.settle_seconds = settle_seconds
        self.observed = {}
        self.errors: list[str] = []

    def scan(self, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        queued = 0
        seen = set()
        self.errors = []
        for watch in self.queue.watches():
            if not watch["enabled"]:
                continue
            root = Path(watch["path"])
            if not root.is_dir():
                self.errors.append(f"Папка недоступна: {root}")
                continue

            def scan_error(exc):
                self.errors.append(str(exc))

            for parent, directories, filenames in os.walk(
                root, followlinks=False, onerror=scan_error
            ):
                directories[:] = (
                    [d for d in directories if self._allowed(Path(parent) / d, root)]
                    if watch["recursive"]
                    else []
                )
                for filename in filenames:
                    path = Path(parent) / filename
                    if (
                        filename.startswith((".", "~$"))
                        or path.suffix.lower()
                        in {".tmp", ".part", ".crdownload", ".partial"}
                        or not self._allowed(path, root)
                    ):
                        continue
                    key = (str(path), watch["project_id"], watch["mode"])
                    try:
                        stat = path.stat()
                        if not stat.st_size:
                            continue
                        version = (stat.st_size, stat.st_mtime_ns)
                        seen.add(key)
                        previous = self.observed.get(key)
                        if previous is None or previous[0] != version:
                            self.observed[key] = (version, now, False)
                        elif (
                            not previous[2] and now - previous[1] >= self.settle_seconds
                        ):
                            self.queue.enqueue(
                                path, watch["project_id"], AnalysisMode(watch["mode"])
                            )
                            self.observed[key] = (version, previous[1], True)
                            queued += 1
                    except (OSError, ValueError) as exc:
                        self.errors.append(f"{path.name}: {exc}")
        self.observed = {
            key: value for key, value in self.observed.items() if key in seen
        }
        return queued

    def _allowed(self, path: Path, root: Path) -> bool:
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            return False
        resolved = path.resolve()
        return resolved.is_relative_to(root) and not any(
            resolved.is_relative_to(excluded) for excluded in self.excluded
        )


class QueueDaemon:
    def __init__(
        self,
        service: ForensicsService,
        queue: JobQueue,
        *,
        on_result=None,
        on_change=None,
        on_progress=None,
        isolate=True,
    ):
        self.service = service
        self.queue = queue
        self.scanner = FolderScanner(
            queue,
            [
                service.config.data_dir,
                service.config.cases_dir,
                service.config.reports_dir,
            ],
        )
        self.on_result = on_result or (lambda result: None)
        self.on_change = on_change or (lambda: None)
        self.on_progress = on_progress or (lambda stage, current, total: None)
        self.stop_event = threading.Event()
        self.paused = threading.Event()
        self.current_token: CancellationToken | None = None
        self.current_job_id: str | None = None
        self.isolate = isolate
        self.has_execution_lock = False

    def stop(self):
        self.stop_event.set()
        if self.current_token:
            self.current_token.cancel()

    def cancel_current(self):
        if self.current_token:
            self.current_token.cancel()

    def run(self, *, once=False, poll_seconds=1.0):
        with QueueExecutionLock(self.queue.path.with_suffix(".lock")):
            self.has_execution_lock = True
            try:
                self.queue.recover_interrupted()
                self.on_change()
                while not self.stop_event.is_set():
                    if not self.paused.is_set():
                        self.scanner.scan()
                        while (
                            not self.stop_event.is_set()
                            and not self.paused.is_set()
                            and self.process_one()
                        ):
                            pass
                    if once:
                        return
                    self.stop_event.wait(poll_seconds)
            finally:
                self.has_execution_lock = False

    def process_one(self) -> bool:
        job = self.queue.claim()
        if job is None:
            return False
        self.current_job_id = job.id
        self.current_token = CancellationToken()
        self.on_change()
        try:
            if self.service.config.settings_path:
                from app.core.settings import SettingsStore

                config = SettingsStore(self.service.config.settings_path).load(
                    self.service.config
                )
                if config != self.service.config:
                    # Workspace identity belongs to this executor/queue. Tool paths
                    # and limits may change live; moving a workspace needs a restart.
                    from dataclasses import replace

                    config = replace(
                        config,
                        **{
                            key: getattr(self.service.config, key)
                            for key in (
                                "data_dir",
                                "database_path",
                                "cases_dir",
                                "reports_dir",
                                "settings_path",
                            )
                        },
                    )
                    self.service = ForensicsService(config)
            saved = (
                self.service.repository.load(job.evidence_id)
                if job.evidence_id
                else None
            )
            if saved:
                self.queue.finish(
                    job.id,
                    "partial" if saved.incomplete else "completed",
                    evidence_id=saved.evidence.id,
                )
                self.on_result(saved)
                return True
            if (
                job.project_id
                and self.service.repository.get_project(job.project_id) is None
            ):
                raise ValueError(
                    "Проект задания больше не существует. Добавьте файл заново в существующий проект."
                )
            stat = Path(job.path).stat()
            if (stat.st_size, stat.st_mtime_ns) != (job.size, job.mtime_ns):
                raise ValueError(
                    "Файл изменился после постановки в очередь. Добавьте актуальную версию повторно."
                )
            if self.isolate:
                from app.core.isolated import analyze_isolated

                result = analyze_isolated(
                    self.service,
                    Path(job.path),
                    job.project_id,
                    AnalysisMode(job.mode),
                    set(json.loads(job.selected_analyzers)),
                    self.current_token,
                    self.on_progress,
                    result_id=job.evidence_id,
                )
            else:
                result = self.service.analyze_file(
                    Path(job.path),
                    job.project_id,
                    AnalysisMode(job.mode),
                    selected_analyzers=set(json.loads(job.selected_analyzers)),
                    cancellation_token=self.current_token,
                    progress=self.on_progress,
                    result_id=job.evidence_id,
                )
            self.queue.finish(
                job.id,
                "partial" if result.incomplete else "completed",
                evidence_id=result.evidence.id,
            )
            self.on_result(result)
        except AnalysisCancelled:
            self.queue.finish(
                job.id, "pending" if self.stop_event.is_set() else "cancelled"
            )
        except Exception as exc:
            LOGGER.exception("Queue analysis failed for %s", job.path)
            self.queue.finish(job.id, "failed", error=str(exc))
        finally:
            self.current_token = None
            self.current_job_id = None
            self.on_change()
        return True
