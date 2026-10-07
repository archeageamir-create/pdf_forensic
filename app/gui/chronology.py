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
        self.anchor_row = None
        self.comparison = None
        layout = QVBoxLayout(self)
        hint = QLabel(
            "Выберите запись и нажмите «Запомнить первую дату», затем выберите другую и нажмите «Сравнить даты». "
            "Записи без известного пояса или точного времени вынесены в конец; их порядок не установлен."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        compare_row = QHBoxLayout()
        self.pin_date = QPushButton("Запомнить первую дату")
        self.pin_date.clicked.connect(self._pin_date)
        self.compare_dates = QPushButton("Сравнить даты")
        self.compare_dates.clicked.connect(self._compare_dates)
        self.reset_comparison = QPushButton("Сбросить")
        self.reset_comparison.clicked.connect(self._reset_comparison)
        compare_row.addWidget(self.pin_date)
        compare_row.addWidget(self.compare_dates)
        compare_row.addWidget(self.reset_comparison)
        compare_row.addStretch()
        layout.addLayout(compare_row)
        self.anchor_label = QLabel("Первая дата не выбрана. Также можно выделить две строки с Ctrl.")
        self.anchor_label.setWordWrap(True)
        layout.addWidget(self.anchor_label)
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
        self.anchor_row = None
        self.comparison = None
        self.anchor_label.setText("Первая дата не выбрана. Также можно выделить две строки с Ctrl.")
        self.anchor_label.setToolTip("")
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
        self.comparison = tuple(selected) if len(selected) == 2 else None
        rows = self.table.selectionModel().selectedRows()
        self.pin_date.setEnabled(len(selected) == 1)
        self.compare_dates.setEnabled(
            len(selected) == 1 and self.anchor_row is not None
            and rows[0].row() != self.anchor_row
        )
        self.reset_comparison.setEnabled(self.anchor_row is not None)
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

    def _pin_date(self):
        rows = self.table.selectionModel().selectedRows()
        if len(rows) != 1:
            return
        self.anchor_row = rows[0].row()
        event = self.events[self.anchor_row]
        description = f"Первая дата: {parameter_label(event['name'])} — {event['raw']} ({source_label(event['source'])})"
        self.anchor_label.setText(description)
        self.anchor_label.setToolTip(description)
        self._selection()

    def _compare_dates(self):
        selected = self._selected()
        rows = self.table.selectionModel().selectedRows()
        if self.anchor_row is None or len(selected) != 1 or rows[0].row() == self.anchor_row:
            return
        self.comparison = (self.events[self.anchor_row], selected[0])
        self.detail.setPlainText(compare_events(*self.comparison))
        self.add_note.setEnabled(True)

    def _reset_comparison(self):
        self.anchor_row = None
        self.anchor_label.setText("Первая дата не выбрана. Также можно выделить две строки с Ctrl.")
        self.anchor_label.setToolTip("")
        self._selection()

    def _open_source(self):
        selected = self._selected()
        if len(selected) == 1 and selected[0].get("finding_id"):
            self.finding_selected.emit(selected[0]["finding_id"])

    def _add_note(self):
        selected = self.comparison
        if selected:
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
