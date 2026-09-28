"""Research-oriented progressive disclosure for the existing desktop interface."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.analyzers.interpretation import (
    InterpretationBuilder,
    STATUS_LABELS,
    draft_text,
)
from app.analyzers.overview import needs_attention
from app.gui.widgets import configure_resizable_columns
from app.resources.labels import parameter_label, source_label


class ResearchAssistant(QWidget):
    finding_selected = Signal(str)
    draft_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.result = None
        self.answers = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("Помощник исследования")
        heading.setObjectName("SectionTitle")
        heading.setStyleSheet("font-size: 14pt; font-weight: 600;")
        layout.addWidget(heading)
        hint = QLabel(
            "Выберите вопрос: что найдено, что это позволяет утверждать и что проверить дальше."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.scope = QLabel()
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        self.observations_label = QLabel(
            "Наблюдения, которые стоит проверить — выберите для пояснения"
        )
        layout.addWidget(self.observations_label)
        self.observations = QListWidget()
        self.observations.setMaximumHeight(100)
        self.observations.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.observations.itemActivated.connect(
            lambda item: self.finding_selected.emit(item.data(Qt.ItemDataRole.UserRole))
        )
        self.observations.itemClicked.connect(
            lambda item: self.finding_selected.emit(item.data(Qt.ItemDataRole.UserRole))
        )
        layout.addWidget(self.observations)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Вопрос", "Что позволяют данные"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        configure_resizable_columns(self.table, "research_answers", [380, 260])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.setMinimumHeight(180)
        self.table.setAccessibleName("Вопросы для исследования")
        self.table.currentCellChanged.connect(self._select)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.table)
        detail_page = QWidget()
        detail_layout = QVBoxLayout(detail_page)
        detail_layout.setContentsMargins(4, 0, 0, 0)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMinimumHeight(180)
        self.detail.setAccessibleName("Основания и пределы интерпретации")
        detail_layout.addWidget(self.detail, 1)
        ground_row = QHBoxLayout()
        self.grounds = QComboBox()
        self.grounds.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.grounds.setMinimumContentsLength(16)
        self.grounds.setAccessibleName("Исходные записи выбранного вопроса")
        ground_row.addWidget(self.grounds, 1)
        self.open_ground = QPushButton("Открыть основание")
        self.open_ground.clicked.connect(self._open_ground)
        ground_row.addWidget(self.open_ground)
        detail_layout.addLayout(ground_row)
        self.add_draft = QPushButton("Добавить заготовку в заметки")
        self.add_draft.clicked.connect(self._add_draft)
        self.add_draft.setToolTip(
            "Добавить описание, основания и ограничения в редактируемые заметки исследования"
        )
        detail_layout.addWidget(self.add_draft, 0, Qt.AlignmentFlag.AlignLeft)
        self.splitter.addWidget(detail_page)
        self.splitter.setSizes([440, 590])
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setMinimumHeight(330)
        layout.addWidget(self.splitter, 1)
        legal = QLabel(
            "РК: НПВ по вопросу, выявленное в ходе исследования, обосновывается в заключении "
            "(ст. 39). Сообщение до исследования — отдельный документ (ст. 40). "
            "Статусы помощника описывают данные и не принимают эти решения за эксперта."
        )
        legal.setWordWrap(True)
        legal_toggle = QPushButton(
            "Памятка: НПВ в ходе исследования и сообщение до исследования"
        )
        legal_toggle.setCheckable(True)
        legal_toggle.toggled.connect(legal.setVisible)
        layout.addWidget(legal_toggle)
        legal.hide()
        layout.addWidget(legal)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "splitter"):
            narrow = self.width() < 820
            orientation = Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal
            if self.splitter.orientation() != orientation:
                self.splitter.setOrientation(orientation)
                self.splitter.setSizes([200, 300] if narrow else [440, 590])
            self.splitter.setMinimumHeight(500 if narrow else 330)

    def populate(self, result):
        self.result = result
        self.answers = InterpretationBuilder().build(result) if result else []
        self.observations.clear()
        interesting = (
            [
                f
                for f in result.findings
                if needs_attention(f) and f.category != "Tool diagnostics"
            ]
            if result
            else []
        )
        for finding in interesting:
            value = (
                str(finding.value)
                if not isinstance(finding.value, (list, dict))
                else f"записей: {len(finding.value)}"
            )
            text = f"{parameter_label(finding.name)}: {value[:120]} · {source_label(finding.source)}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, finding.id)
            item.setToolTip(text)
            self.observations.addItem(item)
        self.observations.setVisible(bool(interesting))
        self.observations_label.setVisible(bool(interesting))
        self.scope.setText(
            "Часть методов не завершена. Полученные наблюдения доступны; полнота исследования ограничена."
            if result
            and (
                result.incomplete
                or result.errors
                or any(r.status != "completed" for r in result.tool_runs)
            )
            else "Статус показывает, какое утверждение допускают полученные данные. Вывод по вопросу формулирует эксперт."
        )
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.answers))
        for row, answer in enumerate(self.answers):
            for col, value in enumerate(
                (answer.question, STATUS_LABELS[answer.status])
            ):
                item = QTableWidgetItem(value)
                item.setToolTip(value + "\n" + answer.answer)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        if self.answers:
            self.table.setCurrentCell(0, 0)
        self._select()

    def _select(self, *_):
        row = self.table.currentRow()
        self.grounds.clear()
        valid = 0 <= row < len(self.answers)
        self.add_draft.setEnabled(valid)
        self.open_ground.setEnabled(False)
        if not valid:
            self.detail.clear()
            return
        answer = self.answers[row]
        self.detail.setPlainText(
            "\n\n".join(
                (
                    answer.answer,
                    "Что получено\n" + answer.observation,
                    "Пределы интерпретации\n" + answer.limitation,
                    "Что проверить дальше\n" + answer.next_step,
                )
            )
        )
        findings = {f.id: f for f in self.result.findings}
        for finding_id in answer.finding_ids:
            finding = findings.get(finding_id)
            if finding:
                self.grounds.addItem(
                    f"{parameter_label(finding.name)} · {source_label(finding.source)} · {finding.location}",
                    finding.id,
                )
        self.open_ground.setEnabled(bool(self.grounds.count()))
        if not self.grounds.count():
            self.grounds.addItem("Прямые поля для этого вопроса не представлены")

    def _open_ground(self):
        if self.result and self.grounds.currentData():
            self.finding_selected.emit(self.grounds.currentData())

    def _add_draft(self):
        row = self.table.currentRow()
        if self.result and 0 <= row < len(self.answers):
            self.draft_requested.emit(draft_text(self.answers[row], self.result))
