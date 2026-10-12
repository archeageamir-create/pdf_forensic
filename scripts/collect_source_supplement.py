"""Collect exact upstream recipes and sources for the redistributed native/Java components."""
from __future__ import annotations

import concurrent.futures
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".downloads/source-audit"
DEST = ROOT / "third_party_sources/archives/supplement"
RECORDS = ROOT / "compliance/source-records"
CUTOFF = "2026-05-04T04:28:11"
POPPLER = {
    "poppler": ("poppler.dll", "26.02.0"), "libfreetype6": ("freetype.dll", "2.14.3"),
    "libzlib": ("zlib.dll", "1.3.2"), "zstd": ("zstd.dll", "1.5.7"),
    "libtiff": ("tiff.dll", "4.7.1"), "libssh2": ("libssh2.dll", "1.11.1"),
    "libpng": ("libpng16.dll", None), "libcurl": ("libcurl.dll", "8.20.0"),
    "openssl": ("libcrypto-3-x64.dll", "3.6.2"), "openjpeg": ("openjp2.dll", "2.5.4"),
    "libjpeg-turbo": ("jpeg8.dll", "3.1.4.1"), "liblzma": ("liblzma.dll", "5.8.3"),
    "libdeflate": ("deflate.dll", "1.25"), "lerc": ("Lerc.dll", "4.1.0"),
    "lcms2": ("lcms2.dll", "2.19"),
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(url: str, path: Path, expected: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "ANSE-source-delivery"})
                with urllib.request.urlopen(request, timeout=90) as response, path.with_suffix(path.suffix + ".part").open("wb") as output:
                    shutil.copyfileobj(response, output)
                path.with_suffix(path.suffix + ".part").replace(path)
                break
            except urllib.error.HTTPError as error:
                if error.code in (403, 404):
                    raise
                if attempt == 2:
                    raise
                time.sleep(2)
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(2)
    if expected and digest(path).lower() != expected.lower():
        raise ValueError(f"Checksum mismatch: {path.name}")
    return path


def conda_info(path: Path) -> tarfile.TarFile:
    if path.suffix == ".conda":
        with zipfile.ZipFile(path) as archive:
            data = archive.read(next(n for n in archive.namelist() if n.startswith("info-")))
        raw = subprocess.run(["C:/msys64/usr/bin/zstd.exe", "-d", "-c"], input=data, capture_output=True, check=True).stdout
        return tarfile.open(fileobj=io.BytesIO(raw))
    return tarfile.open(path)


def poppler_component(name: str, dll: str, version: str | None) -> dict:
    metadata = json.loads(fetch(f"https://api.anaconda.org/package/conda-forge/{name}", CACHE / f"{name}.json").read_text())
    candidates = [item for item in metadata["files"] if item["basename"].startswith("win-64/")
                  and str(item.get("upload_time", ""))[:19] <= CUTOFF
                  and (not version or item.get("version", "").rstrip(".0") == version.rstrip(".0"))]
    candidates.sort(key=lambda item: item.get("upload_time", ""), reverse=True)
    runtime = ROOT / "app/resources/binaries/poppler/bin" / dll
    binary_hash = digest(runtime)
    for item in candidates[:18]:
        archive_name = Path(item["basename"]).name
        binary = fetch("https:" + item["download_url"], CACHE / archive_name, item.get("sha256"))
        with conda_info(binary) as archive:
            paths = json.load(archive.extractfile("info/paths.json"))["paths"]
            matched = [p for p in paths if p["_path"].casefold() == f"library/bin/{dll}".casefold() and p.get("sha256") == binary_hash]
            if not matched:
                continue
            target = RECORDS / "conda" / archive_name.split(".conda")[0]
            target.mkdir(parents=True, exist_ok=True)
            for member in archive:
                if member.isfile() and member.name.startswith(("info/recipe/", "info/licenses/")):
                    dest = target / member.name
                    if not dest.resolve().is_relative_to(target.resolve()):
                        raise ValueError(member.name)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(archive.extractfile(member).read())
            recipe_path = target / "info/recipe/meta.yaml"
            if recipe_path.exists():
                recipe = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
            else:
                recipe = yaml.safe_load((target / "info/recipe/rendered_recipe.yaml").read_text(encoding="utf-8"))["recipe"]
            source = recipe.get("source", [])
            if isinstance(source, dict):
                source = [source]
            sources = []
            for index, spec in enumerate(source):
                urls = spec.get("url", [])
                if isinstance(urls, str):
                    urls = [urls]
                error = None
                for url in urls:
                    try:
                        filename = f"conda-{name}-{item['version']}-{index}-" + url.rsplit("/", 1)[-1]
                        path = fetch(url, DEST / filename, spec.get("sha256"))
                        sources.append({"file": path.name, "url": url, "sha256": digest(path)})
                        break
                    except (OSError, ValueError) as exc:
                        error = str(exc)
                else:
                    raise RuntimeError(f"Missing source for {name}: {error or spec}")
            return {"component": name, "version": item["version"], "binary": dll, "binary_sha256": binary_hash,
                    "package_url": "https:" + item["download_url"], "package_sha256": digest(binary),
                    "recipe": target.relative_to(ROOT).as_posix(), "license": recipe.get("about", {}).get("license"), "sources": sources}
    raise RuntimeError(f"No exact binary/source match for {name} ({dll}); candidates: {len(candidates)}")


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    DEST.mkdir(parents=True, exist_ok=True)
    RECORDS.mkdir(parents=True, exist_ok=True)
    records = []
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        pending = {pool.submit(poppler_component, name, dll, version): name for name, (dll, version) in POPPLER.items()}
        for result in concurrent.futures.as_completed(pending):
            try:
                record = result.result()
                records.append(record)
                print(f"Matched {record['component']} {record['version']}", flush=True)
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError, tarfile.TarError, zipfile.BadZipFile) as error:
                errors.append({"component": pending[result], "error": str(error)})
                print(errors[-1], flush=True)
    (RECORDS / "poppler-provenance.json").write_text(json.dumps({"components": sorted(records, key=lambda item: item["component"]), "errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
