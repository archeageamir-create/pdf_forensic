"""Fetch canonical license texts for native libraries bundled with Poppler."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "app" / "resources" / "licenses" / "poppler-dependencies"
URLS = {
    "libdeflate-LICENSE.txt": "https://raw.githubusercontent.com/ebiggers/libdeflate/master/COPYING",
    "freetype-LICENSE.txt": "https://raw.githubusercontent.com/freetype/freetype/VER-2-14-3/LICENSE.TXT",
    "libjpeg-turbo-LICENSE.md": "https://raw.githubusercontent.com/libjpeg-turbo/libjpeg-turbo/3.1.4.1/LICENSE.md",
    "littlecms-LICENSE.txt": "https://raw.githubusercontent.com/mm2/Little-CMS/lcms2.19/LICENSE",
    "Lerc-LICENSE.txt": "https://raw.githubusercontent.com/Esri/lerc/master/LICENSE",
    "openssl-LICENSE.txt": "https://raw.githubusercontent.com/openssl/openssl/openssl-3.6.2/LICENSE.txt",
    "curl-COPYING.txt": "https://raw.githubusercontent.com/curl/curl/curl-8_20_0/COPYING",
    "xz-COPYING.txt": "https://raw.githubusercontent.com/tukaani-project/xz/v5.8.3/COPYING",
    "libpng-LICENSE.txt": "https://raw.githubusercontent.com/pnggroup/libpng/v1.6.58/LICENSE",
    "libssh2-COPYING.txt": "https://raw.githubusercontent.com/libssh2/libssh2/libssh2-1.11.1/COPYING",
    "openjpeg-LICENSE.txt": "https://raw.githubusercontent.com/uclouvain/openjpeg/v2.5.4/LICENSE",
    "libtiff-LICENSE.md": "https://gitlab.com/libtiff/libtiff/-/raw/v4.7.1/LICENSE.md",
    "zlib-LICENSE.txt": "https://raw.githubusercontent.com/madler/zlib/v1.3.2/LICENSE",
    "zstd-LICENSE.txt": "https://raw.githubusercontent.com/facebook/zstd/v1.5.7/LICENSE",
}


def main() -> int:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    manifest = []
    for filename, url in URLS.items():
        request = urllib.request.Request(url, headers={"User-Agent": "DFI-compliance-builder/0.4.2"})
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
        if len(content) < 100:
            raise RuntimeError(f"Unexpectedly short license text: {url}")
        target = DESTINATION / filename
        target.write_bytes(content)
        manifest.append({
            "file": filename,
            "source": url,
            "sha256": hashlib.sha256(content).hexdigest(),
        })
        print(f"Fetched {filename}")
    (DESTINATION / "MANIFEST.json").write_text(
        json.dumps({"files": manifest}, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
