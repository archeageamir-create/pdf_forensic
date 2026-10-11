"""Build Windows LGPL ffprobe with explicit codec and compression dependencies."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAME = "ffmpeg-38b88335f9.tar.gz"
CONFIGURE = [
    "--arch=x86_64", "--target-os=mingw32", "--cc=gcc", "--cxx=g++",
    "--disable-autodetect", "--disable-gpl", "--disable-nonfree", "--disable-version3",
    "--enable-zlib", "--enable-bzlib", "--enable-lzma",
    "--enable-shared", "--disable-static", "--disable-network", "--disable-doc",
    "--disable-debug", "--disable-ffmpeg", "--disable-ffplay", "--enable-ffprobe",
    "--disable-encoders", "--disable-muxers", "--disable-avdevice", "--disable-avfilter",
    "--disable-pthreads", "--enable-w32threads", "--extra-ldflags=-static-libgcc",
]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--msys2", type=Path, default=Path("C:/msys64"))
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 2))
    parser.add_argument("--package-build", type=Path, help="Package an already completed build directory")
    parser.add_argument("--output", type=Path, default=ROOT / ".downloads/runtime/ffprobe-8.1.2-anse-lgpl.zip")
    args = parser.parse_args()
    source_archive = ROOT / "third_party_sources/archives" / SOURCE_NAME
    source_manifest = json.loads((source_archive.parent / "SOURCE_ARCHIVES_MANIFEST.json").read_text(encoding="utf-8"))
    expected = next(item["sha256"] for item in source_manifest["files"] if item["archive"] == SOURCE_NAME)
    if sha256(source_archive) != expected:
        raise ValueError("FFmpeg source checksum mismatch")
    # FFmpeg's makefiles require a source/build path without spaces.
    work = args.package_build or Path(tempfile.mkdtemp(prefix="anse-ffprobe-"))
    if " " in str(work):
        raise ValueError("Set TEMP to an ASCII path without spaces for this build")
    print(f"Build directory: {work}", flush=True)
    if not args.package_build:
        with tarfile.open(source_archive) as archive:
            archive.extractall(work, filter="data")
    source = next(work.glob("FFmpeg-*"))
    prefix = work / "installed"
    recipe = work / "build.sh"
    recipe.write_text(
        'set -euo pipefail\nexport PATH=/ucrt64/bin:/usr/bin\n'
        'export LC_ALL=C\nexport SOURCE_DATE_EPOCH=0\n'
        'for tool in gcc make nasm cmp diff; do command -v "$tool" >/dev/null; done\n'
        'source_dir=$(cygpath -u "$1")\nprefix=$(cygpath -u "$2")\n'
        'cd "$source_dir"\n'
        './configure --prefix="$prefix" ' + " ".join(CONFIGURE) + '\n'
        f'make -j{args.jobs}\nmake install\n'
        'pacman -Q make nasm diffutils mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-crt mingw-w64-ucrt-x86_64-headers mingw-w64-ucrt-x86_64-zlib mingw-w64-ucrt-x86_64-bzip2 mingw-w64-ucrt-x86_64-xz > "$prefix/toolchain.txt"\n',
        encoding="utf-8", newline="\n",
    )
    environment = dict(os.environ, MSYSTEM="UCRT64", CHERE_INVOKING="1")
    if not args.package_build:
        with (work / "build.log").open("w", encoding="utf-8") as log:
            subprocess.run([str(args.msys2 / "usr/bin/bash.exe"), "--noprofile", "--norc", str(recipe), str(source), str(prefix)], env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    configuration = dict(re.findall(r"^#define (CONFIG_\w+) ([01])$", (source / "config.h").read_text(), re.MULTILINE))
    for feature, value in {"GPL": "0", "NONFREE": "0", "VERSION3": "0", "NETWORK": "0", "ZLIB": "1", "BZLIB": "1", "LZMA": "1", "SHARED": "1", "STATIC": "0"}.items():
        if configuration.get("CONFIG_" + feature) != value:
            raise ValueError(f"Unexpected ffprobe build configuration: {feature}")
    package = work / "ffprobe-8.1.2-anse-lgpl"
    shutil.copytree(prefix / "bin", package / "bin", dirs_exist_ok=True)
    shutil.copy2(args.msys2 / "ucrt64/bin/libwinpthread-1.dll", package / "bin")
    for name in ("zlib1.dll", "libbz2-1.dll", "liblzma-5.dll"):
        shutil.copy2(args.msys2 / "ucrt64/bin" / name, package / "bin")
    for name in ("LICENSE.md", "COPYING.LGPLv2.1", "COPYING.LGPLv3", "COPYING.GPLv2", "COPYING.GPLv3"):
        shutil.copy2(source / name, package / name)
    provenance = package / "build-information"
    provenance.mkdir(exist_ok=True)
    # Configure logs include a dump of the process environment. Do not ship them.
    # Remove the old generated log when repackaging a previous build directory.
    (provenance / "config.log").unlink(missing_ok=True)
    for original, name in ((source / "config.h", "config.h"), (source / "ffbuild/config.mak", "config.mak"), (prefix / "toolchain.txt", "toolchain.txt")):
        # Keep useful build records without disclosing the build machine path.
        text = original.read_text(encoding="utf-8", errors="replace")
        text = text.replace(str(work), "BUILD_ROOT").replace(work.as_posix(), "BUILD_ROOT")
        text = text.replace("/c/" + work.as_posix()[3:], "BUILD_ROOT")
        (provenance / name).write_text(text, encoding="utf-8")
    shutil.copy2(Path(__file__), provenance / "build_ffprobe.py")
    (package / "README.txt").write_text(
        "FFprobe 8.1.2 — ANSE build from unmodified FFmpeg source 38b88335f9.\n"
        "License: LGPL-2.1-or-later. FFmpeg copyright belongs to its developers.\n"
        "The application invokes ffprobe as a separate process. FFmpeg DLLs remain replaceable.\n"
        "No GPL, nonfree or network protocols are enabled. Compression uses zlib, bzip2 and liblzma.\n"
        "This software is based in part on the work of the Independent JPEG Group.\n"
        "The IJG-derived source files have not been modified.\n"
        "Source: https://github.com/FFmpeg/FFmpeg/commit/38b88335f9\n"
        f"Source archive SHA-256: {expected}\n"
        "Recipe: build-information/build_ffprobe.py. MSYS2 UCRT64; tool versions in toolchain.txt.\n"
        "Configure: " + " ".join(CONFIGURE) + "\n",
        encoding="utf-8",
    )
    runtime_notices = args.msys2 / "ucrt64/share/licenses"
    for name in ("gcc-libs", "crt", "headers", "winpthreads", "zlib", "bzip2", "xz"):
        if (runtime_notices / name).is_dir():
            shutil.copytree(runtime_notices / name, package / "licenses" / name, dirs_exist_ok=True)
    environment["PATH"] = str(package / "bin") + os.pathsep + os.environ["WINDIR"] + "/System32"
    version = subprocess.run([str(package / "bin/ffprobe.exe"), "-version"], env=environment, capture_output=True, text=True, check=True).stdout
    version = version.replace(str(work), "BUILD_ROOT").replace(work.as_posix(), "BUILD_ROOT")
    version = version.replace("/c/" + work.as_posix()[3:], "BUILD_ROOT")
    (provenance / "ffprobe-version.txt").write_text(version, encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                output.write(path, path.relative_to(package.parent).as_posix())
    print(json.dumps({"archive": str(args.output), "sha256": sha256(args.output), "bytes": args.output.stat().st_size, "work": str(work)}), flush=True)


if __name__ == "__main__":
    main()
