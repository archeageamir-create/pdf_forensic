from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.config import AppConfig
from app.models import ResearchProject


class ProjectDialog(QDialog):
    def __init__(self, parent=None, project: ResearchProject | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Карточка проекта")
        form = QFormLayout()
        self.title_edit = QLineEdit(project.title if project else "")
        self.case_edit = QLineEdit(project.case_number if project else "")
        self.object_edit = QLineEdit(project.object_description if project else "")
        self.initiator_edit = QLineEdit(project.initiator if project else "")
        self.legal_edit = QLineEdit(project.legal_basis if project else "")
        self.source_edit = QLineEdit(project.source_description if project else "")
        self.examiner_edit = QLineEdit(project.examiner_name if project else "")
        self.notes_edit = QPlainTextEdit(project.notes if project else "")
        self.notes_edit.setMaximumHeight(90)
        self.conclusions_edit = QPlainTextEdit(project.user_conclusions if project else "")
        self.conclusions_edit.setMaximumHeight(90)
        for label, widget in (
            ("Наименование*", self.title_edit),
            ("Номер исследования*", self.case_edit),
            ("Описание объекта*", self.object_edit),
            ("Инициатор", self.initiator_edit),
            ("Основание исследования", self.legal_edit),
            ("Источник получения", self.source_edit),
            ("Эксперт", self.examiner_edit),
            ("Заметки проекта", self.notes_edit),
            ("Выводы по проекту", self.conclusions_edit),
        ):
            form.addRow(label, widget)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _validate(self) -> None:
        if not all(
            (self.title_edit.text().strip(), self.case_edit.text().strip(), self.object_edit.text().strip())
        ):
            QMessageBox.warning(self, "Карточка проекта", "Заполните три обязательных поля.")
            return
        self.accept()

    def value(self) -> ResearchProject:
        values = {
            "title": self.title_edit.text().strip(),
            "case_number": self.case_edit.text().strip(),
            "object_description": self.object_edit.text().strip(),
            "initiator": self.initiator_edit.text().strip(),
            "legal_basis": self.legal_edit.text().strip(),
            "source_description": self.source_edit.text().strip(),
            "examiner_name": self.examiner_edit.text().strip(),
            "notes": self.notes_edit.toPlainText().strip(),
            "user_conclusions": self.conclusions_edit.toPlainText().strip(),
        }
        if self.project:
            for key, value in values.items():
                setattr(self.project, key, value)
            return self.project
        return ResearchProject(**values)


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Настройки анализа")
        form = QFormLayout()
        self.exiftool = _path_row(str(config.exiftool_command), self, executable=True)
        self.ffprobe = _path_row(str(config.ffprobe_command), self, executable=True)
        self.qpdf = _path_row(str(config.qpdf_command), self, executable=True)
        self.pdfcpu = _path_row(str(config.pdfcpu_command), self, executable=True)
        self.poppler = _directory_row(str(config.poppler_bin_dir or ""), self)
        self.java = _path_row(str(config.java_command), self, executable=True)
        self.jhove = _directory_row(str(config.jhove_dir or ""), self)
        self.verapdf = _directory_row(str(config.verapdf_dir or ""), self)
        self.pdfbox = _path_row(str(config.pdfbox_jar or ""), self, executable=False, jar=True)
        self.template = _path_row(str(config.report_template or ""), self, executable=False)
        self.update_url = QLineEdit(config.update_manifest_url)
        self.update_url.setPlaceholderText("https://example.org/update-manifest.json")
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 3600)
        self.timeout.setValue(config.tool_timeout_seconds)
        self.analysis_timeout = QSpinBox()
        self.analysis_timeout.setRange(1, 240)
        self.analysis_timeout.setValue(max(1, config.max_analysis_seconds // 60))
        self.stream_limit = QSpinBox()
        self.stream_limit.setRange(1, 2048)
        self.stream_limit.setValue(config.max_stream_bytes // (1024 * 1024))
        self.qdf = QCheckBox("Создавать QDF-копию при полном анализе")
        self.qdf.setChecked(config.create_qdf_in_full_mode)
        self.signatures = QCheckBox("Проверять подписи криптографически")
        self.signatures.setChecked(config.validate_signatures)
        form.addRow("ExifTool", self.exiftool)
        form.addRow("ffprobe — аудио и видео", self.ffprobe)
        form.addRow("qpdf", self.qpdf)
        form.addRow("pdfcpu", self.pdfcpu)
        form.addRow("Poppler — папка bin", self.poppler)
        form.addRow("Встроенная Java", self.java)
        form.addRow("JHOVE — папка", self.jhove)
        form.addRow("veraPDF — папка", self.verapdf)
        form.addRow("PDFBox — JAR", self.pdfbox)
        form.addRow("DOCX-шаблон", self.template)
        form.addRow("Манифест обновлений", self.update_url)
        form.addRow("Timeout, секунд", self.timeout)
        form.addRow("Лимит на файл, минут", self.analysis_timeout)
        form.addRow("Максимальный stream, МБ", self.stream_limit)
        form.addRow(self.qdf)
        form.addRow(self.signatures)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def value(self) -> AppConfig:
        return replace(
            self.config,
            exiftool_command=self.exiftool.findChild(QLineEdit).text().strip() or "exiftool",
            ffprobe_command=self.ffprobe.findChild(QLineEdit).text().strip() or "ffprobe",
            qpdf_command=self.qpdf.findChild(QLineEdit).text().strip() or "qpdf",
            pdfcpu_command=self.pdfcpu.findChild(QLineEdit).text().strip() or "pdfcpu",
            poppler_bin_dir=(
                Path(self.poppler.findChild(QLineEdit).text().strip())
                if self.poppler.findChild(QLineEdit).text().strip()
                else None
            ),
            java_command=self.java.findChild(QLineEdit).text().strip() or "java",
            jhove_dir=(
                Path(self.jhove.findChild(QLineEdit).text().strip())
                if self.jhove.findChild(QLineEdit).text().strip()
                else None
            ),
            verapdf_dir=(
                Path(self.verapdf.findChild(QLineEdit).text().strip())
                if self.verapdf.findChild(QLineEdit).text().strip()
                else None
            ),
            pdfbox_jar=(
                Path(self.pdfbox.findChild(QLineEdit).text().strip())
                if self.pdfbox.findChild(QLineEdit).text().strip()
                else None
            ),
            report_template=(
                Path(self.template.findChild(QLineEdit).text().strip())
                if self.template.findChild(QLineEdit).text().strip()
                else None
            ),
            tool_timeout_seconds=self.timeout.value(),
            max_analysis_seconds=self.analysis_timeout.value() * 60,
            max_stream_bytes=self.stream_limit.value() * 1024 * 1024,
            create_qdf_in_full_mode=self.qdf.isChecked(),
            validate_signatures=self.signatures.isChecked(),
            update_manifest_url=self.update_url.text().strip(),
        )


class CustomAnalyzersDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Пользовательский набор анализаторов")
        self.boxes: dict[str, QCheckBox] = {}
        layout = QVBoxLayout(self)
        for key, label in (
            ("exiftool", "ExifTool"),
            ("qpdf", "qpdf"),
            ("pdfcpu", "pdfcpu — независимая проверка"),
            ("poppler", "Poppler — текст, шрифты, изображения и рендер"),
            ("jhove", "JHOVE PDF-hul — сохранность структуры"),
            ("verapdf", "veraPDF — PDF/A и PDF/UA"),
            ("pdfbox", "Apache PDFBox — независимый парсер"),
            ("pdfid", "PDFiD"),
            ("ffprobe", "ffprobe — контейнер и медиадорожки"),
            ("pdf_parser", "pdf-parser"),
            ("deep_pdf", "Ревизии, объекты и streams"),
            ("signatures", "ByteRange и подписи"),
            ("attachments", "Вложения"),
        ):
            box = QCheckBox(label)
            box.setChecked(True)
            self.boxes[key] = box
            layout.addWidget(box)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Применить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self) -> set[str]:
        return {key for key, box in self.boxes.items() if box.isChecked()}


def _path_row(
    value: str, parent: QWidget, executable: bool, jar: bool = False
) -> QWidget:
    widget = QWidget(parent)
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    edit = QLineEdit(value)
    button = QPushButton("…")
    button.setMaximumWidth(36)

    def choose() -> None:
        selected, _ = QFileDialog.getOpenFileName(
            parent,
            "Выберите файл",
            edit.text(),
            (
                "Исполняемые файлы (*.exe);;Все файлы (*)"
                if executable
                else "Java (*.jar);;Все файлы (*)"
                if jar
                else "Word (*.docx *.dotx);;Все файлы (*)"
            ),
        )
        if selected:
            edit.setText(selected)

    button.clicked.connect(choose)
    layout.addWidget(edit)
    layout.addWidget(button)
    return widget


def _directory_row(value: str, parent: QWidget) -> QWidget:
    widget = QWidget(parent)
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    edit = QLineEdit(value)
    button = QPushButton("…")
    button.setMaximumWidth(36)

    def choose() -> None:
        selected = QFileDialog.getExistingDirectory(parent, "Выберите папку", edit.text())
        if selected:
            edit.setText(selected)

    button.clicked.connect(choose)
    layout.addWidget(edit)
    layout.addWidget(button)
    return widget
