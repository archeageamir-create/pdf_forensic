"""Product identity, local storage and bundled legal information."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QTextBrowser, QVBoxLayout, QWidget,
)

from app import __version__
from app.core.config import AppConfig, bundled_resource


class AboutDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("О программе")
        self.setMinimumSize(360, 320)
        layout = QVBoxLayout(self)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(20, 18, 20, 18)
        body.setSpacing(16)
        logo = QLabel()
        logo.setAccessibleName("Логотип АНСЭ")
        picture = QPixmap(str(bundled_resource("app", "resources", "branding", "anse-logo.png")))
        logo.setPixmap(picture.scaledToWidth(280, Qt.TransformationMode.SmoothTransformation))
        body.addWidget(logo)
        title = QLabel(f"Document Forensic Inspector {__version__}")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        body.addWidget(title)
        for text in (
            "Программа разработана ТОО «АНСЭ».\n"
            "© 2026. Все права защищены в пределах применимых лицензий.",
            "Файлы исследуются на вашем компьютере. Для анализа не нужен интернет. "
            "Исходники и отчёты автоматически никуда не отправляются.",
            "Сборка распространяется бесплатно. Код оболочки — Apache-2.0. "
            "Сторонние инструменты и библиотеки имеют свои лицензии; их условия сохраняются.",
            "Программа показывает найденные сведения и помогает их проверить. "
            "Оценку результатов и заключение даёт эксперт.",
        ):
            label = QLabel(text)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            body.addWidget(label)
        links = QHBoxLayout()
        for caption, resource in (
            ("Лицензия программы", ("compliance", "LICENSE")),
            ("Сторонние компоненты", ("THIRD_PARTY_NOTICES.md",)),
        ):
            button = QPushButton(caption)
            button.clicked.connect(lambda _checked=False, title=caption, parts=resource: self._show_text(title, parts))
            links.addWidget(button)
        body.addLayout(links)
        storage_toggle = QPushButton("Где хранятся исследования и отчёты")
        storage_toggle.setCheckable(True)
        body.addWidget(storage_toggle)
        storage = QWidget()
        storage_layout = QVBoxLayout(storage)
        storage_layout.setContentsMargins(0, 0, 0, 0)
        storage_text = QLabel(
            f"Папка исследований:\n{config.data_dir}\n\n"
            "В ней находятся база, рабочие копии и журналы. Отчёт сохраняется туда, "
            "куда вы указали при экспорте. Перед переносом на другой ПК закройте "
            "программу и скопируйте всю папку исследований. Удаление программы её не удаляет."
        )
        storage_text.setWordWrap(True)
        storage_text.setTextFormat(Qt.TextFormat.PlainText)
        storage_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        storage_layout.addWidget(storage_text)
        open_folder = QPushButton("Открыть папку исследований")
        open_folder.clicked.connect(lambda: self._open_folder(config.data_dir))
        storage_layout.addWidget(open_folder)
        storage.hide()
        storage_toggle.toggled.connect(storage.setVisible)
        body.addWidget(storage)
        body.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText("Закрыть")
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        screen = self.screen().availableGeometry()
        self.resize(min(640, screen.width() - 32), min(620, screen.height() - 48))

    def _show_text(self, title: str, parts: tuple[str, ...]) -> None:
        path = bundled_resource("app", "resources", *parts)
        # Source checkouts keep the main license at their root.
        if not path.is_file() and parts == ("compliance", "LICENSE"):
            path = bundled_resource("LICENSE")
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            QMessageBox.warning(self, title, "Файл не найден. Восстановите комплект программы из установщика.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        viewer = QTextBrowser()
        viewer.setPlainText(text)
        layout.addWidget(viewer)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText("Закрыть")
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        screen = dialog.screen().availableGeometry()
        dialog.resize(min(760, screen.width() - 32), min(620, screen.height() - 48))
        dialog.exec()

    def _open_folder(self, path: Path) -> None:
        if not path.is_dir() or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "Папка исследований", "Не удалось открыть папку. Её путь указан выше.")
