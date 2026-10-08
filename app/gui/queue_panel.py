from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.daemon import QueueDaemon
from app.core.job_queue import JobQueue
from app.core.service import ForensicsService
from app.gui.widgets import configure_resizable_columns
from app.models import AnalysisMode


STATUS_LABELS = {
    "pending": "В очереди",
    "running": "Анализируется",
    "completed": "Готово",
    "partial": "Частично",
    "failed": "Ошибка",
    "cancelled": "Отменено",
}


class QueueSignals(QObject):
    result = Signal(object)
    changed = Signal()
    error = Signal(str)
    progress = Signal(str, int, int)
    finished = Signal()


class QueueWorker(QRunnable):
    def __init__(self, daemon: QueueDaemon):
        super().__init__()
        self.daemon = daemon
        self.signals = QueueSignals()
        daemon.on_result = self.signals.result.emit
        daemon.on_change = self.signals.changed.emit
        daemon.on_progress = self.signals.progress.emit

    def run(self):
        try:
            self.daemon.run()
        except Exception as exc:
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()


class QueuePanel(QWidget):
    open_result = Signal(str)

    def __init__(self, service: ForensicsService, project_id_callback):
        super().__init__()
        self.queue = JobQueue(service.config.data_dir / "queue.sqlite3")
        self.daemon = QueueDaemon(service, self.queue)
        self.project_id_callback = project_id_callback
        self.service = service
        self.jobs = []
        self.watches = []
        self.project_names = {}
        self.summary = QLabel("Очередь пуста")
        self.summary.setWordWrap(True)
        self.state = QLabel("Обработка начнётся при запуске приложения")
        self.state.setWordWrap(True)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        self.state.setTextFormat(Qt.TextFormat.PlainText)
        self.notice.hide()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Файл", "Проект", "Состояние", "Режим", "Добавлен"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        configure_resizable_columns(self.table, "queue_with_project", [230, 180, 130, 100, 200])
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(90)
        self.table.currentCellChanged.connect(self._selected)
        self.table.cellDoubleClicked.connect(lambda *_: self._open())
        self.pause = QPushButton("Приостановить очередь")
        self.pause.setCheckable(True)
        self.pause.toggled.connect(self._pause)
        self.cancel = QPushButton("Отменить задание")
        self.cancel.clicked.connect(self._cancel)
        self.retry = QPushButton("Повторить")
        self.retry.clicked.connect(self._retry)
        self.open = QPushButton("Открыть результат")
        self.open.clicked.connect(self._open)
        self.watch_list = QComboBox()
        self.watch_list.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.watch_list.setMinimumContentsLength(18)
        self.watch_list.setMinimumWidth(0)
        self.watch_list.setAccessibleName("Наблюдаемые папки")
        self.watch_list.currentIndexChanged.connect(self._watch_selected)
        self.watch_enabled = QCheckBox("Следить за папкой")
        self.watch_enabled.toggled.connect(self._toggle_watch)
        self.recursive = QCheckBox("Включая вложенные папки")
        self.watch_mode = QComboBox()
        self.watch_mode.addItem("Быстрый анализ", AnalysisMode.QUICK)
        self.watch_mode.addItem("Полный анализ", AnalysisMode.FULL)
        add_watch = QPushButton("Выбрать папку для наблюдения")
        add_watch.clicked.connect(self._add_watch)
        remove_watch = QPushButton("Убрать папку")
        remove_watch.clicked.connect(self._remove_watch)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.state)
        layout.addWidget(self.notice)
        self.pages = QTabWidget()
        jobs_page, watches_page = QWidget(), QWidget()
        jobs_layout, watches_layout = QVBoxLayout(jobs_page), QVBoxLayout(watches_page)
        controls = QGridLayout()
        for index, button in enumerate(
            (self.pause, self.cancel, self.retry, self.open)
        ):
            controls.addWidget(button, index // 2, index % 2)
        jobs_layout.addLayout(controls)
        jobs_layout.addWidget(self.table, 1)
        jobs_layout.addWidget(self.detail)
        self.pages.addTab(jobs_page, "Задания")
        self.pages.addTab(watches_page, "Наблюдаемые папки")
        layout.addWidget(self.pages, 1)
        note = QLabel(
            "При добавлении папки она привязывается к выбранному проекту. Файлы поступают в очередь после стабилизации размера и даты. Наблюдение действует, пока запущено приложение или отдельный демон."
        )
        note.setWordWrap(True)
        watches_layout.addWidget(note)
        watch_controls = QGridLayout()
        watch_controls.addWidget(add_watch, 0, 0, 1, 2)
        watch_controls.addWidget(self.watch_mode, 1, 0)
        watch_controls.addWidget(self.recursive, 1, 1)
        watches_layout.addLayout(watch_controls)
        watches = QHBoxLayout()
        watches.addWidget(self.watch_list, 1)
        watches.addWidget(self.watch_enabled)
        watches.addWidget(remove_watch)
        watches_layout.addLayout(watches)
        self.watch_details = QLabel()
        self.watch_details.setWordWrap(True)
        watches_layout.addWidget(self.watch_details)
        watches_layout.addStretch(1)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.pause.setEnabled(self.daemon.has_execution_lock)
        selected = self._current_job()
        selected_id = selected.id if selected else None
        jobs = self.queue.list_jobs()
        counts = self.queue.counts()
        self.summary.setText(
            "Общая очередь  •  " + ("  •  ".join(
                f"{label}: {counts[status]}"
                for status, label in STATUS_LABELS.items()
                if counts.get(status)
            )
            or "Пока нет заданий — добавьте файлы или папку")
        )
        project_names = {project.id: f"{project.case_number} — {project.title}" for project in self.service.repository.list_projects()}
        projects_changed = project_names != self.project_names
        self.project_names = project_names
        if jobs != self.jobs or projects_changed:
            self._update_jobs(jobs, selected_id)
        self._selected()
        self._refresh_watches()
        if self.daemon.scanner.errors:
            self.state.setText("; ".join(self.daemon.scanner.errors[:3]))
        elif self.daemon.has_execution_lock and self.daemon.current_job_id is None:
            self.state.setText("Очередь на паузе" if self.daemon.paused.is_set() else "Очередь работает — ожидаем новые задания")

    def _update_jobs(self, jobs, selected_id):
        vertical = self.table.verticalScrollBar().value()
        horizontal = self.table.horizontalScrollBar().value()
        self.jobs = jobs
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.jobs))
        selected_row = -1
        for row, job in enumerate(self.jobs):
            mode = {"quick": "Быстрый", "full": "Полный", "custom": "Выбранные"}.get(
                job.mode, job.mode
            )
            for column, value in enumerate(
                (
                    Path(job.path).name,
                    self._project_name(job),
                    STATUS_LABELS.get(job.status, job.status),
                    mode,
                    job.created_at[:19].replace("T", " ") + " UTC",
                )
            ):
                item = QTableWidgetItem(value)
                item.setToolTip(job.path if column == 0 else value)
                self.table.setItem(row, column, item)
            if job.id == selected_id:
                selected_row = row
        self.table.blockSignals(False)
        if self.jobs:
            self.table.setCurrentCell(max(0, selected_row), 0)
        self.table.verticalScrollBar().setValue(vertical)
        self.table.horizontalScrollBar().setValue(horizontal)

    def _refresh_watches(self):
        watches = self.queue.watches()
        if watches != self.watches:
            previous = self.watch_list.currentData()
            self.watches = watches
            self.watch_list.blockSignals(True)
            self.watch_list.clear()
            for watch in watches:
                self.watch_list.addItem(watch["path"], watch["path"])
            self.watch_list.setCurrentIndex(max(0, self.watch_list.findData(previous)))
            self.watch_list.blockSignals(False)
            self._watch_selected()

    def _current_job(self):
        row = self.table.currentRow()
        return self.jobs[row] if 0 <= row < len(self.jobs) else None

    def select_job(self, job_id):
        for row, job in enumerate(self.jobs):
            if job.id == job_id:
                self.table.setCurrentCell(row, 0)
                self.table.scrollToItem(self.table.item(row, 0))
                break

    def _selected(self, *_):
        job = self._current_job()
        self.cancel.setEnabled(
            bool(
                job
                and (
                    job.status == "pending"
                    or (job.status == "running" and self.daemon.has_execution_lock)
                )
            )
        )
        self.retry.setEnabled(
            bool(job and job.status in {"failed", "cancelled", "partial"})
        )
        self.open.setEnabled(
            bool(job and job.evidence_id and job.status in {"completed", "partial"})
        )
        self.detail.setPlainText(
            (job.path + "\nПроект: " + self._project_name(job) + "\n" + (job.error or STATUS_LABELS[job.status]))
            if job
            else "Выберите задание, чтобы увидеть подробности."
        )

    def _project_name(self, job):
        return self.project_names.get(job.project_id, "Проект удалён") if job.project_id else "Быстрое исследование"

    def _pause(self, paused):
        self.daemon.paused.set() if paused else self.daemon.paused.clear()
        self.pause.setText("Продолжить очередь" if paused else "Приостановить очередь")
        self.state.setText(
            "Пауза после текущего файла" if paused else "Очередь работает"
        )

    def _cancel(self):
        job = self._current_job()
        if job and job.id == self.daemon.current_job_id:
            self.daemon.cancel_current()
        elif job:
            self.queue.cancel_pending(job.id)
        self.refresh()

    def _retry(self):
        job = self._current_job()
        if job:
            self.queue.retry(job.id)
            self.refresh()

    def _open(self):
        job = self._current_job()
        if job and job.evidence_id and job.status in {"completed", "partial"}:
            self.open_result.emit(job.evidence_id)

    def _add_watch(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Папка с файлами для исследования"
        )
        if folder:
            root = Path(folder).resolve()
            if any(root.is_relative_to(path) for path in self.daemon.scanner.excluded):
                self.state.setText(
                    "Выберите папку вне рабочего хранилища приложения, чтобы не анализировать его собственные результаты."
                )
                return
            self.queue.save_watch(
                root,
                self.project_id_callback(),
                self.watch_mode.currentData(),
                self.recursive.isChecked(),
            )
            self.refresh()

    def _remove_watch(self):
        path = self.watch_list.currentData()
        if path:
            self.queue.remove_watch(path)
            self.refresh()

    def _watch_selected(self, *_):
        path = self.watch_list.currentData()
        watch = next((w for w in self.watches if w["path"] == path), None)
        self.watch_enabled.blockSignals(True)
        self.watch_enabled.setEnabled(watch is not None)
        self.watch_enabled.setChecked(bool(watch and watch["enabled"]))
        self.watch_enabled.blockSignals(False)
        if hasattr(self, "watch_details"):
            project = (
                self.service.repository.get_project(watch["project_id"])
                if watch and watch["project_id"]
                else None
            )
            self.watch_details.setText(
                (
                    f"Проект: {project.title if project else 'Быстрое исследование'} • "
                    + ("Полный анализ" if watch["mode"] == "full" else "Быстрый анализ")
                    + (
                        " • С вложенными папками"
                        if watch["recursive"]
                        else " • Только эта папка"
                    )
                )
                if watch
                else "Нет папок для наблюдения"
            )

    def _toggle_watch(self, enabled):
        path = self.watch_list.currentData()
        if path:
            self.queue.set_watch_enabled(path, enabled)
            self.refresh()
