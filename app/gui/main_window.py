from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from PySide6.QtCore import QThreadPool, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStyle,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.core.service import ForensicsService
from app.core.settings import SettingsStore
from app.core.updater import UpdateInfo, UpdateService
from app.gui.dialogs import CustomAnalyzersDialog, ProjectDialog, SettingsDialog
from app.gui.widgets import (
    FindingsTable,
    HexViewer,
    PdfObjectsWidget,
    configure_resizable_columns,
)
from app.gui.workers import AnalysisWorker, FunctionWorker
from app.models import AnalysisMode, AnalysisResult, ToolRun
from app.reporting import (
    DocxReportExporter,
    HtmlReportExporter,
    JsonReportExporter,
    ZipPackageExporter,
)
from app.resources.labels import display_value, parameter_label, source_label
from app import __version__


class MainWindow(QMainWindow):
    def __init__(self, service: ForensicsService) -> None:
        super().__init__()
        self.service = service
        self.thread_pool = QThreadPool.globalInstance()
        self.current_result: AnalysisResult | None = None
        self.current_worker: AnalysisWorker | None = None
        self.background_workers: list[FunctionWorker] = []
        self.setWindowTitle("Document Forensic Inspector")
        self.resize(1560, 940)
        self.setAcceptDrops(True)
        self._create_actions()
        self._build_ui()
        self._refresh_projects()
        self.statusBar().showMessage(self.tr("Готово. Создайте проект или добавьте файл."))
        if self.service.config.update_manifest_url:
            QTimer.singleShot(1500, lambda: self._check_updates(False))

    def _create_actions(self) -> None:
        self.new_project_action = QAction(self.tr("Новый проект"), self)
        self.new_project_action.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        )
        self.new_project_action.setToolTip(self.tr("Создать карточку нового исследования"))
        self.new_project_action.triggered.connect(self._new_project)
        self.edit_project_action = QAction(self.tr("Карточка проекта"), self)
        self.edit_project_action.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        )
        self.edit_project_action.triggered.connect(self._edit_project)
        self.delete_project_action = QAction(self.tr("Удалить пустой проект"), self)
        self.delete_project_action.triggered.connect(self._delete_project)
        self.add_action = QAction(self.tr("Добавить файлы"), self)
        self.add_action.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        )
        self.add_action.setToolTip(self.tr("Выбрать один или несколько PDF/PPTX"))
        self.add_action.triggered.connect(self._choose_files)
        self.cancel_action = QAction(self.tr("Отменить анализ"), self)
        self.cancel_action.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)
        )
        self.cancel_action.triggered.connect(self._cancel_analysis)
        self.cancel_action.setEnabled(False)
        self.settings_action = QAction(self.tr("Настройки"), self)
        self.settings_action.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        )
        self.settings_action.triggered.connect(self._settings)
        self.check_tools_action = QAction(self.tr("Проверить установку"), self)
        self.check_tools_action.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.check_tools_action.triggered.connect(self._check_tools)
        self.updates_action = QAction(self.tr("Проверить обновления"), self)
        self.updates_action.triggered.connect(lambda: self._check_updates(True))
        self.about_action = QAction(self.tr("О программе"), self)
        self.about_action.triggered.connect(self._show_about)

        self.export_actions: dict[str, QAction] = {}
        for key, label in (
            ("json", "Экспорт JSON"),
            ("html", "Экспорт HTML"),
            ("docx", "Экспорт DOCX"),
            ("zip", "ZIP-пакет исследования"),
        ):
            action = QAction(self.tr(label), self)
            action.triggered.connect(lambda _checked=False, kind=key: self._export(kind))
            action.setEnabled(False)
            self.export_actions[key] = action

        file_menu = self.menuBar().addMenu(self.tr("Файл"))
        file_menu.addAction(self.new_project_action)
        file_menu.addAction(self.edit_project_action)
        file_menu.addAction(self.add_action)
        file_menu.addSeparator()
        for action in self.export_actions.values():
            file_menu.addAction(action)
        tools_menu = self.menuBar().addMenu(self.tr("Инструменты"))
        tools_menu.addAction(self.check_tools_action)
        tools_menu.addAction(self.updates_action)
        tools_menu.addAction(self.settings_action)
        help_menu = self.menuBar().addMenu(self.tr("Справка"))
        help_menu.addAction(self.about_action)

        toolbar = QToolBar()
        toolbar.setObjectName("MainToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for action in (
            self.new_project_action,
            self.edit_project_action,
            self.add_action,
            self.cancel_action,
        ):
            toolbar.addAction(action)
        toolbar.addSeparator()
        mode_label = QLabel(self.tr("Режим анализа"))
        mode_label.setObjectName("SectionLabel")
        toolbar.addWidget(mode_label)
        self.mode_combo = QComboBox()
        self.mode_combo.setMinimumWidth(150)
        self.mode_combo.setToolTip(
            self.tr("Быстрый — основные проверки; Полный — все доступные методы")
        )
        self.mode_combo.addItem(self.tr("Быстрый"), AnalysisMode.QUICK)
        self.mode_combo.addItem(self.tr("Полный"), AnalysisMode.FULL)
        self.mode_combo.addItem(self.tr("Пользовательский"), AnalysisMode.CUSTOM)
        self.mode_combo.setCurrentIndex(1)
        toolbar.addWidget(self.mode_combo)
        toolbar.addSeparator()
        toolbar.addAction(self.check_tools_action)
        toolbar.addAction(self.settings_action)
        self.addToolBar(toolbar)

    def _build_ui(self) -> None:
        root_splitter = QSplitter()
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 18, 14, 14)
        sidebar_layout.setSpacing(8)
        sidebar_title = QLabel(self.tr("Мои исследования"))
        sidebar_title.setObjectName("SidebarTitle")
        sidebar_layout.addWidget(sidebar_title)
        project_label = QLabel(self.tr("ПРОЕКТЫ"))
        project_label.setObjectName("SectionLabel")
        sidebar_layout.addWidget(project_label)
        self.project_list = QListWidget()
        self.project_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.project_list.setToolTip(self.tr("Проекты и быстрое исследование без карточки дела"))
        self.project_list.currentItemChanged.connect(self._project_selected)
        self.project_list.itemDoubleClicked.connect(lambda _item: self._edit_project())
        sidebar_layout.addWidget(self.project_list, 1)

        project_buttons = QHBoxLayout()
        new_project_button = QPushButton(self.tr("Новый проект"))
        new_project_button.setObjectName("PrimaryButton")
        new_project_button.clicked.connect(self._new_project)
        project_card_button = QPushButton(self.tr("Карточка"))
        project_card_button.clicked.connect(self._edit_project)
        project_buttons.addWidget(new_project_button)
        project_buttons.addWidget(project_card_button)
        sidebar_layout.addLayout(project_buttons)

        file_label = QLabel(self.tr("ФАЙЛЫ"))
        file_label.setObjectName("SectionLabel")
        sidebar_layout.addWidget(file_label)
        self.file_list = QListWidget()
        self.file_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.file_list.setToolTip(self.tr("Документы выбранного проекта"))
        self.file_list.currentItemChanged.connect(self._file_selected)
        sidebar_layout.addWidget(self.file_list, 2)
        delete_button = QPushButton(self.tr("Удалить пустой"))
        delete_button.setObjectName("DangerButton")
        delete_button.clicked.connect(self._delete_project)
        sidebar_layout.addWidget(delete_button)
        root_splitter.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content.setObjectName("AppRoot")
        content_layout.setContentsMargins(16, 16, 16, 12)
        content_layout.setSpacing(12)

        document_banner = QFrame()
        document_banner.setObjectName("DocumentBanner")
        banner_layout = QHBoxLayout(document_banner)
        banner_layout.setContentsMargins(16, 13, 16, 13)
        banner_layout.setSpacing(12)
        self.document_badge = QLabel(self.tr("PDF / PPTX"))
        self.document_badge.setObjectName("DocumentBadge")
        self.document_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner_layout.addWidget(self.document_badge)
        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)
        self.drop_label = QLabel(self.tr("Перетащите сюда PDF или PPTX"))
        self.drop_label.setObjectName("DocumentTitle")
        self.document_subtitle = QLabel(
            self.tr("Оригинал останется неизменным — анализ выполняется с рабочей копией")
        )
        self.document_subtitle.setObjectName("DocumentSubtitle")
        title_layout.addWidget(self.drop_label)
        title_layout.addWidget(self.document_subtitle)
        banner_layout.addLayout(title_layout, 1)
        add_button = QPushButton(self.tr("Добавить файлы"))
        add_button.setObjectName("PrimaryButton")
        add_button.clicked.connect(self._choose_files)
        banner_layout.addWidget(add_button)
        content_layout.addWidget(document_banner)

        self.welcome_panel = QWidget()
        welcome_layout = QVBoxLayout(self.welcome_panel)
        welcome_layout.setContentsMargins(40, 40, 40, 80)
        welcome_layout.addStretch(1)
        welcome_badge = QLabel("PDF  •  PPTX")
        welcome_badge.setObjectName("DocumentBadge")
        welcome_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_badge.setFixedWidth(120)
        welcome_layout.addWidget(welcome_badge, 0, Qt.AlignmentFlag.AlignHCenter)
        welcome_title = QLabel(self.tr("Начнём исследование документа"))
        welcome_title.setObjectName("WelcomeTitle")
        welcome_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(welcome_title)
        welcome_text = QLabel(
            self.tr(
                "Перетащите файл в это окно или выберите его вручную.\n"
                "Программа создаст рабочую копию, рассчитает SHA-256 и соберёт результаты в одном месте."
            )
        )
        welcome_text.setObjectName("WelcomeText")
        welcome_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_text.setWordWrap(True)
        welcome_layout.addWidget(welcome_text)
        welcome_button = QPushButton(self.tr("Выбрать документы"))
        welcome_button.setObjectName("PrimaryButton")
        welcome_button.clicked.connect(self._choose_files)
        welcome_layout.addWidget(welcome_button, 0, Qt.AlignmentFlag.AlignHCenter)
        welcome_layout.addStretch(2)
        content_layout.addWidget(self.welcome_panel, 1)

        self.tabs = QTabWidget()

        self.summary_text = _plain()
        self.summary_text.setMaximumHeight(150)
        self.hash_table = _table(["Алгоритм / свойство", "Значение"], "hashes")
        overview_page = QWidget()
        overview_layout = QVBoxLayout(overview_page)
        overview_layout.setContentsMargins(12, 12, 12, 12)
        overview_layout.setSpacing(10)
        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(10)
        for title, attribute in (
            ("Формат", "metric_format"),
            ("Размер", "metric_size"),
            ("Целостность", "metric_integrity"),
            ("Требует внимания", "metric_attention"),
        ):
            panel, value_label = _metric_panel(self.tr(title))
            setattr(self, attribute, value_label)
            metrics_layout.addWidget(panel, 1)
        overview_layout.addLayout(metrics_layout)
        summary_group = QGroupBox(self.tr("Коротко о результате"))
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.addWidget(self.summary_text)
        overview_layout.addWidget(summary_group)
        hashes_group = QGroupBox(self.tr("Файл и контрольные суммы"))
        hashes_layout = QVBoxLayout(hashes_group)
        hashes_layout.addWidget(self.hash_table)
        overview_layout.addWidget(hashes_group, 1)

        self.pdf_info_table = FindingsTable("pdf_info")
        self.xmp_table = FindingsTable("xmp")
        self.structure_table = FindingsTable("structure")
        self.advanced_checks_table = FindingsTable("advanced_checks")
        for table in (
            self.pdf_info_table,
            self.xmp_table,
            self.structure_table,
            self.advanced_checks_table,
        ):
            table.mark_changed.connect(self._mark_changed)
        self.provenance_page = QWidget()
        provenance_layout = QVBoxLayout(self.provenance_page)
        self.provenance_caution = QLabel()
        self.provenance_caution.setObjectName("CautionText")
        self.provenance_caution.setWordWrap(True)
        self.provenance_table = _table(
            ["Признак", "Значение", "Источник", "Сила признака", "Как трактовать"],
            "provenance",
        )
        provenance_layout.addWidget(self.provenance_caution)
        provenance_layout.addWidget(self.provenance_table, 1)
        self.timeline_table = _table(
            ["Дата", "Источник", "Событие", "Исходное значение", "TZ"],
            "timeline",
        )
        self.revision_table = _table(
            ["№", "Диапазон байтов", "startxref", "/Prev", "Объекты", "Метаданные", "Примечания"],
            "revisions",
        )
        revisions_page = QWidget()
        revisions_layout = QVBoxLayout(revisions_page)
        revisions_layout.setContentsMargins(0, 0, 0, 0)
        revisions_layout.addWidget(self.revision_table)
        revisions_layout.addWidget(QLabel(self.tr("Визуальные различия между ревизиями")))
        self.revision_diff_table = _table(
            ["Из ревизии", "В ревизию", "Страница", "Статус", "Изменено, %", "Diff-файл"],
            "revision_visual_diffs",
        )
        revisions_layout.addWidget(self.revision_diff_table)
        revision_actions = QHBoxLayout()
        self.open_revision_button = QPushButton(self.tr("Открыть выбранную ревизию"))
        self.open_revision_button.clicked.connect(self._open_selected_revision)
        self.open_revision_button.setEnabled(False)
        self.open_qdf_button = QPushButton(self.tr("Открыть QDF-копию"))
        self.open_qdf_button.clicked.connect(self._open_qdf)
        self.open_qdf_button.setEnabled(False)
        self.open_revision_diff_button = QPushButton(self.tr("Открыть выбранное различие"))
        self.open_revision_diff_button.clicked.connect(self._open_revision_diff)
        self.open_revision_diff_button.setEnabled(False)
        revision_actions.addWidget(self.open_revision_button)
        revision_actions.addWidget(self.open_qdf_button)
        revision_actions.addWidget(self.open_revision_diff_button)
        revision_actions.addStretch(1)
        revisions_layout.addLayout(revision_actions)
        self.revision_paths: list[Path | None] = []
        self.qdf_path: Path | None = None
        self.revision_diff_paths: list[Path | None] = []
        self.signature_table = _table(
            ["№", "ByteRange", "Покрытие", "Целостность", "Доверие", "Сертификат", "Статус"],
            "signatures",
        )
        self.attachment_table = _table(
            ["№", "Имя", "Размер", "Тип", "Дата", "Описание"],
            "attachments",
        )
        attachments_page = QWidget()
        attachments_layout = QVBoxLayout(attachments_page)
        attachments_layout.addWidget(self.attachment_table)
        extract_button = QPushButton(self.tr("Извлечь все вложения"))
        extract_button.clicked.connect(self._extract_attachments)
        attachments_layout.addWidget(extract_button)

        self.objects_widget = PdfObjectsWidget()
        self.objects_widget.offset_selected.connect(self._object_offset_selected)
        self.objects_widget.object_selected.connect(self._load_object_content)
        self.objects_widget.export_requested.connect(self._export_object)
        self.hex_widget = HexViewer(self.service)
        debugger_page = QWidget()
        debugger_layout = QVBoxLayout(debugger_page)
        debugger_note = QLabel(
            self.tr(
                "Apache PDFBox откроет рабочую копию в отдельном объектном отладчике. "
                "Исследуемый оригинал не изменяется."
            )
        )
        debugger_note.setWordWrap(True)
        self.pdfbox_debugger_button = QPushButton(self.tr("Открыть объектный отладчик PDFBox"))
        self.pdfbox_debugger_button.clicked.connect(self._open_pdfbox_debugger)
        debugger_layout.addWidget(debugger_note)
        debugger_layout.addWidget(self.pdfbox_debugger_button, 0, Qt.AlignmentFlag.AlignLeft)
        debugger_layout.addStretch(1)
        self.comparison_page = self._comparison_widget()
        self.tools_page = self._tools_widget()
        self.conclusions_page = self._conclusions_widget()

        self.metadata_tabs = _nested_tabs(
            (
                (self.pdf_info_table, "PDF Info"),
                (self.xmp_table, "XMP"),
                (self.provenance_page, "Авторство и правки"),
            )
        )
        self.structure_tabs = _nested_tabs(
            (
                (self.structure_table, "Общие сведения"),
                (revisions_page, "Ревизии"),
                (self.signature_table, "Подписи"),
                (attachments_page, "Вложения"),
                (self.advanced_checks_table, "Расширенные проверки"),
            )
        )
        object_tabs = _nested_tabs(
            (
                (self.objects_widget, "Дерево объектов"),
                (self.hex_widget, "Hex-просмотр"),
                (debugger_page, "PDFBox Debugger"),
            )
        )
        expert_tabs = _nested_tabs(
            ((self.comparison_page, "Сравнение"), (self.conclusions_page, "Заметки и выводы"))
        )
        for widget, label in (
            (overview_page, "Обзор"),
            (self.metadata_tabs, "Метаданные"),
            (self.structure_tabs, "Структура PDF"),
            (object_tabs, "Объекты и Hex"),
            (self.timeline_table, "Хронология"),
            (expert_tabs, "Эксперт"),
            (self.tools_page, "Технические данные"),
        ):
            self.tabs.addTab(widget, self.tr(label))
        content_layout.addWidget(self.tabs, 1)

        self.stage_label = QLabel()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.stage_label.hide()
        self.progress.hide()
        content_layout.addWidget(self.stage_label)
        content_layout.addWidget(self.progress)
        root_splitter.addWidget(content)
        root_splitter.setStretchFactor(1, 1)
        root_splitter.setSizes([300, 1260])
        self.setCentralWidget(root_splitter)
        self._show_welcome()

    def _tools_widget(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.tool_table = _table(
            ["Инструмент", "Версия", "Статус", "Код", "Время, мс", "Команда"],
            "tool_runs",
        )
        self.raw_combo = QComboBox()
        self.raw_combo.currentIndexChanged.connect(self._show_raw_output)
        self.raw_text = _plain()
        layout.addWidget(self.tool_table)
        layout.addWidget(self.raw_combo)
        layout.addWidget(self.raw_text)
        return widget

    def _conclusions_widget(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(self.tr("Заметки эксперта")))
        self.notes_edit = QPlainTextEdit()
        layout.addWidget(self.notes_edit)
        layout.addWidget(QLabel(self.tr("Выводы пользователя")))
        self.conclusions_edit = QPlainTextEdit()
        layout.addWidget(self.conclusions_edit)
        button = QPushButton(self.tr("Сохранить заметки и выводы"))
        button.clicked.connect(self._save_notes)
        layout.addWidget(button)
        return widget

    def _comparison_widget(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.compare_combo = QComboBox()
        button = QPushButton(self.tr("Сравнить с выбранным файлом"))
        button.clicked.connect(self._compare)
        self.compare_table = _table(
            ["Поле", "Текущий файл", "Второй файл", "Статус"],
            "comparison",
        )
        layout.addWidget(self.compare_combo)
        layout.addWidget(button)
        layout.addWidget(self.compare_table)
        return widget

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        files = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if files:
            self._start_analysis(files)
            event.acceptProposedAction()

    def _new_project(self) -> None:
        dialog = ProjectDialog(self)
        if dialog.exec():
            project = dialog.value()
            self.service.create_project(project)
            self._refresh_projects(project.id)

    def _edit_project(self) -> None:
        project_id = self._current_project_id()
        if not project_id:
            QMessageBox.information(self, self.tr("Проекты"), self.tr("Выберите проект."))
            return
        project = self.service.repository.get_project(project_id)
        if not project:
            return
        dialog = ProjectDialog(self, project)
        if dialog.exec():
            self.service.save_project(dialog.value())
            self._refresh_projects(project_id)

    def _delete_project(self) -> None:
        project_id = self._current_project_id()
        if not project_id:
            return
        if QMessageBox.question(
            self,
            self.tr("Удаление проекта"),
            self.tr("Удалить выбранный пустой проект?"),
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.repository.delete_project(project_id)
            self._refresh_projects()
        except ValueError as exc:
            QMessageBox.warning(self, self.tr("Удаление проекта"), str(exc))

    def _refresh_projects(self, select_id: str | None = None) -> None:
        self.project_list.blockSignals(True)
        self.project_list.clear()
        quick = QListWidgetItem(self.tr("Быстрое исследование"))
        quick.setToolTip(self.tr("Анализ без создания карточки проекта"))
        quick.setData(Qt.ItemDataRole.UserRole, None)
        self.project_list.addItem(quick)
        selected_row = 0
        for row, project in enumerate(self.service.repository.list_projects(), start=1):
            item = QListWidgetItem(f"{project.case_number} — {project.title}")
            item.setData(Qt.ItemDataRole.UserRole, project.id)
            self.project_list.addItem(item)
            if project.id == select_id:
                selected_row = row
        self.project_list.blockSignals(False)
        self.project_list.setCurrentRow(selected_row)

    def _project_selected(self, _current, _previous) -> None:
        self._refresh_files()

    def _refresh_files(self, select_id: str | None = None) -> None:
        self.file_list.blockSignals(True)
        self.file_list.clear()
        project_id = self._current_project_id()
        for evidence_id in self.service.repository.list_evidence_ids(project_id):
            result = self.service.repository.load(evidence_id)
            if not result:
                continue
            prefix = "⚠" if result.incomplete else "✓"
            item = QListWidgetItem(f"{prefix} {result.evidence.original_name}")
            item.setData(Qt.ItemDataRole.UserRole, evidence_id)
            self.file_list.addItem(item)
            if evidence_id == select_id:
                self.file_list.setCurrentItem(item)
        self.file_list.blockSignals(False)
        if self.file_list.count() and self.file_list.currentRow() < 0:
            self.file_list.setCurrentRow(0)
        elif not self.file_list.count():
            self._show_welcome()
        self._refresh_compare_combo()

    def _file_selected(self, current: QListWidgetItem | None, _previous) -> None:
        if not current:
            return
        result = self.service.repository.load(str(current.data(Qt.ItemDataRole.UserRole)))
        if result:
            self._display_result(result)

    def _choose_files(self) -> None:
        selected, _ = QFileDialog.getOpenFileNames(
            self,
            self.tr("Выберите документы"),
            "",
            self.tr("Документы (*.pdf *.pptx)"),
        )
        if selected:
            self._start_analysis([Path(item) for item in selected])

    def _start_analysis(self, paths: list[Path]) -> None:
        if self.current_worker is not None:
            return
        mode = self.mode_combo.currentData()
        selected: set[str] | None = None
        if mode == AnalysisMode.CUSTOM:
            dialog = CustomAnalyzersDialog(self)
            if not dialog.exec():
                return
            selected = dialog.selected()
        worker = AnalysisWorker(
            self.service,
            paths,
            self._current_project_id(),
            mode,
            selected,
        )
        worker.signals.result.connect(self._analysis_ready)
        worker.signals.error.connect(self._analysis_error)
        worker.signals.cancelled.connect(self._analysis_cancelled)
        worker.signals.progress.connect(self._analysis_progress)
        worker.signals.finished.connect(self._analysis_finished)
        self.current_worker = worker
        self.add_action.setEnabled(False)
        self.cancel_action.setEnabled(True)
        self.stage_label.setText(self.tr("Подготавливаем рабочую копию…"))
        self.stage_label.show()
        self.progress.show()
        self.progress.setRange(0, 0)
        self.statusBar().showMessage(self.tr("Исследование выполняется…"))
        self.thread_pool.start(worker)

    def _cancel_analysis(self) -> None:
        if self.current_worker:
            self.current_worker.cancel()
            self.stage_label.setText(self.tr("Отмена выполняющихся процессов…"))

    def _analysis_progress(self, stage: str, current: int, total: int) -> None:
        self.stage_label.setText(stage)
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(current)

    def _analysis_ready(self, value: object) -> None:
        if isinstance(value, AnalysisResult):
            self.current_result = value
            self._display_result(value)
            self._refresh_files(value.evidence.id)

    def _analysis_error(self, details: str) -> None:
        self.statusBar().showMessage(self.tr("Ошибка исследования"))
        logging.getLogger(__name__).error("Ошибка исследования:\n%s", details)
        detail_lines = [line.strip() for line in details.splitlines() if line.strip()]
        short_reason = detail_lines[-1] if detail_lines else self.tr("Неизвестная ошибка")
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle(self.tr("Не удалось завершить анализ"))
        dialog.setText(self.tr("Файл не был добавлен. Оригинал не изменён."))
        dialog.setInformativeText(
            self.tr("Причина: ") + short_reason + "\n\n" +
            self.tr("Технические сведения доступны по кнопке ниже.")
        )
        dialog.setDetailedText(details)
        dialog.exec()

    def _analysis_cancelled(self) -> None:
        self.statusBar().showMessage(self.tr("Исследование отменено пользователем"))

    def _analysis_finished(self) -> None:
        self.current_worker = None
        self.add_action.setEnabled(True)
        self.cancel_action.setEnabled(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.stage_label.hide()
        self.progress.hide()
        if self.current_result:
            self.statusBar().showMessage(
                self.tr("Исследование завершено частично")
                if self.current_result.incomplete
                else self.tr("Исследование завершено")
            )

    def _display_result(self, result: AnalysisResult) -> None:
        self.current_result = result
        self.welcome_panel.hide()
        self.tabs.show()
        for action in self.export_actions.values():
            action.setEnabled(True)
        self.document_badge.setText(result.evidence.detected_format or result.evidence.kind.value.upper())
        self.drop_label.setText(result.evidence.original_name)
        mode_labels = {
            AnalysisMode.QUICK.value: self.tr("быстрый анализ"),
            AnalysisMode.FULL.value: self.tr("полный анализ"),
            AnalysisMode.CUSTOM.value: self.tr("выбранные проверки"),
        }
        mode_value = str(getattr(result.evidence.analysis_mode, "value", result.evidence.analysis_mode))
        self.document_subtitle.setText(
            f"{_human_size(result.evidence.size_bytes)}  •  "
            f"{mode_labels.get(mode_value, mode_value)}  •  "
            + self.tr("оригинал не изменён")
        )
        self.summary_text.setPlainText(
            "\n\n".join(f"• {item}" for item in result.summary)
            or self.tr("Значимых наблюдений пока нет.")
        )
        attention_count = sum(
            1
            for finding in result.findings
            if finding.conflict
            or str(getattr(finding.level, "value", finding.level))
            in {"high", "manual_review"}
        )
        self.metric_format.setText(result.evidence.detected_format or result.evidence.kind.value.upper())
        self.metric_size.setText(_human_size(result.evidence.size_bytes))
        integrity_value = str(
            getattr(result.evidence.integrity_status, "value", result.evidence.integrity_status)
        )
        self.metric_integrity.setText(
            self.tr("Подтверждена") if integrity_value == "verified" else self.tr("Нарушена")
        )
        self.metric_attention.setText(str(attention_count))
        self._fill_hashes(result)
        self.pdf_info_table.populate([item for item in result.findings if item.category == "PDF Info"])
        self.xmp_table.populate([item for item in result.findings if item.category == "XMP"])
        self.structure_table.populate(
            [
                item
                for item in result.findings
                if (
                    item.category.startswith("PDF")
                    and item.category != "PDF provenance"
                    and item.category
                    not in {"PDF conformance", "PDF preservation", "PDF fonts", "PDF content"}
                )
                or item.category.startswith("PPTX")
                or item.category.startswith("OOXML")
                or item.category in {"Integrity", "Metadata conflicts", "Tool diagnostics"}
            ]
        )
        self.advanced_checks_table.populate(
            [
                item
                for item in result.findings
                if item.category
                in {"PDF conformance", "PDF preservation", "PDF fonts", "PDF content"}
            ]
        )
        self._fill_provenance(result)
        self._fill_timeline(result)
        self._fill_revisions(result)
        self._fill_signatures(result)
        self._fill_attachments(result)
        self.objects_widget.set_objects(result.artifacts.get("pdf_objects", []))
        self.hex_widget.set_path(Path(result.evidence.working_copy_path))
        self._fill_tools(result)
        self.notes_edit.setPlainText(result.evidence.user_notes)
        self.conclusions_edit.setPlainText(result.evidence.user_conclusions)
        self._refresh_compare_combo()

    def _show_welcome(self) -> None:
        self.current_result = None
        if not hasattr(self, "welcome_panel"):
            return
        self.tabs.hide()
        self.welcome_panel.show()
        self.document_badge.setText(self.tr("PDF / PPTX"))
        self.drop_label.setText(self.tr("Перетащите сюда PDF или PPTX"))
        self.document_subtitle.setText(
            self.tr("Оригинал останется неизменным — анализ выполняется с рабочей копией")
        )
        for action in self.export_actions.values():
            action.setEnabled(False)

    def _fill_hashes(self, result: AnalysisResult) -> None:
        evidence = result.evidence
        rows = [
            ("Оригинал", evidence.original_path),
            ("Рабочая копия", evidence.working_copy_path),
            ("Формат", f"{evidence.detected_format} — {evidence.mime_type}"),
            ("Размер", f"{evidence.size_bytes:,}"),
            ("SHA-256", evidence.sha256),
            ("SHA-1", evidence.sha1),
            ("MD5", evidence.md5),
            ("Целостность", display_value(evidence.integrity_status.value)),
        ]
        _fill_rows(self.hash_table, rows)

    def _fill_timeline(self, result: AnalysisResult) -> None:
        items = result.artifacts.get("timeline", [])
        rows = [
            (
                item.get("normalized") or item.get("raw", ""),
                source_label(str(item.get("source", ""))),
                parameter_label(str(item.get("name", ""))),
                item.get("raw", ""),
                "есть" if item.get("timezone_present") else "нет",
            )
            for item in items
            if isinstance(item, dict)
        ]
        _fill_rows(self.timeline_table, rows)

    def _fill_provenance(self, result: AnalysisResult) -> None:
        provenance = result.artifacts.get("pdf_provenance", {})
        if not isinstance(provenance, dict):
            provenance = {}
        self.provenance_caution.setText(
            str(
                provenance.get("caution")
                or self.tr(
                    "Метаданные могут указать заявленные имена и программы, но требуют "
                    "подтверждения другими материалами дела."
                )
            )
        )
        rows = [
            (
                item.get("role"),
                _display(item.get("value")),
                source_label(str(item.get("source", ""))),
                item.get("strength"),
                item.get("explanation"),
            )
            for item in provenance.get("signals", [])
            if isinstance(item, dict)
        ]
        _fill_rows(self.provenance_table, rows)

    def _fill_revisions(self, result: AnalysisResult) -> None:
        rows = []
        self.revision_paths = []
        for item in result.artifacts.get("pdf_revisions", []):
            reconstructed = item.get("reconstructed_path")
            self.revision_paths.append(Path(str(reconstructed)) if reconstructed else None)
            rows.append(
                (
                    item.get("number"),
                    f"{item.get('byte_start')}–{item.get('byte_end')}",
                    item.get("startxref"),
                    item.get("prev"),
                    ", ".join(map(str, item.get("changed_objects", [])[:100])),
                    json.dumps(item.get("metadata", {}), ensure_ascii=False),
                    "; ".join(item.get("notes", [])),
                )
            )
        _fill_rows(self.revision_table, rows)
        self.open_revision_button.setEnabled(any(self.revision_paths))
        qdf = result.artifacts.get("qdf_path")
        self.qdf_path = Path(str(qdf)) if qdf else None
        self.open_qdf_button.setEnabled(bool(self.qdf_path and self.qdf_path.is_file()))
        self.revision_diff_paths = []
        diff_rows = []
        status_labels = {
            "identical": "без визуальных изменений",
            "changed": "изменено",
            "page_added": "страница добавлена",
            "page_removed": "страница удалена",
        }
        for item in result.artifacts.get("revision_visual_diffs", []):
            if not isinstance(item, dict):
                continue
            diff_path = Path(str(item["diff_path"])) if item.get("diff_path") else None
            self.revision_diff_paths.append(diff_path)
            diff_rows.append(
                (
                    item.get("from_revision"),
                    item.get("to_revision"),
                    item.get("page"),
                    status_labels.get(str(item.get("status")), item.get("status")),
                    item.get("changed_percent"),
                    item.get("diff_path"),
                )
            )
        _fill_rows(self.revision_diff_table, diff_rows)
        self.open_revision_diff_button.setEnabled(
            any(path and path.is_file() for path in self.revision_diff_paths)
        )

    def _open_selected_revision(self) -> None:
        row = self.revision_table.currentRow()
        if row < 0 and self.revision_paths:
            row = len(self.revision_paths) - 1
        if 0 <= row < len(self.revision_paths):
            path = self.revision_paths[row]
            if path and path.is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_qdf(self) -> None:
        if self.qdf_path and self.qdf_path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.qdf_path)))

    def _open_revision_diff(self) -> None:
        row = self.revision_diff_table.currentRow()
        if row < 0 and self.revision_diff_paths:
            row = 0
        if 0 <= row < len(self.revision_diff_paths):
            path = self.revision_diff_paths[row]
            if path and path.is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_pdfbox_debugger(self) -> None:
        if not self.current_result:
            return
        try:
            self.service.launch_pdfbox_debugger(self.current_result)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, self.tr("PDFBox Debugger"), str(exc))

    def _fill_signatures(self, result: AnalysisResult) -> None:
        rows = []
        for index, item in enumerate(result.artifacts.get("pdf_signatures", []), start=1):
            crypto = item.get("cryptographic_validation", {})
            rows.append(
                (
                    index,
                    json.dumps(item.get("byte_range", [])),
                    display_value(item.get("covers_file_except_signature_container")),
                    display_value(crypto.get("intact")),
                    display_value(crypto.get("trusted")),
                    crypto.get("subject", item.get("declared_name", "")),
                    crypto.get("summary", crypto.get("error", "")),
                )
            )
        _fill_rows(self.signature_table, rows)

    def _fill_attachments(self, result: AnalysisResult) -> None:
        rows = [
            (
                item.get("index"),
                item.get("name"),
                item.get("size"),
                item.get("subtype"),
                item.get("modification_date"),
                item.get("description"),
            )
            for item in result.artifacts.get("pdf_attachments", [])
        ]
        _fill_rows(self.attachment_table, rows)

    def _fill_tools(self, result: AnalysisResult) -> None:
        rows = [
            (
                run.tool_name,
                run.version,
                display_value(run.status.value),
                run.exit_code,
                run.duration_ms,
                json.dumps(run.command, ensure_ascii=False),
            )
            for run in result.tool_runs
        ]
        _fill_rows(self.tool_table, rows)
        self.raw_combo.clear()
        for index, run in enumerate(result.tool_runs):
            self.raw_combo.addItem(run.tool_name, index)
        self._show_raw_output(0)

    def _show_raw_output(self, index: int) -> None:
        if not self.current_result or not (0 <= index < len(self.current_result.tool_runs)):
            self.raw_text.clear()
            return
        run = self.current_result.tool_runs[index]
        self.raw_text.setPlainText(
            f"COMMAND\n{json.dumps(run.command, ensure_ascii=False)}\n\nVERSION\n{run.version}"
            f"\n\nSTDOUT\n{run.stdout}\n\nSTDERR\n{run.stderr}"
        )

    def _mark_changed(self, finding_id: str, mark: str, include: bool) -> None:
        self.service.repository.update_finding_mark(finding_id, mark, include)
        if self.current_result:
            for finding in self.current_result.findings:
                if finding.id == finding_id:
                    finding.user_mark = mark
                    finding.include_in_report = include
                    break

    def _save_notes(self) -> None:
        if not self.current_result:
            return
        evidence = self.current_result.evidence
        evidence.user_notes = self.notes_edit.toPlainText()
        evidence.user_conclusions = self.conclusions_edit.toPlainText()
        self.service.repository.update_evidence_notes(
            evidence.id, evidence.user_notes, evidence.user_conclusions
        )
        QMessageBox.information(self, self.tr("Выводы"), self.tr("Сохранено."))

    def _extract_attachments(self) -> None:
        if not self.current_result:
            return
        destination = QFileDialog.getExistingDirectory(self, self.tr("Каталог извлечения"))
        if not destination:
            return
        try:
            items = self.service.extract_attachments(self.current_result, Path(destination))
            QMessageBox.information(
                self,
                self.tr("Вложения"),
                self.tr(f"Извлечено файлов: {len(items)}"),
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("Ошибка извлечения"), str(exc))

    def _object_offset_selected(self, offset: int) -> None:
        self.hex_widget.jump_to(offset)

    def _load_object_content(self, object_number: int, generation: int) -> None:
        if not self.current_result:
            return
        try:
            payload = self.service.read_pdf_object(
                self.current_result, object_number, generation
            )
            self.objects_widget.set_object_content(payload)
        except (OSError, ValueError) as exc:
            self.objects_widget.set_object_content({"decode_error": str(exc)})

    def _export_object(self, object_number: int, generation: int) -> None:
        if not self.current_result:
            return
        selected, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Экспорт PDF-объекта"),
            f"object-{object_number}-{generation}.bin",
            self.tr("Все файлы (*)"),
        )
        if selected:
            try:
                self.service.export_pdf_object(
                    self.current_result, object_number, generation, Path(selected)
                )
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, self.tr("Ошибка экспорта объекта"), str(exc))

    def _refresh_compare_combo(self) -> None:
        self.compare_combo.clear()
        if not self.current_result:
            return
        for evidence_id in self.service.repository.list_evidence_ids(
            self.current_result.evidence.project_id
        ):
            if evidence_id == self.current_result.evidence.id:
                continue
            result = self.service.repository.load(evidence_id)
            if result and result.evidence.kind == self.current_result.evidence.kind:
                self.compare_combo.addItem(result.evidence.original_name, evidence_id)

    def _compare(self) -> None:
        if not self.current_result or self.compare_combo.currentIndex() < 0:
            return
        comparison = self.service.compare(
            self.current_result.evidence.id, str(self.compare_combo.currentData())
        )
        rows = [
            (
                parameter_label(str(item["field"])),
                _display(item["left"]),
                _display(item["right"]),
                {
                    "same": "совпадает",
                    "changed": "изменено",
                    "added": "добавлено",
                    "removed": "удалено",
                }.get(str(item["status"]), str(item["status"])),
            )
            for item in comparison.items
        ]
        _fill_rows(self.compare_table, rows)

    def _settings(self) -> None:
        dialog = SettingsDialog(self.service.config, self)
        if dialog.exec():
            config = dialog.value()
            if config.settings_path:
                SettingsStore(config.settings_path).save(config)
            self.service = ForensicsService(config)
            self.hex_widget.service = self.service
            self._refresh_projects(self._current_project_id())

    def _check_tools(self) -> None:
        self.check_tools_action.setEnabled(False)
        worker = FunctionWorker(self.service.check_installation)
        worker.signals.result.connect(self._show_installation)
        worker.signals.error.connect(self._analysis_error)
        worker.signals.finished.connect(lambda: self.check_tools_action.setEnabled(True))
        worker.signals.finished.connect(lambda: self._release_background_worker(worker))
        self.background_workers.append(worker)
        self.thread_pool.start(worker)

    def _show_installation(self, value: object) -> None:
        if not isinstance(value, list):
            return
        lines = [
            f"{'✓' if run.status.value == 'completed' else '✗'} {run.tool_name}: "
            f"{run.version} [{run.status.value}]"
            for run in value
            if isinstance(run, ToolRun)
        ]
        QMessageBox.information(
            self,
            self.tr("Проверка установки"),
            "\n".join(lines),
        )

    def _check_updates(self, manual: bool) -> None:
        url = self.service.config.update_manifest_url
        if not url:
            if manual:
                QMessageBox.information(
                    self,
                    self.tr("Обновления"),
                    self.tr("Укажите URL манифеста обновлений в настройках."),
                )
            return
        self.updates_action.setEnabled(False)
        updater = UpdateService(url)
        worker = FunctionWorker(lambda: updater.check(__version__))
        worker.signals.result.connect(
            lambda value, u=updater, m=manual: self._update_checked(value, u, m)
        )
        worker.signals.error.connect(
            lambda details, m=manual: self._update_error(details, m)
        )
        worker.signals.finished.connect(lambda: self.updates_action.setEnabled(True))
        worker.signals.finished.connect(lambda: self._release_background_worker(worker))
        self.background_workers.append(worker)
        self.thread_pool.start(worker)

    def _update_checked(
        self, value: object, updater: UpdateService, manual: bool
    ) -> None:
        if not isinstance(value, UpdateInfo):
            if manual:
                QMessageBox.information(
                    self, self.tr("Обновления"), self.tr("Установлена актуальная версия.")
                )
            return
        answer = QMessageBox.question(
            self,
            self.tr("Доступно обновление"),
            self.tr(f"Доступна версия {value.version}.\n{value.notes}\n\nЗагрузить установщик?"),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        worker = FunctionWorker(
            lambda: updater.download(value, self.service.config.reports_dir / "updates")
        )
        worker.signals.result.connect(self._update_downloaded)
        worker.signals.error.connect(lambda details: self._update_error(details, True))
        worker.signals.finished.connect(lambda: self._release_background_worker(worker))
        self.background_workers.append(worker)
        self.thread_pool.start(worker)

    def _update_downloaded(self, value: object) -> None:
        path = Path(str(value))
        if QMessageBox.question(
            self,
            self.tr("Обновление загружено"),
            self.tr(f"SHA-256 проверен. Запустить установщик?\n{path}"),
        ) == QMessageBox.StandardButton.Yes:
            subprocess.Popen([str(path)], shell=False)

    def _update_error(self, details: str, manual: bool) -> None:
        if manual:
            QMessageBox.warning(self, self.tr("Ошибка обновления"), details)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            self.tr("О программе"),
            self.tr(
                f"<h3>Document Forensic Inspector {__version__}</h3>"
                "<p><b>Автор оболочки, интеграции и Windows-сборки:</b><br>"
                "Amirkhan Smagulov</p>"
                "<p>Приложение объединяет независимые open-source инструменты в "
                "едином графическом интерфейсе. Amirkhan Smagulov не является "
                "автором ExifTool, qpdf, pdfcpu, Poppler, JHOVE, veraPDF, "
                "Apache PDFBox, PDFiD, pdf-parser и других сторонних компонентов.</p>"
                "<p>Авторские права и лицензии на эти компоненты принадлежат их "
                "разработчикам. Полные тексты лицензий входят в поставку.</p>"
                "<p>Перечень компонентов зафиксирован в SPDX SBOM. Для LGPL-компонентов "
                "разрешены замена библиотек и отладка собственных модификаций; исходники "
                "доступны по письменному предложению в комплекте поставки.</p>"
                "<p><small>Самоподписанная Authenticode-подпись подтверждает "
                "целостность подписанной сборки после доверия сертификату, но не "
                "является сертификатом публичного удостоверяющего центра.</small></p>"
            ),
        )

    def _release_background_worker(self, worker: FunctionWorker) -> None:
        if worker in self.background_workers:
            self.background_workers.remove(worker)

    def _export(self, kind: str) -> None:
        if not self.current_result:
            return
        filters = {
            "json": ("JSON (*.json)", ".json"),
            "html": ("HTML (*.html)", ".html"),
            "docx": ("Word (*.docx)", ".docx"),
            "zip": ("ZIP (*.zip)", ".zip"),
        }
        file_filter, suffix = filters[kind]
        selected, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Сохранить отчёт"),
            f"{Path(self.current_result.evidence.original_name).stem}-report{suffix}",
            file_filter,
        )
        if not selected:
            return
        project = (
            self.service.repository.get_project(self.current_result.evidence.project_id)
            if self.current_result.evidence.project_id
            else None
        )
        try:
            if kind == "json":
                JsonReportExporter().export(self.current_result, Path(selected))
            elif kind == "html":
                HtmlReportExporter().export(self.current_result, Path(selected))
            elif kind == "docx":
                DocxReportExporter(self.service.config.report_template).export(
                    self.current_result, Path(selected), project
                )
            else:
                audit = self.service.repository.list_audit(self.current_result.evidence.project_id)
                ZipPackageExporter(self.service.config.report_template).export(
                    self.current_result, Path(selected), project, audit
                )
            self.service.repository.log_event(
                "report_exported",
                self.current_result.evidence.id,
                f"{kind}: {selected}",
                self.current_result.evidence.project_id,
            )
            QMessageBox.information(self, self.tr("Экспорт"), self.tr("Отчёт сохранён."))
        except Exception as exc:
            QMessageBox.critical(self, self.tr("Ошибка экспорта"), str(exc))

    def _current_project_id(self) -> str | None:
        item = self.project_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item and item.data(Qt.ItemDataRole.UserRole) else None


