"""Verify every source-manifest hash and run the tests from the extracted sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    child_environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--archive",
        type=Path,
        default=ROOT
        / "dist/DocumentForensicInspector-Source-0.4.2+universal-preview.zip",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(args.archive) as archive:
        for item in archive.infolist():
            assert (output / item.filename).resolve().is_relative_to(output)
        assert archive.testzip() is None
        archive.extractall(output)
    sources = output / "document-forensic-inspector-0.4.2+universal-preview"
    manifest = json.loads(
        (sources / "SOURCE_MANIFEST.json").read_text(encoding="utf-8")
    )
    for item in manifest["files"]:
        path = sources / item["path"]
        assert path.resolve().is_relative_to(sources)
        assert path.stat().st_size == item["size"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    assert not any(
        p.name in {".git", ".venv", ".verification", ".env"} for p in sources.rglob("*")
    )
    # Explicitly check which app is imported despite the dev environment's
    # editable installation, before trusting a green run from this directory.
    imported = subprocess.check_output(
        [sys.executable, "-c", "import app; print(app.__file__)"],
        cwd=sources,
        text=True,
        encoding="utf-8",
        env=child_environment,
    ).strip()
    assert Path(imported).resolve().is_relative_to(sources)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", f"--junitxml={output / 'tests.xml'}"],
        cwd=sources,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_environment,
        timeout=180,
    )
    (output / "tests.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0
    summary = {
        "archive_sha256": hashlib.sha256(args.archive.read_bytes()).hexdigest(),
        "manifest_files_verified": len(manifest["files"]),
        "imported_app_from_archive": True,
        "tests_exit_code": result.returncode,
        "all_checks_passed": True,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
