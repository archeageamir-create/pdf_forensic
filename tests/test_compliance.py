from __future__ import annotations

import json
import unittest
from pathlib import Path

from app import __version__
from scripts.create_public_source_archive import ROOT, allowed


class ComplianceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def test_release_versions_and_spdx_inventory_match(self) -> None:
        components = json.loads(
            (self.root / "compliance" / "components.json").read_text(encoding="utf-8")
        )
        sbom = json.loads((self.root / "SBOM.spdx.json").read_text(encoding="utf-8"))
        self.assertEqual(components["application"]["version"], __version__)
        self.assertEqual(sbom["spdxVersion"], "SPDX-2.3")
        app_package = next(
            package for package in sbom["packages"]
            if package["name"] == "Document Forensic Inspector"
        )
        self.assertEqual(app_package["versionInfo"], __version__)
        self.assertGreaterEqual(len(sbom["packages"]), 40)

    def test_required_public_release_documents_exist(self) -> None:
        for relative in (
            "LICENSE",
            "NOTICE",
            "SOURCE_OFFER.md",
            "THIRD_PARTY_NOTICES.md",
            "SBOM.spdx.json",
            "compliance/THIRD_PARTY_SOURCES.json",
            "docs/LGPL_COMPLIANCE.md",
            "app/resources/licenses/qt/LGPL-3.0-only.txt",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((self.root / relative).is_file())

    def test_public_archive_filter_rejects_binaries_and_keys(self) -> None:
        self.assertFalse(allowed(ROOT / "app" / "resources" / "binaries" / "qpdf.exe"))
        self.assertFalse(allowed(ROOT / "signing" / "private-key.pfx"))
        self.assertFalse(allowed(ROOT / "tests" / "__pycache__" / "test.pyc"))
        self.assertTrue(allowed(ROOT / "app" / "main.py"))

    def test_source_manifest_covers_copyleft_components(self) -> None:
        sources = json.loads(
            (self.root / "compliance" / "THIRD_PARTY_SOURCES.json").read_text(
                encoding="utf-8"
            )
        )["sources"]
        names = {item["component"] for item in sources}
        self.assertIn("Qt libraries used by PySide6", names)
        self.assertIn("Poppler", names)
        self.assertIn("JHOVE", names)
        self.assertIn("Eclipse Temurin OpenJDK", names)
        self.assertTrue(all(item["url"].startswith("https://") for item in sources))

    def test_pyinstaller_layout_is_onedir(self) -> None:
        spec = (self.root / "DocumentForensicInspector.spec").read_text(encoding="utf-8")
        self.assertIn("exclude_binaries=True", spec)
        self.assertIn("coll = COLLECT(", spec)


if __name__ == "__main__":
    unittest.main()
