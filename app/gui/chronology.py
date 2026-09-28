from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.analyzers.chronology_guidance import (
    SCOPE_LABELS,
    compare_events,
    event_guidance,
)
from app.analyzers.timeline import TimelineBuilder
from app.gui.widgets import configure_resizable_columns
from app.resources.labels import parameter_label, source_label


class ChronologyPanel(QWidget):
    finding_selected = Signal(str)
    draft_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.events = []
        layout = QVBoxLayout(self)
        hint = QLabel(
            "Выберите одну запись для пояснения или две с Ctrl для сопоставления. "
            "Записи без известного пояса или точного времени вынесены в конец; их порядок не установлен."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [
                "Записанная дата",
                "Событие",
                "К чему относится",
                "Часовой пояс",
                "Источник",
            ]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        configure_resizable_columns(
            self.table, "research_chronology", [230, 240, 240, 110, 180]
        )
        self.table.itemSelectionChanged.connect(self._selection)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setSizes([350, 220])
        layout.addWidget(splitter, 1)
        buttons = QHBoxLayout()
        self.open_source = QPushButton("Открыть исходную запись")
        self.open_source.clicked.connect(self._open_source)
        buttons.addWidget(self.open_source)
        self.add_note = QPushButton("Добавить сопоставление в заметки")
        self.add_note.clicked.connect(self._add_note)
        buttons.addWidget(self.add_note)
        buttons.addStretch()
        layout.addLayout(buttons)

    def populate(self, result):
        # Rebuild from source findings so old results gain provenance and precision
        # without silently trusting historical synthetic timestamps.
        self.events = (
            TimelineBuilder().build(result.evidence, result.findings) if result else []
        )
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(len(self.events))
        for row, event in enumerate(self.events):
            values = (
                event["raw"],
                parameter_label(event["name"]),
                SCOPE_LABELS.get(event["scope"], event["scope"]),
                "указан" if event.get("timezone_present") else "неизвестен",
                source_label(event["source"]),
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        self.table.clearSelection()
        if self.events:
            self.table.selectRow(0)
        self._selection()

    def _selected(self):
        return [
            self.events[index.row()]
            for index in self.table.selectionModel().selectedRows()
            if index.row() < len(self.events)
        ]

    def _selection(self):
        selected = self._selected()
        self.open_source.setEnabled(
            len(selected) == 1 and bool(selected[0].get("finding_id"))
        )
        self.add_note.setEnabled(len(selected) == 2)
        if len(selected) == 2:
            self.detail.setPlainText(compare_events(*selected))
        elif len(selected) == 1:
            e = selected[0]
            self.detail.setPlainText(
                f"{parameter_label(e['name'])}: {e['raw']}\n"
                f"Источник: {e['source']}; {e.get('location', '')}\n\n"
                + event_guidance(e)
            )
        else:
            self.detail.setPlainText(
                "Выберите одну или две записи. Точные интервалы вычисляются только при известных поясах и полной записи времени."
            )

    def _open_source(self):
        selected = self._selected()
        if len(selected) == 1 and selected[0].get("finding_id"):
            self.finding_selected.emit(selected[0]["finding_id"])

    def _add_note(self):
        selected = self._selected()
        if len(selected) == 2:
            refs = "\n".join(
                f"{e['source']}; {e.get('location', '')}; запись: {e.get('finding_id') or e['scope']}"
                for e in selected
            )
            self.draft_requested.emit(
                "ЗАГОТОВКА СОПОСТАВЛЕНИЯ ВРЕМЕННЫХ ЗАПИСЕЙ\n\n"
                + compare_events(*selected)
                + "\n\nОснования:\n"
                + refs
            )
