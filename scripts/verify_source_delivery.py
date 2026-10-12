"""Seal and verify the exact source/recipe files delivered with this release."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import __version__
from scripts.verify_native_dependencies import verify as verify_native

LOCK = ROOT / "compliance/SOURCE_DELIVERY.json"
SOURCES = ROOT / "third_party_sources/archives"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_file(base: Path, name: str, expected: str) -> None:
    path = base / name
    if not path.resolve().is_relative_to(base.resolve()) or path.is_symlink():
        raise ValueError(f"Source path escapes its directory: {name}")
    if not path.is_file() or digest(path) != expected:
        raise ValueError(f"Missing or changed source/recipe: {name}")


def source_inputs() -> dict[str, str]:
    original = json.loads((SOURCES / "SOURCE_ARCHIVES_MANIFEST.json").read_text(encoding="utf-8"))
    sources = {item["archive"]: item["sha256"] for item in original["files"]}
    for name in ("poppler-provenance.json", "java-provenance.json"):
        provenance = json.loads((ROOT / "compliance/source-records" / name).read_text(encoding="utf-8"))
        if provenance["errors"]:
            raise ValueError(f"Unresolved source records: {name}")
        for component in provenance["components"]:
            for file in component.get("sources", []) + component.get("files", []) + component.get("parents", []):
                sources["supplement/" + file["file"]] = file["sha256"]
    java_build = json.loads((ROOT / "compliance/source-records/temurin-build.json").read_text(encoding="utf-8"))
    sources["supplement/" + java_build["file"]] = java_build["sha256"]
    pillow = json.loads((ROOT / "compliance/source-records/pillow-provenance.json").read_text(encoding="utf-8"))
    for file in pillow["files"]:
        sources["supplement/" + file["file"]] = file["sha256"]
    compression = json.loads((ROOT / "compliance/source-records/ffprobe-compression.json").read_text(encoding="utf-8"))
    for file in compression["files"]:
        sources["supplement/" + file["file"]] = file["sha256"]
    return sources


def seal() -> None:
    sources = source_inputs()
    for name, expected in sources.items():
        verify_file(SOURCES, name, expected)
    records = [p for p in (ROOT / "compliance/source-records").rglob("*") if p.is_file()]
    records += [ROOT / name for name in ("scripts/build_ffprobe.py", "scripts/prepare_runtime_dependencies.py", "compliance/runtime-dependencies.lock.json")]
    data = {
        "version": __version__,
        "scope": "Exact upstream source archives, Poppler supplier recipes/patches, Java source JARs/build POMs, Temurin build scripts, Pillow text-shaping sources and the ANSE ffprobe recipe. Technical delivery verification; not a legal opinion.",
        "archives": [{"file": name, "sha256": expected, "bytes": (SOURCES / name).stat().st_size} for name, expected in sorted(sources.items())],
        "records": [{"file": p.relative_to(ROOT).as_posix(), "sha256": digest(p)} for p in sorted(records)],
    }
    LOCK.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def verify() -> dict:
    from scripts.prepare_runtime_dependencies import verify_bundle
    verify_bundle()
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    if lock["version"] != __version__:
        raise ValueError("Source delivery version differs from application")
    expected = {item["file"]: item["sha256"] for item in lock["archives"]}
    if expected != source_inputs():
        raise ValueError("Source provenance changed since delivery was sealed")
    for base, key in ((SOURCES, "archives"), (ROOT, "records")):
        for item in lock[key]:
            verify_file(base, item["file"], item["sha256"])
    provenance = json.loads((ROOT / "compliance/source-records/poppler-provenance.json").read_text(encoding="utf-8"))
    for item in provenance["components"]:
        verify_file(ROOT / "app/resources/binaries/poppler/bin", item["binary"], item["binary_sha256"])
    native = verify_native(ROOT / "app/resources/binaries")
    return {"archives_verified": len(lock["archives"]), "recipes_verified": len(lock["records"]), "native_dependency_files": {name: len(files) for name, files in native.items()}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal", action="store_true", help="Intentionally record reviewed sources/recipes for a new release")
    args = parser.parse_args()
    if args.seal:
        seal()
    print(json.dumps(verify()))
