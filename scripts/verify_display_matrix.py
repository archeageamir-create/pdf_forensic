"""Exercise native Qt layouts with real fonts at five scale factors."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def scenario(output: Path, width: int, height: int) -> dict:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontDatabase, QGuiApplication
    from PySide6.QtWidgets import QApplication, QDialogButtonBox
    from app.gui.main_window import MainWindow
    from app.gui.dialogs import ProjectDialog, SettingsDialog
    from app.gui.about import AboutDialog
    from app.resources.theme import apply_theme
    from tests.test_persistence_reporting import sample_result
    from tests.test_universal import service_at

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "consola.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
    app.setStyle("Fusion")
    apply_theme(app)
    output.mkdir(parents=True, exist_ok=False)
    window = MainWindow(service_at(output / "data"))
    window.sidebar_action.setChecked(width >= 1000)
    window.show()
    app.processEvents()
    window.resize(width, height)
    app.processEvents()
    assert window.width() <= width and window.height() <= height, (window.size().toTuple(), width, height)
    window.grab().save(str(output / "welcome.png"))
    window._display_result(sample_result())
    window.expert_mode.setChecked(True)
    visited = []
    for index in range(window.tabs.count()):
        if not window.tabs.isTabVisible(index):
            continue
        window.tabs.setCurrentIndex(index)
        app.processEvents()
        assert window.width() <= width and window.height() <= height
        if window.tabs.currentWidget() is not window.queue_panel:
            assert window.save_report_button.isVisible()
            assert window.document_banner.rect().contains(window.save_report_button.geometry())
        window.grab().save(str(output / f"tab-{index}.png"))
        visited.append(window.tabs.tabText(index))
    for dialog in (ProjectDialog(window), SettingsDialog(window.service.config, window), AboutDialog(window.service.config, window)):
        dialog.resize(min(680, width - 30), min(480, height - 40))
        dialog.show()
        app.processEvents()
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons and dialog.rect().contains(buttons.geometry())
        dialog.grab().save(str(output / f"{type(dialog).__name__}.png"))
        dialog.close()
    record = {"logical_size": [width, height], "scale": os.environ["QT_SCALE_FACTOR"], "actual_size": list(window.size().toTuple()), "tabs": visited, "dialogs": "save/cancel visible", "rendering": "Qt offscreen with Windows Segoe UI fonts; not a physical-monitor test"}
    (output / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    window.close()
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", nargs=2, type=int)
    args = parser.parse_args()
    if args.size:
        scenario(args.output, *args.size)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for scale, width, height in ((1, 1366, 728), (1.25, 1093, 574), (1.5, 911, 480), (1.75, 1097, 577), (2, 960, 500), (2, 1920, 1040)):
        target = args.output / f"scale-{scale}-{width}"
        environment = dict(os.environ, QT_SCALE_FACTOR=str(scale), QT_QPA_PLATFORM="offscreen")
        subprocess.run([sys.executable, __file__, "--output", str(target), "--size", str(width), str(height)], env=environment, check=True, timeout=60)
        results.append(json.loads((target / "result.json").read_text(encoding="utf-8")))
    (args.output / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"scenarios": len(results), "status": "passed"}))


if __name__ == "__main__":
    main()
