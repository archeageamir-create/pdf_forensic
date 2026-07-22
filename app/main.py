from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app import __version__
from app.core.config import AppConfig
from app.core.logging_config import configure_logging
from app.core.service import ForensicsService
from app.core.settings import SettingsStore
from app.models import AnalysisMode
from app.reporting import (
    DocxReportExporter,
    HtmlReportExporter,
    JsonReportExporter,
    ZipPackageExporter,
)


def announce_headless_report(destination: Path) -> None:
    """Record a report path without assuming a console is attached."""
    resolved_destination = destination.resolve()
    logging.getLogger(__name__).info(
        "Headless report created: %s", resolved_destination
    )
    if sys.stdout is not None:
        print(resolved_destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="Document Forensic Inspector")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--analyze", type=Path, help="Run a headless analysis of one PDF/PPTX")
    parser.add_argument("--output", type=Path, help="Output report path for headless mode")
    parser.add_argument(
        "--mode",
        choices=[item.value for item in AnalysisMode if item != AnalysisMode.CUSTOM],
        default=AnalysisMode.FULL.value,
        help="Analysis mode for headless operation",
    )
    args = parser.parse_args()

    defaults = AppConfig.default()
    config = (
        SettingsStore(defaults.settings_path).load(defaults)
        if defaults.settings_path
        else defaults
    )
    config.ensure_directories()
    configure_logging(config.data_dir)
    logging.getLogger(__name__).info("Application started, version %s", __version__)
    service = ForensicsService(config)

    if args.analyze:
        result = service.analyze_file(args.analyze, mode=AnalysisMode(args.mode))
        destination = args.output or Path.cwd() / f"{args.analyze.stem}-report.json"
        suffix = destination.suffix.lower()
        if suffix == ".html":
            HtmlReportExporter().export(result, destination)
        elif suffix == ".docx":
            DocxReportExporter(config.report_template).export(result, destination)
        elif suffix == ".zip":
            ZipPackageExporter(config.report_template).export(result, destination)
        elif suffix == ".json":
            JsonReportExporter().export(result, destination)
        else:
            parser.error("--output must end in .json, .html, .docx or .zip")
        # PyInstaller's windowed bootloader intentionally exposes no stdout.
        # Headless analysis must still finish successfully in that build.
        announce_headless_report(destination)
        return 0 if not result.errors else 2

    from PySide6.QtWidgets import QApplication

    from app.gui.main_window import MainWindow
    from app.resources.theme import apply_theme

    application = QApplication(sys.argv)
    application.setApplicationName("Document Forensic Inspector")
    application.setApplicationVersion(__version__)
    application.setStyle("Fusion")
    apply_theme(application)
    window = MainWindow(service)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
