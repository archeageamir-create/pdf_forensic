"""Check archive hashes, relocate the EXE and run the complete package without host-installed CLI tools."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_standalone_engines import verify as verify_engines
from scripts.prepare_runtime_dependencies import verify_bundle
from app.core.database import AnalysisRepository
from app.core.job_queue import JobQueue
from app.models import AnalysisMode


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--archive",
        type=Path,
        default=ROOT / "dist/DocumentForensicInspectorPreview-Windows.zip",
    )
    parser.add_argument("--files", type=int, default=154)
    args = parser.parse_args()
    if args.files < 2 or args.files > 2000:
        parser.error("--files must be between 2 and 2000")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    extraction = root / "Перенесённая программа"
    extraction.mkdir()
    with zipfile.ZipFile(args.archive) as archive:
        for item in archive.infolist():
            target = (extraction / item.filename).resolve()
            if not target.is_relative_to(extraction):
                raise ValueError(f"Unsafe archive member: {item.filename}")
        assert archive.testzip() is None
        archive.extractall(extraction)
    app = extraction / "DocumentForensicInspectorPreview"
    manifest = json.loads((app / "PREVIEW_MANIFEST.json").read_text(encoding="utf-8"))
    for item in manifest["files"]:
        path = (app / item["path"]).resolve()
        assert path.is_relative_to(app.resolve())
        assert path.stat().st_size == item["size"] and digest(path) == item["sha256"], (
            path
        )
    assert manifest.get("standalone") is True
    verify_bundle(app / "_internal/app/resources/binaries")
    executable = app / "DocumentForensicInspectorPreview.exe"
    assert digest(executable) == manifest["executable_sha256"]
    helper = runpy.run_path(str(ROOT / "scripts/soak-queue.py"))
    inbox, workspace = root / "inbox", root / "workspace"
    inbox.mkdir()
    specimens = [helper["create_specimen"](inbox, i) for i in range(args.files)]
    hashes = {str(path): digest(path) for path, _ in specimens}
    queue = JobQueue(workspace / "queue.sqlite3")
    half = len(specimens) // 2
    for path, _ in specimens[:half]:
        queue.enqueue(path, mode=AnalysisMode.CUSTOM)
    # A fresh machine must run the built-in profiles without Python or tool PATHs.
    # This changes only this test process and the child that it launches.
    if os.name == "nt":
        windows = Path(os.environ["WINDIR"])
        os.environ["PATH"] = os.pathsep.join(map(str, (windows / "System32", windows)))
    os.environ.pop("QT_QPA_PLATFORM", None)
    daemon = helper["PackagedDaemon"](executable, workspace, inbox, gui=True)
    started = time.monotonic()
    second_batch_added = False
    events = []
    previous_done = -1
    try:
        while time.monotonic() - started < 600:
            assert daemon.is_alive(), "GUI process exited during the burst"
            jobs = queue.list_jobs(5000)
            done = sum(j.status in {"completed", "partial", "failed"} for j in jobs)
            if done >= 1 and not second_batch_added:
                for path, _ in specimens[half:]:
                    queue.enqueue(path, mode=AnalysisMode.CUSTOM)
                second_batch_added = True
            if done != previous_done:
                events.append(
                    {
                        "done": done,
                        "elapsed_seconds": round(time.monotonic() - started, 2),
                        "memory_bytes": helper["memory_bytes"](daemon.process.pid),
                    }
                )
                previous_done = done
                if done % 25 == 0:
                    print(
                        f"Relocated GUI: {done}/{len(specimens)} completed", flush=True
                    )
            if done == len(specimens):
                break
            time.sleep(0.25)
        assert done == len(specimens) and second_batch_added, queue.counts()
        repository = AnalysisRepository(workspace / "forensics.sqlite3")
        jobs_by_path = {j.path: j for j in queue.list_jobs(5000)}
        assert len(jobs_by_path) == len(specimens)
        for path, broken in specimens:
            job = jobs_by_path[str(path)]
            assert job.status == ("partial" if broken else "completed"), job
            result = repository.load(job.evidence_id)
            assert result and result.evidence.sha256 == hashes[str(path)]
            assert digest(path) == hashes[str(path)]
            assert bool(result.errors) == broken
        assert len(repository.list_evidence_ids()) == len(specimens)
        burst_seconds = round(time.monotonic() - started, 2)
    finally:
        daemon.stop()
        daemon.join(timeout=15)
        assert not daemon.is_alive(), "Owned GUI did not stop"
    engines = verify_engines(executable, root / "standalone-engines")
    summary = {
        "completed_utc": datetime.now(UTC).isoformat(),
        "archive_sha256": digest(args.archive),
        "exe_sha256": digest(executable),
        "archive_entries_verified": len(manifest["files"]),
        "native_gui": True,
        "clean_system_path": os.name == "nt",
        "files": len(specimens),
        "expected_partial_corrupt_files": sum(broken for _, broken in specimens),
        "added_during_processing": second_batch_added,
        "burst_seconds": burst_seconds,
        "peak_parent_memory_bytes": max(
            (e["memory_bytes"] or 0 for e in events), default=0
        ),
        "standalone_engines": engines,
        "all_checks_passed": True,
    }
    (root / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
    (root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
