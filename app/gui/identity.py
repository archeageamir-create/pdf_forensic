from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.widgets import configure_resizable_columns
from app.resources.labels import display_value, parameter_label, source_label


class IdentityPanel(QWidget):
    """A compact orientation panel: key recorded facts and a derived image preview."""

    finding_selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.facts = []
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ["Основное", "Записанное значение", "Источник"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.cellDoubleClicked.connect(self._open_fact)
        self.table.setToolTip("Двойной щелчок открывает исходное значение и пояснение")
        configure_resizable_columns(self.table, "identity", [185, 270, 160])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumWidth(0)
        self.preview.setMaximumWidth(310)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setMaximumWidth(310)
        self.image_panel = QWidget()
        image_layout = QVBoxLayout(self.image_panel)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.addWidget(self.preview)
        image_layout.addWidget(self.note)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.image_panel)
        self.setMinimumHeight(155)
        self.setMaximumHeight(250)

    def populate(self, result):
        wanted = {
            "author",
            "creator",
            "lastmodifiedby",
            "creatortool",
            "producer",
            "software",
            "application",
            "make",
            "model",
            "lensmodel",
            "datetimeoriginal",
            "created",
            "creationdate",
            "createdate",
            "modifydate",
            "modified",
            "creation_time",
            "encoder",
            "image width",
            "image height",
            "duration",
            "codec_name",
            "gpsposition",
        }
        facts = []
        seen = set()
        for f in result.findings:
            key = (f.name.casefold(), display_value(f.value))
            if key[0] in wanted and key not in seen:
                facts.append(f)
                seen.add(key)
        self.table.setRowCount(len(facts))
        self.facts = facts
        for row, fact in enumerate(facts):
            for col, value in enumerate(
                (
                    parameter_label(fact.name),
                    display_value(fact.value),
                    source_label(fact.source),
                )
            ):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, col, item)
        self.table.setVisible(bool(facts))
        path = result.artifacts.get("image_preview_path")
        pixmap = QPixmap(str(path)) if path else QPixmap()
        self.image_panel.setVisible(not pixmap.isNull())
        if not pixmap.isNull():
            self.preview.setPixmap(
                pixmap.scaled(
                    280,
                    160,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.note.setText("Предпросмотр рабочей копии")
            self.note.setToolTip(str(result.artifacts.get("image_preview_note", "")))
        self.setVisible(bool(facts) or not pixmap.isNull())
        self.setFixedHeight(
            max(
                min(225, 54 + 30 * len(facts)) if facts else 0,
                205 if not pixmap.isNull() else 0,
            )
        )

    def _open_fact(self, row, _column):
        if 0 <= row < len(self.facts):
            self.finding_selected.emit(self.facts[row].id)
