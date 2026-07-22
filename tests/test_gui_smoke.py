from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHeaderView

from app.core.config import AppConfig
from app.core.service import ForensicsService
from app.gui.main_window import MainWindow
from tests.test_persistence_reporting import sample_result


class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_main_window_can_render_analysis_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = AppConfig(
                data_dir=root,
                database_path=root / "db.sqlite3",
                cases_dir=root / "cases",
                reports_dir=root / "reports",
                create_qdf_in_full_mode=False,
                validate_signatures=False,
            )
            window = MainWindow(ForensicsService(config))
            result = sample_result()
            window._display_result(result)
            self.assertEqual(window.drop_label.text(), result.evidence.original_name)
            self.assertEqual(window.about_action.text(), "О программе")
            self.assertTrue(all(action.isEnabled() for action in window.export_actions.values()))
            for table in (
                window.structure_table,
                window.advanced_checks_table,
                window.revision_table,
                window.revision_diff_table,
                window.hash_table,
            ):
                header = table.horizontalHeader()
                self.assertTrue(
                    all(
                        header.sectionResizeMode(column)
                        == QHeaderView.ResizeMode.Interactive
                        for column in range(table.columnCount())
                    )
                )
            window.close()


if __name__ == "__main__":
    unittest.main()
