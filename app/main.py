from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from app import __version__
from app.core.config import AppConfig
from app.core.logging_config import configure_logging
from app.core.service import ForensicsService
from app.core.settings import SettingsStore
from app.models import AnalysisMode, ToolRunStatus
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
    import multiprocessing
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="Document Forensic Inspector")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--analyze", type=Path, help="Run a headless analysis of a file (format detected from content)")
    parser.add_argument("--output", type=Path, help="Output report path for headless mode")
    parser.add_argument("--watch", type=Path, help="Continuously analyze new files in a local folder")
    parser.add_argument("--recursive", action="store_true", help="Include subfolders with --watch")
    parser.add_argument("--drain-queue", action="store_true", help="Process saved pending jobs and exit")
    parser.add_argument("--check-tools", action="store_true", help="Check every engine and write diagnostics to --output JSON")
    parser.add_argument("--data-dir", type=Path, help="Use a separate local workspace for evidence, settings and queue")
    parser.add_argument(
        "--mode",
        choices=[item.value for item in AnalysisMode if item != AnalysisMode.CUSTOM],
        default=AnalysisMode.FULL.value,
        help="Analysis mode for headless operation",
    )
    args = parser.parse_args()
    if sum(bool(value) for value in (args.analyze, args.watch, args.drain_queue, args.check_tools)) > 1:
        parser.error("Choose one of --analyze, --watch, --drain-queue, --check-tools")
    if args.check_tools and (not args.output or args.output.suffix.lower() != ".json"):
        parser.error("--check-tools requires --output with a .json file")

    defaults = AppConfig.default()
    if args.data_dir:
        from dataclasses import replace
        data_dir = args.data_dir.expanduser().resolve()
        defaults = replace(defaults, data_dir=data_dir, database_path=data_dir / "forensics.sqlite3", cases_dir=data_dir / "cases", reports_dir=data_dir / "reports", settings_path=data_dir / "settings.json")
    config = (
        SettingsStore(defaults.settings_path).load(defaults)
        if defaults.settings_path
        else defaults
    )
    if args.data_dir:
        config = replace(config, **{key: getattr(defaults, key) for key in ("data_dir", "database_path", "cases_dir", "reports_dir", "settings_path")})
    config.ensure_directories()
    configure_logging(config.data_dir)
    logging.getLogger(__name__).info("Application started, version %s", __version__)
    service = ForensicsService(config)

    if args.check_tools:
        runs = service.check_installation()
        healthy = all(run.status == ToolRunStatus.COMPLETED for run in runs)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"all_tools_available": healthy, "tools": [asdict(run) for run in runs]}, ensure_ascii=False, indent=2), encoding="utf-8")
        announce_headless_report(args.output)
        return 0 if healthy else 2

    if args.watch or args.drain_queue:
        import signal
        from app.core.daemon import QueueDaemon
        from app.core.job_queue import JobQueue
        queue = JobQueue(config.data_dir / "queue.sqlite3")
        daemon = QueueDaemon(service, queue)
        if args.watch:
            root = args.watch.expanduser().resolve()
            if any(root.is_relative_to(path.resolve()) for path in (config.data_dir, config.cases_dir, config.reports_dir)):
                parser.error("Watch folder must be outside the application workspace")
            queue.save_watch(root, None, AnalysisMode(args.mode), args.recursive)
        signal.signal(signal.SIGINT, lambda *_: daemon.stop())
        signal.signal(signal.SIGTERM, lambda *_: daemon.stop())
        daemon.run(once=args.drain_queue)
        return 0

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
        return 0 if not result.incomplete else 2

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from app.gui.main_window import MainWindow
    from app.resources.theme import apply_theme

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    application = QApplication(sys.argv)
    application.setApplicationName("Document Forensic Inspector")
    application.setApplicationVersion(__version__)
    application.setStyle("Fusion")
    apply_theme(application)
    window = MainWindow(service)
    window.start_background_processing()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
