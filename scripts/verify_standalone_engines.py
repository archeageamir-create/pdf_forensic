"""Exercise every engine from the actual frozen EXE with a Windows-only PATH."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import wave
import zipfile
from pathlib import Path

from PIL import Image
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_runtime_dependencies import verify_bundle

TOOLS = {"ExifTool", "ffprobe", "qpdf", "pdfcpu", "Poppler", "Java runtime", "JHOVE PDF-hul", "veraPDF", "Apache PDFBox", "pdfid.py", "pdf-parser.py"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(executable: Path, output: Path) -> dict:
    executable = executable.resolve()
    package = executable.parent
    runtime = package / "_internal/app/resources/binaries"
    verify_bundle(runtime)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ)
    windows = Path(environment.get("WINDIR", "C:/Windows"))
    environment["PATH"] = os.pathsep.join(map(str, (windows / "System32", windows)))
    for key in ("JAVA_HOME", "JDK_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "CLASSPATH", "PYTHONPATH", "PDFID_SCRIPT", "PDF_PARSER_SCRIPT"):
        environment.pop(key, None)
    # Also avoid finding a host's cached Java/ExifTool configuration.
    profile = output / "empty-profile"
    profile.mkdir()
    environment.update({"USERPROFILE": str(profile), "HOME": str(profile), "APPDATA": str(profile / "Roaming"), "LOCALAPPDATA": str(profile / "Local")})

    def execute(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(executable), "--data-dir", str(output / "workspace"), *map(str, args)], env=environment, cwd=output,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=240, check=False)

    diagnostics = output / "tools.json"
    process = execute("--check-tools", "--output", diagnostics)
    assert process.returncode == 0 and diagnostics.is_file(), "Bundled tool diagnostic failed"
    tools = json.loads(diagnostics.read_text(encoding="utf-8"))
    assert tools["all_tools_available"] and {t["tool_name"] for t in tools["tools"]} == TOOLS
    for tool in tools["tools"]:
        assert tool["status"] == "completed", tool
        assert Path(tool["command"][0]).resolve().is_relative_to(package), tool

    pdf = output / "Учебный PDF с обновлением.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(300, 200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 20 100 Td (Synthetic portable test) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    xmp = DecodedStreamObject()
    xmp.set_data(b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title><rdf:Alt><rdf:li xml:lang="x-default">Synthetic test</rdf:li></rdf:Alt></dc:title></rdf:Description></rdf:RDF></x:xmpmeta>')
    xmp[NameObject("/Type")] = NameObject("/Metadata")
    xmp[NameObject("/Subtype")] = NameObject("/XML")
    writer.root_object[NameObject("/Metadata")] = writer._add_object(xmp)
    writer.add_metadata({"/Author": "Synthetic test", "/Title": "First title"})
    base_pdf = output / "base.pdf"
    writer.write(base_pdf)
    updated = PdfWriter(base_pdf, incremental=True)
    updated.add_metadata({"/Title": "Updated title"})
    updated.write(pdf)

    photo = output / "Учебное фото.jpg"
    Image.new("RGB", (80, 60), "#486575").save(photo)
    audio = output / "Учебный звук.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\0\0" * 800)
    office = output / "Учебный документ.docx"
    document = Document()
    document.add_paragraph("Учебный файл для проверки автономной программы.")
    document.save(office)
    originals = {p: digest(p) for p in (pdf, photo, audio, office)}
    summaries = {}
    for specimen, mode in ((pdf, "full"), (photo, "quick"), (audio, "quick"), (office, "quick")):
        report = output / (specimen.suffix[1:] + "-report.json")
        process = execute("--analyze", specimen, "--mode", mode, "--output", report)
        assert report.is_file(), (specimen, process.returncode)
        result = json.loads(report.read_text(encoding="utf-8"))
        statuses = {run["tool_name"]: run["status"] for run in result["tool_runs"]}
        assert process.returncode == 0 and not result["incomplete"] and not result["errors"], (specimen.name, process.returncode, statuses, result["errors"])
        assert statuses.get("ExifTool") == "completed", statuses
        if specimen == pdf:
            for prefix in ("qpdf/", "pdfcpu/", "poppler/", "jhove/", "verapdf/", "pdfbox/", "pdfid.py", "pdf-parser"):
                matching = [value for key, value in statuses.items() if key.startswith(prefix)]
                assert matching and all(value == "completed" for value in matching), (prefix, statuses)
            assert any(name.startswith("poppler/render-revision-") for name in statuses), statuses
            renders = result["artifacts"]["revision_renders"]
            assert len(renders) >= 2 and all(group["pages"] for group in renders), renders
            assert all(Path(page["path"]).is_file() for group in renders for page in group["pages"])
        if specimen == audio:
            assert statuses.get("ffprobe") == "completed", statuses
        summaries[specimen.suffix] = statuses
    for extension in ("docx", "html", "zip"):
        report = output / f"export.{extension}"
        specimen, mode = (pdf, "full") if extension == "zip" else (office, "quick")
        assert execute("--analyze", specimen, "--mode", mode, "--output", report).returncode == 0
        assert report.stat().st_size > 100
        if extension == "zip":
            with zipfile.ZipFile(report) as package_report:
                assert any(name.endswith("verapdf-features.xml") for name in package_report.namelist())
    assert all(digest(path) == original for path, original in originals.items())
    verify_bundle(runtime)
    summary = {"all_checks_passed": True, "windows_only_path": True, "empty_user_profile": True,
               "all_engine_executables_inside_package": True, "tools_checked": len(tools["tools"]),
               "runtime_payload_unchanged_after_analysis": True,
               "pdf_full_with_revision_rendering": True, "image_audio_office": True,
               "exports": ["json", "docx", "html", "zip"], "originals_unchanged": True,
               "analysis_tool_statuses": summaries, "executable_sha256": digest(executable)}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.exe, args.output), ensure_ascii=False))
