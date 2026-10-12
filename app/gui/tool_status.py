from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.gui.widgets import configure_resizable_columns
from app.models import ToolRunStatus


PURPOSES = {
    "ExifTool": "Метаданные, EXIF, GPS и следы программ для разных форматов",
    "ffprobe": "Контейнер, кодеки, длительность и дорожки аудио/видео",
    "qpdf": "Объекты, структура, шифрование и исследовательская копия PDF",
    "pdfcpu": "Независимая проверка PDF, формы, вложения и подписи",
    "Poppler": "Текст, шрифты, изображения и отображение PDF",
    "Java runtime": "Среда для JHOVE, veraPDF и PDFBox",
    "JHOVE PDF-hul": "Форматная корректность PDF",
    "veraPDF": "Соответствие PDF/A и PDF/UA",
    "Apache PDFBox": "Независимый парсер и отладчик PDF",
    "pdfid.py": "Быстрый поиск структурных маркеров PDF",
    "pdf-parser.py": "Статистика и разбор объектов PDF",
}


class ToolStatusDialog(QDialog):
    def __init__(self, runs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Готовность инструментов")
        self.resize(920, 620)
        self.runs = runs
        layout = QVBoxLayout(self)
        ready = sum(run.status == ToolRunStatus.COMPLETED for run in runs)
        label = QLabel(
            f"Доступно внешних компонентов: {ready} из {len(runs)}. Встроенные проверки изображений, Office, ZIP и хешей доступны без этих программ."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        self.table = QTableWidget(len(runs), 4)
        self.table.setHorizontalHeaderLabels(
            ["Инструмент", "Для чего нужен", "Состояние", "Версия"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        configure_resizable_columns(self.table, "tool_readiness", [130, 370, 150, 170])
        for row, run in enumerate(runs):
            status = (
                "Готов"
                if run.status == ToolRunStatus.COMPLETED
                else "Не найден"
                if run.status == ToolRunStatus.UNAVAILABLE
                else "Не запустился"
            )
            for col, text in enumerate(
                (
                    run.tool_name,
                    PURPOSES.get(run.tool_name, "Дополнительный анализ"),
                    status,
                    run.version,
                )
            ):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, col, item)
        layout.addWidget(self.table, 1)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail)
        self.table.currentCellChanged.connect(self._selected)
        self.configure = QPushButton("Настроить пути к инструментам")
        self.configure.clicked.connect(self.accept)
        layout.addWidget(self.configure)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        if runs:
            self.table.setCurrentCell(0, 0)

    def _selected(self, row, *_):
        if 0 <= row < len(self.runs):
            run = self.runs[row]
            self.detail.setPlainText(
                f"{run.tool_name}\n{PURPOSES.get(run.tool_name, '')}\n\nКоманда: {' '.join(run.command)}\n\n{run.stdout}\n{run.stderr}"
            )
