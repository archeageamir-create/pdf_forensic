"""Create a public source archive from an explicit allowlist."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.4.2"
ARCHIVE = ROOT / "dist" / f"DocumentForensicInspector-Source-{VERSION}.zip"
DIRECTORIES = ("app", "compliance", "docs", "installer", "scripts", "signing", "tests")
FILES = (
    ".gitignore",
    "build.ps1",
    "CONTRIBUTING.md",
    "create-self-signed-certificate.ps1",
    "DocumentForensicInspector.spec",
    "DocumentForensicToolRunner.spec",
    "LICENSE",
    "NOTICE",
    "pyproject.toml",
    "README.md",
    "requirements-dev.txt",
    "requirements.txt",
    "run.ps1",
    "SECURITY.md",
    "sign-build.ps1",
    "SOURCE_OFFER.md",
    "THIRD_PARTY_NOTICES.md",
    "SBOM.spdx.json",
    "PRODUCT.md",
    "Launch.vbs",
    "setup.ps1",
    "build-preview.ps1",
    "DocumentForensicInspectorPreview.spec",
)
EXCLUDED_PARTS = {
    "__pycache__",
    ".pytest_cache",
    "binaries",
    "bin",
    "archives",
}
EXCLUDED_SUFFIXES = {".pyc", ".pfx", ".p12", ".pem", ".key", ".exe", ".dll", ".jar"}


def allowed(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    return path.suffix.lower() not in EXCLUDED_SUFFIXES


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Label this development snapshot as a universal preview.",
    )
    args = parser.parse_args()
    version = VERSION + "+universal-preview" if args.preview else VERSION
    archive_path = ROOT / "dist" / f"DocumentForensicInspector-Source-{version}.zip"
    ROOT.joinpath("dist").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dfi-public-source-") as temporary:
        stage = Path(temporary) / f"document-forensic-inspector-{version}"
        stage.mkdir()
        for filename in FILES:
            source = ROOT / filename
            if not source.is_file():
                raise FileNotFoundError(source)
            target = stage / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for directory in DIRECTORIES:
            source_root = ROOT / directory
            for source in source_root.rglob("*"):
                if not source.is_file() or not allowed(source):
                    continue
                relative = source.relative_to(ROOT)
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

        manifest: list[dict[str, str | int]] = []
        for source in sorted(path for path in stage.rglob("*") if path.is_file()):
            data = source.read_bytes()
            manifest.append(
                {
                    "path": source.relative_to(stage).as_posix(),
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        (stage / "SOURCE_MANIFEST.json").write_text(
            json.dumps({"version": version, "files": manifest}, indent=2) + "\n",
            encoding="utf-8",
        )
        with tempfile.NamedTemporaryFile(
            dir=archive_path.parent, suffix=".tmp", delete=False
        ) as output:
            staged_archive = Path(output.name)
        try:
            with zipfile.ZipFile(
                staged_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
            ) as archive:
                for source in sorted(
                    path for path in stage.rglob("*") if path.is_file()
                ):
                    archive.write(source, source.relative_to(stage.parent))
            staged_archive.replace(archive_path)
        finally:
            staged_archive.unlink(missing_ok=True)

    print(archive_path)
    print(f"SHA256={hashlib.sha256(archive_path.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
