"""Freeze Python sources for a reproducible long test while development continues."""

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

root = Path(__file__).resolve().parents[1]
snapshot = root / ".verification" / "soak-source-20260914"
snapshot.mkdir(parents=True, exist_ok=False)
for name in ("app", "tests"):
    shutil.copytree(
        root / name,
        snapshot / name,
        ignore=shutil.ignore_patterns("__pycache__", "binaries"),
    )
(snapshot / "scripts").mkdir()
shutil.copy2(root / "scripts" / "soak-queue.py", snapshot / "scripts" / "soak-queue.py")
manifest = {
    str(path.relative_to(snapshot)): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in snapshot.rglob("*.py")
}
(snapshot / "source-manifest.json").write_text(
    json.dumps(
        {"created_at": datetime.now(UTC).isoformat(), "sha256": manifest}, indent=2
    ),
    encoding="utf-8",
)
print(snapshot)
