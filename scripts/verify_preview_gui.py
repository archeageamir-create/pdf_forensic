"""Verify the built GUI starts and executes a queued fixture, without UI input.

This catches missing Qt DLLs that headless --drain-queue cannot detect. The
owned test process is stopped after the saved result is checked; it does not
exercise interactive controls or a user's existing workspace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image
from app.core.database import AnalysisRepository
from app.core.job_queue import JobQueue
from app.models import AnalysisMode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--exe",
        type=Path,
        default=ROOT
        / "dist/DocumentForensicInspectorPreview/DocumentForensicInspectorPreview.exe",
    )
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    specimen = root / "SYNTHETIC-GUI-PROBE.jpg"
    Image.new("RGB", (80, 60), "#436C82").save(specimen)
    digest = hashlib.sha256(specimen.read_bytes()).hexdigest()
    workspace = root / "workspace"
    queue = JobQueue(workspace / "queue.sqlite3")
    queue.enqueue(specimen, mode=AnalysisMode.QUICK)
    startup = None
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
    started = time.monotonic()
    process = subprocess.Popen(
        [str(args.exe.resolve()), "--data-dir", str(workspace)],
        startupinfo=startup,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(f"GUI exited unexpectedly: {process.returncode}")
            job = queue.list_jobs()[0]
            if job.status in {"completed", "partial", "failed"}:
                break
            time.sleep(0.1)
        assert job.status in {"completed", "partial"}, (
            f"GUI did not initialize or process its queue: {job}"
        )
        result = AnalysisRepository(workspace / "forensics.sqlite3").load(
            job.evidence_id
        )
        assert result and result.evidence.sha256 == digest and not result.errors
        assert hashlib.sha256(specimen.read_bytes()).hexdigest() == digest
        summary = {
            "completed_utc": datetime.now(UTC).isoformat(),
            "native_gui_initialized": True,
            "gui_background_queue_completed": True,
            "original_unchanged": True,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "exe_sha256": hashlib.sha256(args.exe.read_bytes()).hexdigest(),
            "all_checks_passed": True,
        }
        (root / "summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary))
    finally:
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    main()
