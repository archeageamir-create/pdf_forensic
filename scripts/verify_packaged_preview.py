"""Exercise the actual windowed EXE's CLI and spawned queue worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import wave
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image
from pypdf import PdfWriter
from app.core.database import AnalysisRepository
from app.core.job_queue import JobQueue
from app.models import AnalysisMode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--exe",
        type=Path,
        default=ROOT
        / "dist/DocumentForensicInspectorPreview/DocumentForensicInspectorPreview.exe",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    folder = args.output_dir.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    inbox = folder / "synthetic-evidence"
    inbox.mkdir()
    Image.new("RGB", (64, 48), (58, 72, 100)).save(inbox / "ДЕМО-фото.jpg")
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.add_metadata({"/Author": "Synthetic fixture"})
    writer.write(inbox / "ДЕМО.pdf")
    for extension, member, body in (
        (
            "docx",
            "word/document.xml",
            '<document xmlns="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><body><p/></body></document>',
        ),
        (
            "xlsx",
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Скрытый" state="hidden" sheetId="1"/></sheets></workbook>',
        ),
        ("zip", "note.txt", "Synthetic archive content"),
    ):
        with zipfile.ZipFile(inbox / ("ДЕМО." + extension), "w") as archive:
            if extension in {"docx", "xlsx"}:
                archive.writestr(
                    "[Content_Types].xml",
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
                )
            archive.writestr(member, body)
    with wave.open(str(inbox / "ДЕМО.wav"), "w") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * 800)
    (inbox / "ДЕМО.bin").write_bytes(b"Synthetic unknown evidence\x01\x02")
    (inbox / "ДЕМО-поврежден.jpg").write_bytes(b"\xff\xd8\xffbroken jpeg data")
    files = sorted(inbox.iterdir())
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    workspace = folder / "workspace"
    queue = JobQueue(workspace / "queue.sqlite3")
    for path in files:
        queue.enqueue(path, mode=AnalysisMode.CUSTOM)

    def execute(arguments):
        process = subprocess.run(
            [str(args.exe.resolve()), "--data-dir", str(workspace), *arguments],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=180,
            check=False,
        )
        return process.returncode

    assert execute(["--drain-queue"]) == 0
    jobs = queue.list_jobs()
    assert len(jobs) == len(files)
    repository = AnalysisRepository(workspace / "forensics.sqlite3")
    for job in jobs:
        corrupt = "поврежден" in job.path
        assert job.status == ("partial" if corrupt else "completed"), job
        result = repository.load(job.evidence_id)
        assert result and result.evidence.sha256 == hashes[Path(job.path).name]
        expected_kind = {"jpg": "jpeg", "bin": "binary"}.get(
            Path(job.path).suffix[1:], Path(job.path).suffix[1:]
        )
        assert result.evidence.kind.value == expected_kind, (
            job.path,
            result.evidence.kind,
        )
    # A second executor run must not duplicate committed reports.
    assert execute(["--drain-queue"]) == 0
    assert len(queue.list_jobs()) == len(files)
    report = folder / "windowed-cli-report.json"
    code = execute(
        [
            "--analyze",
            str(inbox / "ДЕМО-фото.jpg"),
            "--mode",
            "quick",
            "--output",
            str(report),
        ]
    )
    assert code in (0, 2) and report.is_file()
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["evidence"]["sha256"] == hashes["ДЕМО-фото.jpg"]
    probe_runs = {}
    for name, required_tool in (("ДЕМО.pdf", "pdfid.py"), ("ДЕМО.wav", "ffprobe")):
        output = folder / (name + "-report.json")
        exit_code = execute(
            ["--analyze", str(inbox / name), "--mode", "quick", "--output", str(output)]
        )
        assert exit_code in (0, 2) and output.is_file()
        payload = json.loads(output.read_text(encoding="utf-8"))
        runs = {run["tool_name"]: run["status"] for run in payload["tool_runs"]}
        if required_tool == "pdfid.py" or shutil.which(required_tool):
            assert runs.get(required_tool) == "completed", runs
        probe_runs[name] = runs
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files} == hashes
    summary = {
        "completed_utc": datetime.now(UTC).isoformat(),
        "exe": str(args.exe.resolve()),
        "exe_sha256": hashlib.sha256(args.exe.read_bytes()).hexdigest(),
        "queued_files": len(files),
        "expected_partial_corrupt_files": 1,
        "windowed_cli_exit_code": code,
        "profile_tool_runs": probe_runs,
        "all_checks_passed": True,
    }
    (folder / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
