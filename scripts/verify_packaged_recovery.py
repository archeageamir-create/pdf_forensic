"""Kill an owned preview executor during a synthetic job, then verify recovery."""

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
    specimen = root / "СИНТЕТИКА-recovery.bin"
    chunk = b"synthetic evidence\0" * 65536
    digest = hashlib.sha256()
    with specimen.open("wb") as output:
        for _ in range(64):
            output.write(chunk)
            digest.update(chunk)
    workspace = root / "workspace"
    queue = JobQueue(workspace / "queue.sqlite3")
    queue.enqueue(specimen, mode=AnalysisMode.CUSTOM)
    command = [str(args.exe.resolve()), "--data-dir", str(workspace), "--drain-queue"]
    child = subprocess.Popen(
        command, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = queue.list_jobs()[0]
            if job.status == "running":
                break
            if child.poll() is not None:
                raise AssertionError(
                    "Executor exited before the active job was observed"
                )
            time.sleep(0.01)
        assert job.status == "running"
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(child.pid), "/T", "/F"],
                check=True,
                capture_output=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            child.kill()
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
    interrupted = queue.list_jobs()[0]
    assert interrupted.status == "running", interrupted
    expected_result_id = interrupted.evidence_id
    subprocess.run(
        command,
        timeout=120,
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    job = queue.list_jobs()[0]
    assert job.status == "completed" and job.evidence_id == expected_result_id, job
    repository = AnalysisRepository(workspace / "forensics.sqlite3")
    result = repository.load(job.evidence_id)
    assert result and result.evidence.sha256 == digest.hexdigest()
    with specimen.open("rb") as source:
        assert hashlib.file_digest(source, "sha256").hexdigest() == digest.hexdigest()
    assert len(repository.list_evidence_ids()) == 1
    summary = {
        "completed_utc": datetime.now(UTC).isoformat(),
        "exe_sha256": hashlib.sha256(args.exe.read_bytes()).hexdigest(),
        "interrupted_status": interrupted.status,
        "recovered_status": job.status,
        "same_result_id": True,
        "source_bytes": specimen.stat().st_size,
        "original_unchanged": True,
        "saved_results": 1,
        "all_checks_passed": True,
    }
    (root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