def _table(headers: list[str], settings_key: str) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.verticalHeader().setVisible(False)
    defaults = [170 for _header in headers]
    if defaults:
        defaults[0] = 210
        defaults[-1] = 300 if len(defaults) > 1 else defaults[-1]
    configure_resizable_columns(table, settings_key, defaults)
    return table


def _fill_rows(table: QTableWidget, rows: list[tuple]) -> None:
    table.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem("" if value is None else str(value))
            item.setToolTip(item.text())
            table.setItem(row, column, item)


def _plain() -> QPlainTextEdit:
    widget = QPlainTextEdit()
    widget.setReadOnly(True)
    return widget


def _metric_panel(title: str) -> tuple[QFrame, QLabel]:
    panel = QFrame()
    panel.setObjectName("MetricPanel")
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(2)
    value = QLabel("—")
    value.setObjectName("MetricValue")
    label = QLabel(title)
    label.setObjectName("MetricLabel")
    layout.addWidget(value)
    layout.addWidget(label)
    return panel, value


def _nested_tabs(items: tuple[tuple[QWidget, str], ...]) -> QTabWidget:
    tabs = QTabWidget()
    tabs.setDocumentMode(True)
    for widget, label in items:
        tabs.addTab(widget, label)
    return tabs


def _human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < 1024 or unit == "ТБ":
            return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} Б"


def _display(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return "" if value is None else str(value)
