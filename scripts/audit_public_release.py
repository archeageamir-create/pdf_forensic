"""Fail closed when a release misses compliance files or leaks private material."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.4.2"
DIST = ROOT / "dist"
APP_DIR = DIST / "DocumentForensicInspector"
INSTALLER = DIST / f"DocumentForensicInspector-Setup-{VERSION}.exe"
SOURCE_ARCHIVE = DIST / f"DocumentForensicInspector-Source-{VERSION}.zip"
FORBIDDEN_SUFFIXES = {
    ".pfx", ".p12", ".pem", ".key", ".sqlite", ".sqlite3", ".db",
    ".exe", ".dll", ".jar", ".whl",
}
FORBIDDEN_PARTS = {".verification", ".downloads", ".compliance-cache", "build", "dist", "__pycache__"}
PRIVATE_PATTERNS = (
    re.compile(rb"[A-Z]:\\Users\\[^\\\r\n]+\\", re.IGNORECASE),
    re.compile(rb"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit() -> tuple[list[str], dict[str, object]]:
    errors: list[str] = []
    required_runtime = [
        APP_DIR / "DocumentForensicInspector.exe",
        APP_DIR / "_internal" / "PySide6" / "QtCore.pyd",
        APP_DIR / "_internal" / "app" / "resources" / "SBOM.spdx.json",
        APP_DIR / "_internal" / "app" / "resources" / "THIRD_PARTY_NOTICES.md",
        APP_DIR / "_internal" / "app" / "resources" / "licenses" / "qt" / "LGPL-3.0-only.txt",
        APP_DIR / "_internal" / "app" / "resources" / "compliance" / "SOURCE_OFFER.md",
        APP_DIR / "_internal" / "app" / "resources" / "bin" / "DocumentForensicToolRunner.exe",
    ]
    errors.extend(f"Missing runtime file: {path}" for path in required_runtime if not path.is_file())
    for artifact in (INSTALLER, SOURCE_ARCHIVE):
        if not artifact.is_file():
            errors.append(f"Missing release artifact: {artifact}")

    source_files = 0
    if SOURCE_ARCHIVE.is_file():
        with zipfile.ZipFile(SOURCE_ARCHIVE) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                source_files += 1
                path = Path(info.filename)
                parts = {part.casefold() for part in path.parts}
                if parts & FORBIDDEN_PARTS:
                    errors.append(f"Forbidden directory in source archive: {info.filename}")
                if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
                    errors.append(f"Forbidden file type in source archive: {info.filename}")
                data = archive.read(info)
                if len(data) <= 8 * 1024 * 1024:
                    for pattern in PRIVATE_PATTERNS:
                        if pattern.search(data):
                            errors.append(f"Private marker in source archive: {info.filename}")
                            break

    report: dict[str, object] = {
        "version": VERSION,
        "status": "failed" if errors else "passed",
        "source_files": source_files,
        "artifacts": {},
        "errors": errors,
    }
    artifact_records = report["artifacts"]
    assert isinstance(artifact_records, dict)
    for artifact in (INSTALLER, SOURCE_ARCHIVE, APP_DIR / "DocumentForensicInspector.exe"):
        if artifact.is_file():
            artifact_records[artifact.name] = {
                "size": artifact.stat().st_size,
                "sha256": _sha256(artifact),
            }
    return errors, report


def main() -> int:
    errors, report = audit()
    destination = DIST / f"DocumentForensicInspector-Release-Audit-{VERSION}.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(destination)
    print("Release audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
