from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.service import ForensicsService
from app.models import AnalysisResult, Finding, UserMark
from app.resources.labels import display_value, parameter_description, parameter_label, source_label


class FindingsTable(QTableWidget):
    mark_changed = Signal(str, str, bool)

    def __init__(self, settings_key: str = "findings") -> None:
        super().__init__(0, 7)
        self.setHorizontalHeaderLabels(
            [
                "Параметр",
                "Значение",
                "Источник",
                "Внимание",
                "Что означает",
                "Оценка эксперта",
                "В отчёт",
            ]
        )
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.setWordWrap(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(42)
        configure_resizable_columns(
            self,
            settings_key,
            [230, 280, 200, 90, 300, 150, 65],
        )

    def populate(self, findings: list[Finding]) -> None:
        self.setRowCount(len(findings))
        labels = {
            UserMark.NONE.value: "Не отмечено",
            UserMark.SIGNIFICANT.value: "Существенно",
            UserMark.INSIGNIFICANT.value: "Несущественно",
            UserMark.EXPLAINED.value: "Объяснено",
            UserMark.FURTHER_REVIEW.value: "Доп. исследование",
        }
        for row, finding in enumerate(findings):
            values = [
                ("⚠ РАЗЛИЧИЕ — " if finding.conflict else "")
                + parameter_label(finding.name),
                display_value(finding.value),
                source_label(finding.source),
                display_value(finding.level.value),
                parameter_description(
                    finding.name, finding.details or finding.description
                ),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if finding.conflict:
                    item.setBackground(QColor("#fff3cd"))
                self.setItem(row, column, item)
            combo = QComboBox()
            for value, label in labels.items():
                combo.addItem(label, value)
            current = combo.findData(finding.user_mark)
            combo.setCurrentIndex(max(0, current))
            include = QCheckBox()
            include.setChecked(finding.include_in_report)
            combo.currentIndexChanged.connect(
                lambda _index, c=combo, box=include, f=finding: self.mark_changed.emit(
                    f.id, str(c.currentData()), box.isChecked()
                )
            )
            include.stateChanged.connect(
                lambda _state, c=combo, box=include, f=finding: self.mark_changed.emit(
                    f.id, str(c.currentData()), box.isChecked()
                )
            )
            self.setCellWidget(row, 5, combo)
            self.setCellWidget(row, 6, include)


class PdfObjectsWidget(QWidget):
    offset_selected = Signal(int)
    export_requested = Signal(int, int)
    object_selected = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        splitter = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["PDF-объекты и ссылки"])
        self.tree.currentItemChanged.connect(self._selected)
        self.tabs = QTabWidget()
        self.dictionary = _plain()
        self.raw = _plain()
        self.decoded = _plain()
        self.references = _plain()
        self.tabs.addTab(self.dictionary, "Словарь")
        self.tabs.addTab(self.raw, "Исходные байты")
        self.tabs.addTab(self.decoded, "Декодированный stream")
        self.tabs.addTab(self.references, "Ссылки")
        splitter.addWidget(self.tree)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)
        self.export_button = QPushButton("Экспортировать выбранный объект")
        self.export_button.clicked.connect(self._export)
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)
        layout.addWidget(self.export_button)

    def set_objects(self, objects: object) -> None:
        self.tree.clear()
        if not isinstance(objects, list):
            return
        categories: dict[str, QTreeWidgetItem] = {}
        for item in objects:
            if not isinstance(item, dict) or int(item.get("object", -1)) < 0:
                continue
            category = str(item.get("category", "Objects"))
            parent = categories.setdefault(
                category, QTreeWidgetItem(self.tree, [parameter_label(category)])
            )
            location = (
                "внутри ObjStm · индекс qpdf"
                if item.get("storage") == "object_stream"
                else f"смещение {item.get('offset')} · ревизия {item.get('revision')}"
            )
            label = (
                f"{item.get('object')} {item.get('generation')} obj · {location}"
            )
            node = QTreeWidgetItem(parent, [label])
            node.setData(0, Qt.ItemDataRole.UserRole, item)
            for reference in item.get("references", [])[:50]:
                QTreeWidgetItem(
                    node,
                    [f"→ {reference.get('object')} {reference.get('generation')} R"],
                )
        self.tree.expandToDepth(0)

    def _selected(self, current: QTreeWidgetItem | None, _previous) -> None:
        item = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        if not isinstance(item, dict):
            return
        self.dictionary.setPlainText(str(item.get("dictionary", "")))
        self.raw.setPlainText(str(item.get("raw_preview", "")))
        self.decoded.setPlainText(
            str(
                item.get("decoded_preview")
                or item.get("decode_error")
                or "Декодированный stream отсутствует"
            )
        )
        self.references.setPlainText(json.dumps(item.get("references", []), indent=2))
        if item.get("storage") != "object_stream":
            self.offset_selected.emit(int(item.get("offset", 0)))
            self.object_selected.emit(int(item["object"]), int(item["generation"]))

    def set_object_content(self, payload: dict[str, object]) -> None:
        """Replace index previews with bounded content loaded on demand."""
        self.raw.setPlainText(str(payload.get("raw", "")))
        self.decoded.setPlainText(
            str(
                payload.get("decoded")
                or payload.get("decode_error")
                or "Декодированный stream отсутствует"
            )
        )

    def _export(self) -> None:
        current = self.tree.currentItem()
        item = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        if isinstance(item, dict):
            self.export_requested.emit(int(item["object"]), int(item["generation"]))


