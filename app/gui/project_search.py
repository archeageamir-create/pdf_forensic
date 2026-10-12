from __future__ import annotations

import threading

from PySide6.QtCore import QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.core.project_search import search_project
from app.gui.widgets import configure_resizable_columns
from app.gui.workers import FunctionWorker
from app.resources.labels import category_label, parameter_label, source_label


class ProjectSearchDialog(QDialog):
    open_finding = Signal(str, str)

    def __init__(self, database, project_id, project_title, parent=None):
        super().__init__(parent)
        self.database, self.project_id = database, project_id
        self.hits = []
        self.worker = None
        self.cancelled = threading.Event()
        self.closing = False
        self.setWindowTitle("Поиск по метаданным проекта")
        available = self.screen().availableGeometry()
        self.resize(
            min(950, max(400, available.width() - 32)),
            min(630, max(400, available.height() - 32)),
        )
        layout = QVBoxLayout(self)
        heading = QLabel(f"Проект: {project_title}")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        note = QLabel(
            "Поиск среди сохранённых результатов всех файлов этого проекта. Откройте находку, чтобы увидеть полное значение, источник и экспертную отметку."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        controls = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText(
            "Автор, название программы, GPS, адрес или другое значение…"
        )
        self.query.setAccessibleName("Поиск по метаданным проекта")
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self._search)
        self.search_button = QPushButton("Найти")
        self.search_button.clicked.connect(self._search)
        controls.addWidget(self.query, 1)
        controls.addWidget(self.search_button)
        layout.addLayout(controls)
        self.status = QLabel("Введите слово или фрагмент значения и нажмите Enter.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Файл", "Что найдено", "Значение", "Источник"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        configure_resizable_columns(self.table, "project_search", [220, 190, 280, 180])
        self.table.currentCellChanged.connect(self._selected)
        self.table.cellDoubleClicked.connect(lambda *_: self._open())
        layout.addWidget(self.table, 1)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(125)
        layout.addWidget(self.detail)
        self.open_button = QPushButton("Открыть файл и находку")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open)
        layout.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignRight)
        self.query.setFocus()

    def _search(self):
        if self.worker is not None:
            return
        query = self.query.text().strip()
        if not query:
            self.status.setText("Введите слово или фрагмент значения.")
            return
        self.cancelled.clear()
        self.hits = []
        self.table.setRowCount(0)
        self._selected()
        self.search_button.setEnabled(False)
        self.status.setText("Ищем в сохранённых метаданных…")
        worker = FunctionWorker(
            lambda: search_project(
                self.database, self.project_id, query, cancelled=self.cancelled
            )
        )
        self.worker = worker
        worker.signals.result.connect(self._ready)
        worker.signals.error.connect(self._error)
        worker.signals.finished.connect(self._finished)
        QThreadPool.globalInstance().start(worker)

    def _ready(self, result):
        if self.closing:
            return
        self.hits = result.hits
        self.table.setRowCount(len(self.hits))
        for row, hit in enumerate(self.hits):
            values = (
                hit["original_name"],
                parameter_label(hit["name"]),
                hit["preview"].replace("\n", " "),
                source_label(hit["source"]),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(hit["original_path"] if column == 0 else value)
                self.table.setItem(row, column, item)
        text = f"Найдено: {len(self.hits)}."
        if result.limited:
            text += " Показаны первые 200 совпадений; уточните запрос."
        if result.interrupted:
            text += " Проверена только часть проекта: достигнут лимит времени или поиск отменён."
        self.status.setText(text)
        if self.hits:
            self.table.setCurrentCell(0, 0)
        self._selected()

    def _selected(self, *_):
        row = self.table.currentRow()
        valid = 0 <= row < len(self.hits)
        self.open_button.setEnabled(valid)
        if not valid:
            self.detail.clear()
            return
        hit = self.hits[row]
        self.detail.setPlainText(
            f"{hit['original_path']}\n{category_label(hit['category'])} • {source_label(hit['source'])} • {hit['location'] or 'расположение не указано'}\n{hit['preview']}"
            + (
                "\nПоказаны первые 800 символов; откройте находку для полного значения."
                if hit["preview_truncated"]
                else ""
            )
        )

    def _open(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.hits):
            hit = self.hits[row]
            self.open_finding.emit(hit["evidence_id"], hit["finding_id"])
            self.accept()

    def _error(self, details):
        if not self.closing:
            self.status.setText("Поиск не завершён. Подробности ниже; можно повторить.")
            self.detail.setPlainText(details)

    def _finished(self):
        self.worker = None
        if not self.closing:
            self.search_button.setEnabled(True)

    def done(self, result):
        self.closing = True
        self.cancelled.set()
        super().done(result)
