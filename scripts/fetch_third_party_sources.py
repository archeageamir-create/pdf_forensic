"""Download exact corresponding-source archives recorded for a release."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_LIST = ROOT / "compliance" / "THIRD_PARTY_SOURCES.json"
DESTINATION = ROOT / "third_party_sources" / "archives"


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(item: dict[str, Any]) -> dict[str, Any]:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    target = DESTINATION / item["archive"]
    if not target.is_file():
        request = urllib.request.Request(
            item["url"], headers={"User-Agent": "DFI-source-mirror/0.4.2"}
        )
        partial = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        partial.replace(target)
    digest = _hash(target)
    expected = item.get("sha256")
    if expected and digest.casefold() != expected.casefold():
        raise RuntimeError(f"SHA-256 mismatch for {target.name}")
    return {"component": item["component"], "archive": target.name, "sha256": digest}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", action="append", default=[], help="download only matching component")
    parser.add_argument("--list", action="store_true", help="list archives without downloading")
    args = parser.parse_args()
    source_data = json.loads(SOURCE_LIST.read_text(encoding="utf-8"))
    selected = source_data["sources"]
    if args.component:
        needles = [value.casefold() for value in args.component]
        selected = [item for item in selected if any(needle in item["component"].casefold() for needle in needles)]
    if args.list:
        for item in selected:
            print(f"{item['component']} {item['version']}: {item['url']}")
        return 0
    if not selected:
        raise SystemExit("No components matched")
    manifest = [_download(item) for item in selected]
    path = DESTINATION / "SOURCE_ARCHIVES_MANIFEST.json"
    path.write_text(json.dumps({"release": source_data["release"], "files": manifest}, indent=2) + "\n", encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
