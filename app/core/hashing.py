from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable


HashProgress = Callable[[int, int], None]


def calculate_hashes(
    path: Path,
    chunk_size: int = 1024 * 1024,
    progress: HashProgress | None = None,
) -> dict[str, str]:
    algorithms = {
        "sha256": hashlib.sha256(),
        "sha1": hashlib.sha1(usedforsecurity=False),
        "md5": hashlib.md5(usedforsecurity=False),
    }
    processed = 0
    total = path.stat().st_size
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            for digest in algorithms.values():
                digest.update(chunk)
            processed += len(chunk)
            if progress:
                progress(processed, total)
    return {name: digest.hexdigest() for name, digest in algorithms.items()}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    return calculate_hashes(path, chunk_size)["sha256"]
