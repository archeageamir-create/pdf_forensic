"""Long-running local queue/watch test. Uses synthetic files only.

Produces a JSON evidence log: ingestion latency, restored queue state, result
integrity and resident memory. Stops and restarts the daemon periodically.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import wave
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image
from app.core.config import AppConfig
from app.core.daemon import QueueDaemon
from app.core.job_queue import JobQueue
from app.core.service import ForensicsService
from app.core.settings import SettingsStore
from app.models import AnalysisMode
from tests.helpers import write_test_pptx
from tests.test_universal import write_word


def memory_bytes(pid=None):
    if os.name != "nt":
        return None
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "PeakWorkingSetSize",
                "WorkingSetSize",
                "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage",
                "PagefileUsage",
                "PeakPagefileUsage",
            )
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    query = ctypes.WinDLL("psapi").GetProcessMemoryInfo
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    query.restype = wintypes.BOOL
    handle = (
        kernel.OpenProcess(0x410, False, pid) if pid else kernel.GetCurrentProcess()
    )
    try:
        if not handle or not query(handle, ctypes.byref(counters), counters.cb):
            return None
        return counters.WorkingSetSize
    finally:
        if pid and handle:
            kernel.CloseHandle(handle)


class PackagedDaemon:
    def __init__(self, executable, workspace, inbox, gui=False):
        command = [str(executable.resolve()), "--data-dir", str(workspace)]
        if not gui:
            command += ["--watch", str(inbox), "--mode", "quick"]
        startup = None
        if gui and os.name == "nt":
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
        self.process = subprocess.Popen(
            command,
            startupinfo=startup,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def stop(self):
        if self.process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                self.process.terminate()

    def join(self, timeout=None):
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass

    def is_alive(self):
        return self.process.poll() is None


def create_specimen(inbox, index):
    kind = index % 7
    suffix = (".jpg", ".docx", ".pptx", ".wav", ".zip", ".bin", ".jpg")[kind]
    path = inbox / f"СИНТЕТИКА-{index:04d}{suffix}"
    staging = path.with_suffix(".part")
    if kind == 0:
        exif = Image.Exif()
        exif[271] = "Synthetic Test Camera"
        exif[305] = f"Soak test {index}"
        Image.new("RGB", (80 + index % 20, 60), "#447799").save(
            staging, format="JPEG", exif=exif
        )
    elif kind == 1:
        write_word(staging)
    elif kind == 2:
        write_test_pptx(staging)
    elif kind == 3:
        with wave.open(str(staging), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(8000)
            stream.writeframes(b"\0\0" * 800)
    elif kind == 4:
        with zipfile.ZipFile(staging, "w") as archive:
            archive.writestr("test.txt", "Синтетические данные")
    elif kind == 5:
        staging.write_bytes(b"synthetic unsupported data " + str(index).encode())
    else:
        staging.write_bytes(b"\xff\xd8\xffBROKEN_SYNTHETIC_JPEG")
    staging.replace(path)
    return path, kind == 6


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=5)
    parser.add_argument("--interval", type=float, default=20)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Exercise the packaged GUI event loop with its saved folder watch",
    )
    parser.add_argument(
        "--executable",
        type=Path,
        help="Test the built windowed EXE instead of source daemon",
    )
    args = parser.parse_args()
    root = args.output.resolve()
    inbox, workspace = root / "inbox", root / "workspace"
    inbox.mkdir(parents=True, exist_ok=True)
    config = replace(
        AppConfig.default(),
        data_dir=workspace,
        database_path=workspace / "forensics.sqlite3",
        cases_dir=workspace / "cases",
        reports_dir=workspace / "reports",
        settings_path=None,
        tool_timeout_seconds=20,
        max_analysis_seconds=60,
    )
    service = ForensicsService(config)
    if args.executable:
        SettingsStore(workspace / "settings.json").save(config)
    queue = JobQueue(workspace / "queue.sqlite3")
    queue.save_watch(inbox, None, AnalysisMode.QUICK)
    results = []
    failures = []
    received_lock = threading.Lock()

    def receive(result):
        with received_lock:
            results.append(result.evidence.id)

    def start():
        if args.executable:
            daemon = PackagedDaemon(args.executable, workspace, inbox, gui=args.gui)
            return daemon, daemon
        daemon = QueueDaemon(service, queue, on_result=receive)
        thread = threading.Thread(
            target=daemon.run, kwargs={"poll_seconds": 0.3}, daemon=True
        )
        thread.start()
        return daemon, thread

    daemon, thread = start()
    start_time = time.monotonic()
    deadline = start_time + args.minutes * 60
    index = 0
    restarts = 0
    samples = []
    log = root / "events.jsonl"
    try:
        while time.monotonic() < deadline:
            index += 1
            iteration = time.monotonic()
            path, broken = create_specimen(inbox, index)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            job = None
            while time.monotonic() - iteration < 65:
                job = next(
                    (j for j in queue.list_jobs(2000) if j.path == str(path)), None
                )
                if job and job.status in {"completed", "partial", "failed"}:
                    break
                time.sleep(0.3)
            result = (
                service.repository.load(job.evidence_id)
                if job and job.evidence_id
                else None
            )
            okay = bool(
                result
                and result.evidence.sha256 == digest
                and hashlib.sha256(path.read_bytes()).hexdigest() == digest
                and (bool(result.errors) if broken else not result.errors)
            )
            event = {
                "index": index,
                "utc": datetime.now(UTC).isoformat(),
                "elapsed_seconds": round(time.monotonic() - start_time, 2),
                "ingestion_seconds": round(time.monotonic() - iteration, 2),
                "okay": okay,
                "path": str(path),
                "status": job.status if job else "not_enqueued",
                "error": job.error if job else "",
                "analysis_errors": result.errors if result else [],
                "memory_bytes": memory_bytes(
                    daemon.process.pid if args.executable else None
                ),
            }
            samples.append(event)
            with log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            if not okay:
                failures.append(event)
                print(json.dumps(event, ensure_ascii=False), flush=True)
            if index % 10 == 0:
                print(
                    f"{index} specimens; failures={len(failures)}; elapsed={int(time.monotonic() - start_time)}s",
                    flush=True,
                )
            if index % 30 == 0:
                daemon.stop()
                thread.join(timeout=15)
                if thread.is_alive():
                    failures.append({"error": "daemon did not stop"})
                    break
                before = len(queue.list_jobs(10000))
                daemon, thread = start()
                time.sleep(4)
                if len(queue.list_jobs(10000)) != before:
                    failures.append({"error": "restart duplicated existing files"})
                restarts += 1
            remaining = min(
                args.interval - (time.monotonic() - iteration),
                deadline - time.monotonic(),
            )
            if remaining > 0:
                time.sleep(remaining)
    finally:
        daemon.stop()
        thread.join(timeout=15)
        summary = {
            "duration_seconds": round(time.monotonic() - start_time, 2),
            "files": index,
            "callbacks": None if args.executable else len(results),
            "executable": str(args.executable) if args.executable else None,
            "gui": args.gui,
            "executable_sha256": hashlib.sha256(
                args.executable.read_bytes()
            ).hexdigest()
            if args.executable
            else None,
            "restarts": restarts,
            "failures": failures,
            "queue": queue.counts(),
            "peak_memory_bytes": max(
                (s["memory_bytes"] or 0 for s in samples), default=0
            ),
            "completed": not thread.is_alive(),
        }
        (root / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
