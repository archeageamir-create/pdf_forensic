from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


# Mood: quiet evidence desk — clear daylight, graphite folders, one indigo tab marker.
# Qt Style Sheets do not support OKLCH, so these are sRGB conversions of the
# restrained OKLCH palette selected for the desktop client.
APP_STYLE = """
QWidget {
    color: #202536;
    font-family: "Segoe UI";
    font-size: 10pt;
}
QMainWindow, QWidget#AppRoot { background: #f5f6fa; }
QMenuBar {
    background: #ffffff;
    border-bottom: 1px solid #e1e4ec;
    padding: 3px 8px;
}
QMenuBar::item { padding: 6px 10px; border-radius: 6px; }
QMenuBar::item:selected { background: #eeeff8; color: #39366f; }
QMenu {
    background: #ffffff;
    border: 1px solid #d9dde8;
    padding: 6px;
}
QMenu::item { padding: 7px 28px 7px 10px; border-radius: 5px; }
QMenu::item:selected { background: #eeeff8; color: #39366f; }
QToolBar#MainToolbar {
    background: #ffffff;
    border: 0;
    border-bottom: 1px solid #e1e4ec;
    spacing: 5px;
    padding: 7px 12px;
}
QToolBar#MainToolbar QToolButton {
    background: transparent;
    border: 0;
    border-radius: 7px;
    padding: 7px 10px;
}
QToolBar#MainToolbar QToolButton:hover { background: #f0f1f6; }
QToolBar#MainToolbar QToolButton:pressed { background: #e6e8f0; }
QToolBar#MainToolbar QToolButton:disabled { color: #9ba2b2; }
QWidget#Sidebar {
    background: #eef0f5;
    border-right: 1px solid #dfe2ea;
}
QLabel#SidebarTitle { font-size: 14pt; font-weight: 650; color: #22283a; }
QLabel#SectionLabel { color: #636b7d; font-size: 9pt; font-weight: 600; }
QListWidget {
    background: transparent;
    border: 0;
    outline: 0;
    padding: 2px;
}
QListWidget::item {
    border-radius: 7px;
    padding: 8px 9px;
    margin: 1px 0;
}
QListWidget::item:hover { background: #e5e7ef; }
QListWidget::item:selected { background: #dadbea; color: #302d65; }
QFrame#DocumentBanner {
    background: #ffffff;
    border: 1px solid #dfe2ea;
    border-radius: 12px;
}
QLabel#DocumentBadge {
    background: #e7e7f5;
    color: #39366f;
    border-radius: 8px;
    font-weight: 700;
    padding: 8px 10px;
}
QLabel#DocumentTitle { font-size: 15pt; font-weight: 650; color: #1d2232; }
QLabel#DocumentSubtitle { color: #687083; }
QLabel#WelcomeTitle { font-size: 16pt; font-weight: 650; color: #252b3b; }
QLabel#WelcomeText { color: #687083; font-size: 10.5pt; }
QLabel#CautionText {
    background: #f2f2f9;
    color: #3f4560;
    border: 1px solid #dcddea;
    border-radius: 8px;
    padding: 9px 11px;
}
QFrame#MetricPanel {
    background: #f8f9fc;
    border: 1px solid #e4e6ed;
    border-radius: 10px;
}
QLabel#MetricValue { font-size: 12pt; font-weight: 650; color: #252b3b; }
QLabel#MetricLabel { color: #6b7385; font-size: 9pt; }
QGroupBox {
    background: #ffffff;
    border: 1px solid #e0e3eb;
    border-radius: 10px;
    margin-top: 13px;
    padding: 14px 10px 10px 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
    color: #353b4d;
}
QTabWidget::pane {
    background: #ffffff;
    border: 1px solid #dfe2ea;
    border-radius: 9px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #5d6577;
    border: 0;
    padding: 9px 13px;
    margin-right: 2px;
}
QTabBar::tab:hover { color: #39366f; background: #f0f1f7; border-radius: 7px; }
QTabBar::tab:selected {
    color: #39366f;
    font-weight: 650;
    border-bottom: 2px solid #514e9b;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #cfd4df;
    border-radius: 7px;
    padding: 7px 12px;
    min-height: 18px;
}
QPushButton:hover { background: #f5f6fa; border-color: #aeb5c5; }
QPushButton:pressed { background: #e9ebf1; }
QPushButton:focus { border: 2px solid #7773bd; padding: 6px 11px; }
QPushButton#PrimaryButton {
    background: #4d4a98;
    color: #ffffff;
    border: 0;
    font-weight: 600;
    padding: 8px 14px;
}
QPushButton#PrimaryButton:hover { background: #403d85; }
QPushButton#DangerButton { color: #a13b46; border-color: #e0b8bd; }
QPushButton:disabled, QPushButton#PrimaryButton:disabled, QPushButton#DangerButton:disabled {
    color: #626a7c;
    background: #edf0f4;
    border: 1px solid #dde1e8;
}
QComboBox, QLineEdit, QSpinBox, QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #cfd4df;
    border-radius: 6px;
    padding: 5px 7px;
    selection-background-color: #d9d9ef;
    selection-color: #202536;
}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover { border-color: #aeb5c5; }
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QPlainTextEdit:focus {
    border: 2px solid #7773bd;
    padding: 4px 6px;
}
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox { padding-right: 27px; }
QComboBox::down-arrow { image: url("@@ICON_DIR@@/chevron-down.svg"); width: 12px; height: 8px; }
QTableWidget, QTreeWidget {
    background: #ffffff;
    alternate-background-color: #f7f8fb;
    border: 0;
    gridline-color: #e3e5eb;
    selection-background-color: #dedff0;
    selection-color: #202536;
}
QTableWidget::item { padding: 6px; }
QHeaderView::section {
    background: #eef0f5;
    color: #3b4253;
    border: 0;
    border-right: 1px solid #dde0e8;
    border-bottom: 1px solid #d5d9e3;
    padding: 7px;
    font-weight: 600;
}
QProgressBar {
    background: #e4e6ed;
    border: 0;
    border-radius: 4px;
    max-height: 8px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk { background: #5d5aa3; border-radius: 4px; }
QStatusBar { background: #ffffff; color: #697184; border-top: 1px solid #e1e4ec; }
QSplitter::handle { background: #dfe2ea; width: 1px; height: 1px; }
QToolTip {
    background: #252936;
    color: #ffffff;
    border: 0;
    padding: 5px;
}
"""


def apply_theme(application: QApplication) -> None:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#f5f6fa"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#202536"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f7f8fb"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#202536"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#202536"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#4d4a98"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#626a7c"))
    application.setPalette(palette)
    application.setFont(QFont("Segoe UI", 10))
    application.setStyleSheet(APP_STYLE.replace("@@ICON_DIR@@", (Path(__file__).parent / "icons").as_posix()))
