from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    download_url: str
    sha256: str
    notes: str = ""


class UpdateService:
    """Checks a configured manifest and verifies an installer before use."""

    def __init__(self, manifest_url: str, timeout_seconds: int = 15) -> None:
        self.manifest_url = manifest_url.strip()
        self.timeout_seconds = timeout_seconds

    def check(self, current_version: str) -> UpdateInfo | None:
        if not self.manifest_url:
            return None
        with urllib.request.urlopen(self.manifest_url, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
        info = UpdateInfo(
            version=str(payload["version"]),
            download_url=str(payload["download_url"]),
            sha256=str(payload["sha256"]).casefold(),
            notes=str(payload.get("notes", "")),
        )
        if not re.fullmatch(r"[0-9a-f]{64}", info.sha256):
            raise ValueError("Манифест обновления содержит некорректный SHA-256")
        if urlparse(info.download_url).scheme not in {"https", "file"}:
            raise ValueError("Обновление разрешено загружать только по HTTPS")
        return info if _version_tuple(info.version) > _version_tuple(current_version) else None

    def download(self, info: UpdateInfo, destination_dir: Path) -> Path:
        destination_dir.mkdir(parents=True, exist_ok=True)
        filename = Path(urlparse(info.download_url).path).name or "DocumentForensicInspector-Setup.exe"
        filename = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
        destination = destination_dir / filename
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        digest = hashlib.sha256()
        with urllib.request.urlopen(info.download_url, timeout=self.timeout_seconds) as response:
            with temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
        if digest.hexdigest().casefold() != info.sha256:
            temporary.unlink(missing_ok=True)
            raise ValueError("SHA-256 загруженного обновления не совпадает с манифестом")
        temporary.replace(destination)
        return destination


def _version_tuple(value: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", value)
    return tuple(int(item) for item in numbers[:4]) or (0,)
