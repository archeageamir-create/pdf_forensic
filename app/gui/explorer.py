"""Operate: inherit the existing Windows/Segoe UI evidence desk.

One searchable list connects a plain-language observation to its exact value,
source and location. Filtering never changes the report or the stored evidence.
The table is compact; full values and expert marks belong in the detail pane.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal, QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.analyzers.overview import needs_attention
from app.analyzers.research_guidance import explain_finding, observation_draft
from app.gui.widgets import configure_resizable_columns
from app.models import Finding, UserMark
from app.resources.labels import (
    category_label,
    display_value,
    parameter_label,
    source_label,
)


class FindingsExplorer(QWidget):
    mark_changed = Signal(str, str, bool)
    export_value = Signal(object)
    draft_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.findings: list[Finding] = []
        self.visible_findings: list[Finding] = []
        self.search_values = {}
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Найти автора, дату, GPS, программу или любое значение…"
        )
        self.search.setAccessibleName("Поиск по результатам")
        self.search.setClearButtonEnabled(True)
        self.category = QComboBox()
        self.category.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.category.setMinimumContentsLength(20)
        self.category.setAccessibleName("Группа результатов")
        self.attention = QCheckBox("Требует внимания")
        self.counter = QLabel()
        self.reset_filters = QPushButton("Сбросить фильтры")
        self.reset_filters.setToolTip("Показать все результаты, сохранив оценки и выбор для отчёта")
        self.reset_filters.clicked.connect(self.clear_filters)
        self.reset_filters.setEnabled(False)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Что найдено", "Значение", "Источник", "Оценка"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        configure_resizable_columns(
            self.table, "universal_findings", [240, 290, 160, 150]
        )
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setAccessibleName("Объяснение и исходные данные")
        self.raw_detail = QPlainTextEdit()
        self.raw_detail.setReadOnly(True)
        self.raw_detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.raw_detail.setAccessibleName("Исходное значение и технические сведения")
        self.raw_toggle = QPushButton("Исходные данные")
        self.raw_toggle.setToolTip("Показать полное значение, расположение и служебные сведения")
        self.raw_toggle.setCheckable(True)
        self.raw_toggle.toggled.connect(self._toggle_raw)
        self.raw_detail.hide()
        self.add_observation = QPushButton("Описание в заметки")
        self.add_observation.setToolTip("Добавить заготовку описания наблюдения с источником и ограничениями")
        self.add_observation.clicked.connect(self._add_observation)
        self.mark = QComboBox()
        for value, label in (
            (UserMark.NONE, "Без отметки"),
            (UserMark.SIGNIFICANT, "Существенно"),
            (UserMark.INSIGNIFICANT, "Несущественно"),
            (UserMark.EXPLAINED, "Объяснено"),
            (UserMark.FURTHER_REVIEW, "Доп. исследование"),
        ):
            self.mark.addItem(label, value.value)
        self.include = QCheckBox("Включить в отчёт")
        self.save_value = QPushButton("Сохранить значение")
        self.save_value.clicked.connect(self._export_value)
        self.mark.currentIndexChanged.connect(self._mark)
        self.include.toggled.connect(self._mark)
        self.table.currentCellChanged.connect(self._selection)
        self.search.textChanged.connect(self._filter)
        self.category.currentIndexChanged.connect(self._filter)
        self.attention.toggled.connect(self._filter)
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        filters.addWidget(self.search, 1)
        filters.addWidget(self.attention)
        layout.addLayout(filters)
        groups = QHBoxLayout()
        groups.addWidget(self.category, 1)
        groups.addWidget(self.counter)
        groups.addWidget(self.reset_filters)
        layout.addLayout(groups)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter = splitter
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.addWidget(self.raw_detail)
        splitter.setSizes([300, 270])
        settings = QSettings("DocumentForensicsLab", "Inspector")
        state = settings.value("explorer/splitter")
        if state is not None:
            splitter.restoreState(state)
        splitter.splitterMoved.connect(
            lambda *_: settings.setValue("explorer/splitter", splitter.saveState())
        )
        layout.addWidget(splitter, 1)
        marks = QHBoxLayout()
        marks.addWidget(QLabel("Оценка эксперта:"))
        marks.addWidget(self.mark)
        marks.addWidget(self.include)
        marks.addStretch()
        layout.addLayout(marks)
        actions = QHBoxLayout()
        actions.addWidget(self.raw_toggle)
        actions.addWidget(self.add_observation)
        actions.addWidget(self.save_value)
        actions.addStretch()
        layout.addLayout(actions)

    def _toggle_raw(self, visible: bool):
        self.raw_detail.setVisible(visible)
        if visible:
            # Hidden panes can be restored at zero height from QSettings.
            # Explicitly give the source record space whenever it is requested.
            height = max(300, self.splitter.height())
            self.splitter.setSizes([height * 3 // 10, height * 3 // 10, height * 4 // 10])

    def populate(self, findings: list[Finding]):
        self.findings = findings
        self.search_values = {
            f.id: " ".join(
                (
                    f.name,
                    parameter_label(f.name),
                    category_label(f.category),
                    f.source,
                    json.dumps(f.value, ensure_ascii=False, default=str),
                    f.details,
                    f.location,
                )
            ).casefold()
            for f in findings
        }
        self.search.clear()
        self.attention.setChecked(False)
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("Все группы", "")
        for category in sorted({f.category for f in findings}, key=category_label):
            self.category.addItem(category_label(category), category)
        self.category.blockSignals(False)
        self._filter()

    def _filter(self, *_):
        query = self.search.text().casefold().strip()
        category = self.category.currentData()
        self.reset_filters.setEnabled(bool(self.search.text() or category or self.attention.isChecked()))
        self.visible_findings = [
            f
            for f in self.findings
            if (not category or f.category == category)
            and (not self.attention.isChecked() or needs_attention(f))
            and (not query or query in self.search_values.get(f.id, ""))
        ]
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(len(self.visible_findings))
        for row, finding in enumerate(self.visible_findings):
            raw = (
                f"{len(finding.value)} записей — выберите строку"
                if isinstance(finding.value, (dict, list))
                else display_value(finding.value)
            )
            compact = raw.replace("\n", " ")[:240]
            for col, text in enumerate(
                (
                    parameter_label(finding.name),
                    compact,
                    source_label(finding.source),
                    "Расхождение" if finding.conflict else display_value(finding.level),
                )
            ):
                item = QTableWidgetItem(text)
                item.setToolTip(raw if col == 1 else text)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        self.counter.setText(
            f"Показано {len(self.visible_findings)} из {len(self.findings)}"
        )
        if self.visible_findings:
            self.table.setCurrentCell(0, 0)
        self._selection()

    def clear_filters(self):
        controls = (self.search, self.attention, self.category)
        previous = [control.blockSignals(True) for control in controls]
        try:
            self.search.clear()
            self.attention.setChecked(False)
            self.category.setCurrentIndex(0)
        finally:
            for control, blocked in zip(controls, previous):
                control.blockSignals(blocked)
        self._filter()

    def reveal(self, finding_id: str):
        self.clear_filters()
        for row, finding in enumerate(self.visible_findings):
            if finding.id == finding_id:
                self.table.setCurrentCell(row, 0)
                self.table.scrollToItem(self.table.item(row, 0))
                return

    def _selection(self, *_):
        row = self.table.currentRow()
        valid = 0 <= row < len(self.visible_findings)
        self.mark.setEnabled(valid)
        self.include.setEnabled(valid)
        self.save_value.setEnabled(valid)
        self.add_observation.setEnabled(valid)
        self.raw_toggle.setEnabled(valid)
        if not valid:
            self.raw_detail.clear()
            self.detail.setPlainText(
                "Нет результатов для выбранных условий. Нажмите «Сбросить фильтры», чтобы показать все записи."
            )
            return
        finding = self.visible_findings[row]
        raw = json.dumps(finding.value, ensure_ascii=False, indent=2, default=str)
        if len(raw) > 100_000:
            raw = (
                raw[:100_000]
                + "\n\nПоказаны первые 100 000 символов. Кнопка «Сохранить исходное значение» выгружает значение целиком."
            )
        guide = explain_finding(finding)
        preview = (
            f"{len(finding.value)} записей; содержимое доступно по кнопке исходного значения"
            if isinstance(finding.value, (list, dict)) else
            raw.replace("\n", " ")[:200] + ("…" if len(raw) > 200 else "")
        )
        self.detail.setPlainText(f"{parameter_label(finding.name)}: {preview}\n\n" + guide.text())
        self.raw_detail.setPlainText(
            f"Исходное значение:\n{raw}\n\nГруппа: {category_label(finding.category)}\n"
            f"Источник: {source_label(finding.source)}\nРасположение: {finding.location or 'не указано анализатором'}\n"
            f"Техническое имя: {finding.name}\nИдентификатор: {finding.id}\n"
            f"Пояснение анализатора: {finding.details or finding.description}\nПравило помощника: {guide.rule}"
        )
        self.mark.blockSignals(True)
        self.include.blockSignals(True)
        self.mark.setCurrentIndex(max(0, self.mark.findData(finding.user_mark)))
        self.include.setChecked(finding.include_in_report)
        self.mark.blockSignals(False)
        self.include.blockSignals(False)

    def _mark(self, *_):
        row = self.table.currentRow()
        if 0 <= row < len(self.visible_findings):
            finding = self.visible_findings[row]
            self.mark_changed.emit(
                finding.id, self.mark.currentData(), self.include.isChecked()
            )

    def _export_value(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.visible_findings):
            self.export_value.emit(self.visible_findings[row])

    def _add_observation(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.visible_findings):
            self.draft_requested.emit(observation_draft(self.visible_findings[row]))
