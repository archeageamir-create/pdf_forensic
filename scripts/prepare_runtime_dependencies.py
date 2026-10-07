"""Prepare the complete Windows tool payload from pinned, verified downloads.

Only the build machine uses the network. The resulting application does not
download engines, run installers, or depend on the host's Python/Java/PATH.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "compliance/runtime-dependencies.lock.json"
PAYLOAD = ROOT / "app/resources/binaries"
REQUIRED = (
    "ExifTool.exe", "exiftool_files/perl532.dll", "exiftool_files/exiftool.pl",
    "qpdf/qpdf.exe", "qpdf/qpdf30.dll", "pdfcpu/pdfcpu.exe",
    "ffmpeg/ffprobe.exe", "java/bin/java.exe", "java/bin/javaw.exe", "java/lib/modules",
    "jhove/bin/jhove-apps-1.34.0.jar", "jhove/conf/jhove.conf",
    "verapdf/bin/cli-1.30.2.jar", "pdfbox/pdfbox-app-3.0.8.jar",
    *(f"poppler/bin/{name}.exe" for name in ("pdfinfo", "pdffonts", "pdfimages", "pdfdetach", "pdftotext", "pdftoppm")),
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_bundle(folder: Path = PAYLOAD) -> dict:
    manifest_path = folder / "RUNTIME_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["lock_sha256"] != digest(LOCK):
        raise ValueError("Runtime lock changed; prepare the dependencies again")
    expected = {item["path"]: item for item in manifest["files"]}
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and p != manifest_path}
    if actual != set(expected):
        raise ValueError(f"Runtime file set differs: missing={set(expected) - actual}, extra={actual - set(expected)}")
    base = folder.resolve()
    for relative, item in expected.items():
        path = folder / relative
        if path.is_symlink() or not path.resolve().is_relative_to(base):
            raise ValueError(f"Runtime file escapes payload: {relative}")
        if path.stat().st_size != item["size"] or digest(path) != item["sha256"]:
            raise ValueError(f"Runtime file modified: {relative}")
    missing = [name for name in REQUIRED if not (folder / name).is_file()]
    if missing:
        raise ValueError(f"Required runtime files missing: {missing}")
    return manifest


def fetch(item: dict, cache: Path, allow_download: bool) -> Path:
    target = cache / item["filename"]
    if not target.is_file():
        if not allow_download:
            raise FileNotFoundError(f"Missing {target.name}. Run with --download on the build machine.")
        request = urllib.request.Request(item["url"], headers={"User-Agent": "DocumentForensicInspector-build"})
        temporary = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        if digest(temporary) != item["sha256"]:
            raise ValueError(f"Downloaded checksum mismatch: {target.name}")
        temporary.replace(target)
    if digest(target) != item["sha256"]:
        raise ValueError(f"Cached checksum mismatch: {target.name}")
    return target


def extract_zip(archive: Path, destination: Path) -> None:
    base = destination.resolve()
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            if not (base / member.filename).resolve().is_relative_to(base):
                raise ValueError(f"Unsafe archive member: {member.filename}")
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"Archive symlink: {member.filename}")
        package.extractall(base)


def copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(source, target, dirs_exist_ok=True)


def install_java_tool(java: Path, jar: Path, target: Path, work: Path) -> None:
    # IzPack only unpacks these packages; isolate Java's user preferences too.
    if not target.resolve().is_relative_to(work.resolve()):
        raise ValueError("Installer target must stay inside the staging directory")
    options = work / (target.name + "-install.properties")
    value = "INSTALL_PATH=" + target.as_posix() + "\n"
    options.write_text(value.encode("ascii", "backslashreplace").decode("ascii"), encoding="ascii")
    environment = dict(os.environ)
    for key in ("JAVA_HOME", "JDK_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "CLASSPATH"):
        environment.pop(key, None)
    result = subprocess.run(
        [str(java), "-Djava.awt.headless=true", f"-Duser.home={work / 'installer-home'}", "-jar", str(jar), "-options", str(options)],
        cwd=work, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", timeout=180,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    (work / (target.name + "-install.log")).write_text(result.stdout, encoding="utf-8")
    if result.returncode or not (target / "bin").is_dir():
        raise RuntimeError(f"{target.name} unpack failed: {result.stdout[-4000:]}")


def prepare(allow_download: bool = False) -> dict:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    cache = ROOT / ".downloads/runtime"
    cache.mkdir(parents=True, exist_ok=True)
    archives = {item["name"]: fetch(item, cache, allow_download) for item in lock["components"]}
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="runtime-stage-", dir=build) as temporary:
        work = Path(temporary).resolve()
        if not work.is_relative_to(build.resolve()):
            raise ValueError("Unexpected staging path")
        stage = work / "payload"
        stage.mkdir()
        extracted = {}
        for name, archive in archives.items():
            if archive.suffix == ".zip":
                destination = work / "archives" / name
                extract_zip(archive, destination)
                extracted[name] = next(p for p in destination.iterdir() if p.is_dir())
        copy_tree(extracted["exiftool"], stage)
        (stage / "exiftool(-k).exe").rename(stage / "ExifTool.exe")
        copy_tree(extracted["qpdf"] / "bin", stage / "qpdf")
        copy_tree(extracted["qpdf"] / "share", stage / "qpdf/share")
        copy_tree(extracted["pdfcpu"], stage / "pdfcpu")
        copy_tree(extracted["poppler"] / "Library/bin", stage / "poppler/bin")
        copy_tree(extracted["poppler"] / "Library/share", stage / "poppler/share")
        copy_tree(extracted["poppler"] / "share", stage / "poppler/distribution-share")
        copy_tree(extracted["java"], stage / "java")
        (stage / "ffmpeg").mkdir()
        shutil.copy2(extracted["ffprobe"] / "bin/ffprobe.exe", stage / "ffmpeg/ffprobe.exe")
        for file in extracted["ffprobe"].iterdir():
            if file.is_file():
                shutil.copy2(file, stage / "ffmpeg" / file.name)
        (stage / "pdfbox").mkdir()
        shutil.copy2(archives["pdfbox"], stage / "pdfbox" / archives["pdfbox"].name)
        java = stage / "java/bin/java.exe"
        vera_jar = next(extracted["verapdf"].glob("*.jar"))
        for name, jar in (("jhove", archives["jhove"]), ("verapdf", vera_jar)):
            installed = work / "installed" / name
            install_java_tool(java, jar, installed, work)
            for directory in installed.iterdir():
                if directory.is_dir() and directory.name != "Uninstaller":
                    copy_tree(directory, stage / name / directory.name)
            copy_tree(ROOT / "app/resources/licenses" / name, stage / name / "licenses")
        # The adapter provides the config and classpath explicitly. No path to
        # the builder's temporary installation may survive in the portable file.
        conf = stage / "jhove/conf/jhove.conf"
        conf.write_text(re.sub(r"<jhoveHome>.*?</jhoveHome>", "<jhoveHome>.</jhoveHome>", conf.read_text(encoding="utf-8"), flags=re.S), encoding="utf-8")
        copy_tree(ROOT / "app/resources/licenses/pdfbox", stage / "pdfbox/licenses")
        manifest = {
            "schema": 1, "platform": lock["platform"], "lock_sha256": digest(LOCK),
            "components": lock["components"],
            "files": [{"path": p.relative_to(stage).as_posix(), "size": p.stat().st_size, "sha256": digest(p)} for p in sorted(stage.rglob("*")) if p.is_file()],
        }
        (stage / "RUNTIME_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        verify_bundle(stage)
        if PAYLOAD.exists():
            if not PAYLOAD.resolve().is_relative_to((ROOT / "app/resources").resolve()):
                raise ValueError("Unexpected existing runtime location")
            # Preserve an existing payload for recovery; do not merge versions.
            PAYLOAD.rename(build / ("runtime-previous-" + uuid.uuid4().hex))
        stage.rename(PAYLOAD)
    return verify_bundle()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        manifest = verify_bundle()
    else:
        try:
            manifest = verify_bundle()
        except (OSError, ValueError, KeyError):
            manifest = prepare(args.download)
    print(json.dumps({"runtime_files_verified": len(manifest["files"]), "components": len(manifest["components"]), "complete": True}))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
