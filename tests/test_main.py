from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from app import main as main_module


class HeadlessMainTests(unittest.TestCase):
    def test_headless_mode_does_not_require_stdout(self) -> None:
        with patch.object(main_module.sys, "stdout", None):
            main_module.announce_headless_report(Path("report.json"))


if __name__ == "__main__":
    unittest.main()
