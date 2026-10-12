"""Generate real synthetic containers and verify them through the built EXE."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image
from PIL.TiffImagePlugin import IFDRational
from docx import Document
from app.core.config import AppConfig
from app.core.job_queue import JobQueue
from app.core.service import ForensicsService
from app.core.settings import SettingsStore
from app.models import AnalysisMode
from tests.helpers import write_minimal_pdf, write_test_pptx


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
    inbox = root / "fixtures"
    inbox.mkdir()
    expected = {}

    def specimen(name, kind):
        path = inbox / ("СИНТЕТИКА-" + name)
        expected[str(path)] = kind
        return path

    exif = Image.Exif()
    exif[271] = "Synthetic Camera"
    exif[272] = "Model Test"
    exif[305] = "Forensic matrix fixture"
    exif[34665] = {
        36867: "2026:02:03 12:34:56",
        33434: IFDRational(1, 125),
        37386: IFDRational(35, 1),
    }
    exif[34853] = {
        1: "N",
        2: (IFDRational(51), IFDRational(10), IFDRational(20)),
        3: "E",
        4: (IFDRational(71), IFDRational(20), IFDRational(30)),
    }
    picture = Image.new("RGB", (320, 200), "#4C7091")
    for extension, kind, format_name in (
        ("jpg", "jpeg", "JPEG"),
        ("png", "png", "PNG"),
        ("tif", "tiff", "TIFF"),
        ("webp", "webp", "WEBP"),
        ("gif", "gif", "GIF"),
        ("bmp", "bmp", "BMP"),
    ):
        options = {"exif": exif} if kind == "jpeg" else {}
        picture.save(
            specimen("image." + extension, kind), format=format_name, **options
        )
    mislabeled = specimen("renamed-photo.pdf", "jpeg")
    shutil.copyfile(inbox / "СИНТЕТИКА-image.jpg", mislabeled)
    write_minimal_pdf(specimen("document.pdf", "pdf"))
    write_test_pptx(specimen("slides.pptx", "pptx"))
    document = Document()
    document.core_properties.author = "Синтетический автор"
    document.add_paragraph("Синтетический документ для проверки формата.")
    document.save(specimen("document.docx", "docx"))
    with zipfile.ZipFile(
        specimen("book.xlsx", "xlsx"), "w", zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Visible" state="visible" sheetId="1"/><sheet name="Hidden" state="hidden" sheetId="2"/></sheets></workbook>',
        )
    with zipfile.ZipFile(
        specimen("archive.zip", "zip"), "w", zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr("синтетика.txt", "Содержимое не распаковывается анализатором.")
    specimen("unknown.txt", "binary").write_text(
        "Обычный синтетический текст.", encoding="utf-8"
    )
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to generate the media matrix")
    for extension, kind, media, codec in (
        ("mp4", "mp4", "video", "mpeg4"),
        ("mov", "mov", "video", "mpeg4"),
        ("mkv", "mkv", "video", "ffv1"),
        ("avi", "avi", "video", "ffv1"),
        ("webm", "mkv", "video", "libvpx-vp9"),
        ("mp3", "mp3", "audio", "libmp3lame"),
        ("wav", "wav", "audio", "pcm_s16le"),
        ("flac", "flac", "audio", "flac"),
        ("ogg", "ogg", "audio", "libvorbis"),
        ("m4a", "mp4", "audio", "aac"),
    ):
        path = specimen("media." + extension, kind)
        command = [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x96:r=5:d=0.4"
            if media == "video"
            else "sine=frequency=440:duration=0.4",
            "-c:v" if media == "video" else "-c:a",
            codec,
            "-metadata",
            "title=Synthetic fixture",
            "-metadata",
            "creation_time=2026-02-03T12:34:56Z",
            str(path),
        ]
        subprocess.run(
            command,
            check=True,
            timeout=30,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    hashes = {
        name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in expected
    }
    workspace = root / "workspace"
    config = replace(
        AppConfig.default(),
        data_dir=workspace,
        database_path=workspace / "forensics.sqlite3",
        cases_dir=workspace / "cases",
        reports_dir=workspace / "reports",
        settings_path=workspace / "settings.json",
        tool_timeout_seconds=30,
        max_analysis_seconds=90,
    )
    SettingsStore(config.settings_path).save(config)
    service = ForensicsService(config)
    queue = JobQueue(workspace / "queue.sqlite3")
    for name in expected:
        queue.enqueue(Path(name), mode=AnalysisMode.QUICK)
    subprocess.run(
        [str(args.exe.resolve()), "--data-dir", str(workspace), "--drain-queue"],
        check=True,
        timeout=300,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    rows = []
    for job in queue.list_jobs():
        result = service.repository.load(job.evidence_id)
        assert result is not None and not result.errors, job
        assert result.evidence.kind.value == expected[job.path], (
            job,
            result.evidence.kind,
        )
        assert result.evidence.sha256 == hashes[job.path]
        assert (
            hashlib.sha256(Path(job.path).read_bytes()).hexdigest() == hashes[job.path]
        )
        assert job.status == "completed", (
            job,
            [(r.tool_name, r.status, r.stderr) for r in result.tool_runs],
        )
        assert not {event["name"] for event in result.artifacts["timeline"]} & {
            "ExposureTime",
            "TotalTime",
            "TotalEditTime",
            "LinksUpToDate",
            "LastModifiedBy",
            "duration_time",
        }
        assert all(
            event.get("timestamp") is None
            for event in result.artifacts["timeline"]
            if not event.get("timezone_present")
        )
        for run in result.tool_runs:
            if run.tool_name == "ExifTool":
                assert "FileName encoding must be specified" not in run.stdout
        directories = [
            finding for finding in result.findings if finding.name == "Directory"
        ]
        assert (
            directories
            and directories[0].value
            == Path(result.evidence.working_copy_path).parent.as_posix()
        )
        if "media." in job.path:
            assert result.artifacts.get("media_probe", {}).get("streams"), job.path
        if job.path == str(mislabeled):
            assert any(
                f.name == "Extension matches signature" and f.value is False
                for f in result.findings
            )
        if job.path.endswith("image.jpg"):
            assert any(f.category == "GPS" for f in result.findings)
            assert any(
                f.name == "ExposureTime"
                and isinstance(f.value, dict)
                and f.value.get("denominator") == 125
                for f in result.findings
            )
            assert Path(result.artifacts["image_preview_path"]).is_file()
        rows.append(
            {
                "file": Path(job.path).name,
                "kind": result.evidence.kind.value,
                "findings": len(result.findings),
                "tools": {r.tool_name: r.status.value for r in result.tool_runs},
                "status": job.status,
            }
        )
    assert len(rows) == len(expected)
    summary = {
        "completed_utc": datetime.now(UTC).isoformat(),
        "exe_sha256": hashlib.sha256(args.exe.read_bytes()).hexdigest(),
        "files": len(rows),
        "all_checks_passed": True,
        "results": rows,
    }
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps({key: value for key, value in summary.items() if key != "results"})
    )


if __name__ == "__main__":
    main()
