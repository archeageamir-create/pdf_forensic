"""Assemble the customer distribution from an explicit file list."""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import __version__


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("Choose an empty destination for the distribution")
    dist = ROOT / "dist"
    resources = dist / "DocumentForensicInspector/_internal/app/resources"
    entries = {}
    for folder, prefix in [(resources / "licenses", "licenses"), (ROOT / "compliance", "compliance")]:
        for path in folder.rglob("*"):
            if path.is_file():
                entries[prefix + "/" + path.relative_to(folder).as_posix()] = path
    runtime = resources / "binaries"
    for path in runtime.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".exe", ".dll", ".jar", ".lib", ".pyc"}:
            continue
        relative = path.relative_to(runtime)
        if any(part.lower() in {"licenses", "legal"} for part in relative.parts) or path.name.upper().startswith(("COPYING", "LICENSE", "NOTICE")):
            entries["runtime-notices/" + relative.as_posix()] = path
    for name in ["LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "SBOM.spdx.json", "SOURCE_OFFER.md"]:
        entries[name] = ROOT / name
    for name in ["LGPL_COMPLIANCE.md", "DEPENDENCY_SOURCES.md"]:
        entries[name] = ROOT / "docs" / name
    entries["USER_AGREEMENT_RU.txt"] = ROOT / "installer/USER_AGREEMENT_RU.txt"
    licenses = dist / f"DocumentForensicInspector-Licenses-{__version__}.zip"
    with zipfile.ZipFile(licenses, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sorted(entries.items()):
            archive.write(path, name)
    with zipfile.ZipFile(licenses) as archive:
        if archive.testzip():
            raise ValueError("Invalid license archive")
    files = {
        f"DocumentForensicInspector-Setup-{__version__}.exe": dist / f"DocumentForensicInspector-Setup-{__version__}.exe",
        f"DocumentForensicInspector-{__version__}-Windows.zip": dist / f"DocumentForensicInspector-{__version__}-Windows.zip",
        f"Исходники и лицензии/DocumentForensicInspector-Source-{__version__}.zip": dist / f"DocumentForensicInspector-Source-{__version__}.zip",
        "Исходники и лицензии/" + licenses.name: licenses,
        "DocumentForensicInspector-User-Guide-RU.pdf": ROOT / "docs/user-guide/DocumentForensicInspector-User-Guide-RU.pdf",
        "README-RU.txt": ROOT / "docs/release/README-RU.txt",
        "REQUIREMENTS-RU.txt": ROOT / "docs/release/REQUIREMENTS-RU.txt",
        "USER_AGREEMENT_RU.txt": ROOT / "installer/USER_AGREEMENT_RU.txt",
        "START-HERE-RU.txt": ROOT / "docs/DRIVE_DOWNLOAD_RU.txt",
        "Исходники и лицензии/DEPENDENCY_SOURCES.md": ROOT / "docs/DEPENDENCY_SOURCES.md",
    }
    for path in files.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    output.mkdir(parents=True)
    checksums = []
    for name, source in sorted(files.items()):
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        with destination.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        checksums.append(f"{digest}  {name}")
    (output / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    print(f"Customer distribution: {len(files) + 1} files")


if __name__ == "__main__":
    main()
