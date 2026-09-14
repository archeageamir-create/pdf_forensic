"""Measure a synthetic saved case; this does not claim real-file analysis throughput."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication
from app.core.project_search import search_project
from app.gui.main_window import MainWindow
from app.models import Finding
from tests.test_persistence_reporting import sample_result
from tests.test_universal import service_at


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--files", type=int, default=1000)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    service = service_at(root / "workspace")
    start = time.perf_counter()
    for i in range(args.files):
        result = sample_result()
        result.evidence.id = str(uuid4())
        result.evidence.original_name = f"СИНТЕТИКА-{i:05d}.pdf"
        result.findings = [
            Finding(
                "EXIF",
                f"Tag {tag}",
                f"Synthetic value {i} " + "данные " * 25,
                "Synthetic fixture",
            )
            for tag in range(50)
        ]
        if i == args.files // 2:
            result.findings.append(
                Finding("PDF Info", "Author", "УНИКАЛЬНЫЙ ЭКСПЕРТ", "Synthetic fixture")
            )
        service.repository.save(result)
    saved_seconds = time.perf_counter() - start
    start = time.perf_counter()
    search = search_project(service.config.database_path, None, "уникальный эксперт")
    search_seconds = time.perf_counter() - start
    assert len(search.hits) == 1 and not search.interrupted
    application = QApplication([])
    start = time.perf_counter()
    window = MainWindow(service)
    application.processEvents()
    startup_seconds = time.perf_counter() - start
    assert window.file_list.count() == args.files
    start = time.perf_counter()
    window.file_search.setText("СИНТЕТИКА-00005")
    application.processEvents()
    filter_seconds = time.perf_counter() - start
    assert (
        sum(
            not window.file_list.item(i).isHidden()
            for i in range(window.file_list.count())
        )
        == 1
    )
    window.close()
    summary = {
        "synthetic_saved_files": args.files,
        "synthetic_findings": args.files * 50 + 1,
        "save_seconds": round(saved_seconds, 3),
        "project_search_seconds": round(search_seconds, 3),
        "gui_constructor_seconds": round(startup_seconds, 3),
        "sidebar_filter_seconds": round(filter_seconds, 3),
        "database_bytes": service.config.database_path.stat().st_size,
        "all_checks_passed": True,
    }
    (root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
