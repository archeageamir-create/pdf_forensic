from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from app.adapters.base import AnalysisCancelled, CancellationToken
from app.core.service import ForensicsService
from app.models import AnalysisMode, AnalysisResult


class AnalysisSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(str, int, int)
    cancelled = Signal()
    finished = Signal()


class AnalysisWorker(QRunnable):
    def __init__(
        self,
        service: ForensicsService,
        paths: list[Path],
        project_id: str | None,
        mode: AnalysisMode,
        selected_analyzers: set[str] | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.paths = paths
        self.project_id = project_id
        self.mode = mode
        self.selected_analyzers = selected_analyzers
        self.token = CancellationToken()
        self.signals = AnalysisSignals()

    def cancel(self) -> None:
        self.token.cancel()

    @Slot()
    def run(self) -> None:
        try:
            for file_index, path in enumerate(self.paths, start=1):
                self.signals.progress.emit(
                    f"Файл {file_index}/{len(self.paths)}: {path.name}",
                    file_index - 1,
                    len(self.paths),
                )
                try:
                    result: AnalysisResult = self.service.analyze_file(
                        path,
                        self.project_id,
                        self.mode,
                        self.selected_analyzers,
                        self.token,
                        lambda stage, current, total: self.signals.progress.emit(
                            f"{path.name}: {stage}", current, total
                        ),
                    )
                    self.signals.result.emit(result)
                except AnalysisCancelled:
                    raise
                except Exception:
                    self.signals.error.emit(
                        f"Файл {path}:\n{traceback.format_exc()}"
                    )
        except AnalysisCancelled:
            self.signals.cancelled.emit()
        except Exception:
            self.signals.error.emit(traceback.format_exc())
        finally:
            self.signals.finished.emit()


class FunctionSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class FunctionWorker(QRunnable):
    def __init__(self, function) -> None:
        super().__init__()
        self.function = function
        self.signals = FunctionSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.result.emit(self.function())
        except Exception:
            self.signals.error.emit(traceback.format_exc())
        finally:
            self.signals.finished.emit()