class HexViewer(QWidget):
    def __init__(self, service: ForensicsService) -> None:
        super().__init__()
        self.service = service
        self.path: Path | None = None
        navigation = QHBoxLayout()
        search_controls = QHBoxLayout()
        self.offset = QLineEdit("0x0")
        self.length = QSpinBox()
        self.length.setRange(16, 65536)
        self.length.setValue(4096)
        self.search = QLineEdit()
        self.encoding = QComboBox()
        self.encoding.addItems(["ASCII/UTF-8", "UTF-16LE", "HEX"])
        jump = QPushButton("Перейти")
        find = QPushButton("Найти")
        jump.clicked.connect(self.refresh)
        find.clicked.connect(self._find)
        for widget in (QLabel("Смещение"), self.offset, QLabel("Байты"), self.length, jump):
            navigation.addWidget(widget)
        navigation.addStretch(1)
        search_controls.addWidget(QLabel("Поиск"))
        search_controls.addWidget(self.search, 1)
        search_controls.addWidget(self.encoding)
        search_controls.addWidget(find)
        self.text = _plain()
        layout = QVBoxLayout(self)
        layout.addLayout(navigation)
        layout.addLayout(search_controls)
        layout.addWidget(self.text)

    def set_path(self, path: Path | None) -> None:
        self.path = path
        self.offset.setText("0x0")
        self.refresh()

    def jump_to(self, offset: int) -> None:
        self.offset.setText(hex(offset))
        self.refresh()

    def refresh(self) -> None:
        if not self.path:
            self.text.clear()
            return
        try:
            offset = int(self.offset.text().strip(), 0)
            data = self.service.read_hex(self.path, offset, self.length.value())
            self.text.setPlainText(format_hex(data, offset))
        except (OSError, ValueError) as exc:
            self.text.setPlainText(str(exc))

    def _find(self) -> None:
        if not self.path or not self.search.text():
            return
        try:
            if self.encoding.currentText() == "UTF-16LE":
                needle = self.search.text().encode("utf-16le")
            elif self.encoding.currentText() == "HEX":
                needle = bytes.fromhex(self.search.text())
            else:
                needle = self.search.text().encode("utf-8")
            start = int(self.offset.text().strip(), 0) + 1
            found = self.service.find_bytes(self.path, needle, start)
            if found >= 0:
                self.jump_to(found)
            else:
                self.text.setPlainText("Последовательность не найдена")
        except (OSError, ValueError) as exc:
            self.text.setPlainText(str(exc))


def configure_resizable_columns(
    table: QTableWidget,
    settings_key: str,
    default_widths: list[int],
) -> None:
    """Make every column user-resizable and persist its width between launches."""
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(42)
    header.setToolTip(
        "Потяните границу заголовка для изменения ширины. "
        "Двойной щелчок подбирает ширину по содержимому."
    )
    settings = QSettings("DocumentForensicsLab", "DocumentForensicInspector")
    stored = settings.value(f"tables/{settings_key}/widths", default_widths)
    widths = stored if isinstance(stored, list) else default_widths
    for column in range(table.columnCount()):
        try:
            width = int(widths[column])
        except (IndexError, TypeError, ValueError):
            width = default_widths[column] if column < len(default_widths) else 160
        table.setColumnWidth(column, max(42, width))

    def save_widths(_logical: int, _old_size: int, _new_size: int) -> None:
        settings.setValue(
            f"tables/{settings_key}/widths",
            [header.sectionSize(index) for index in range(table.columnCount())],
        )

    header.sectionResized.connect(save_widths)


def format_hex(data: bytes, base_offset: int = 0) -> str:
    lines = []
    for index in range(0, len(data), 16):
        chunk = data[index : index + 16]
        hex_part = " ".join(f"{item:02X}" for item in chunk).ljust(47)
        text_part = "".join(chr(item) if 32 <= item < 127 else "." for item in chunk)
        lines.append(f"{base_offset + index:016X}  {hex_part}  |{text_part}|")
    return "\n".join(lines)


def _plain() -> QPlainTextEdit:
    widget = QPlainTextEdit()
    widget.setReadOnly(True)
    return widget


def _display(value: object) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return str(value)
