"""Exercise the offline download assembler with Windows PowerShell 5.1."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows delivery helper")
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "failure", [None, "missing", "damaged", "existing", "traversal"]
)
def test_download_integrity_and_output_preservation(tmp_path, failure):
    script = tmp_path / "Assemble-Distribution.ps1"
    shutil.copy2(ROOT / "scripts/Assemble-Distribution.ps1", script)
    content = b"synthetic installer bytes - never executed"
    name = "DocumentForensicInspector-Setup-0.5.1.exe"
    part = tmp_path / (name + ".001")
    part.write_bytes(content)
    record = {
        "file": name,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "parts": [
            {
                "file": part.name,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    destination = tmp_path / name
    if failure == "missing":
        part.unlink()
    elif failure == "damaged":
        part.write_bytes(b"x" * len(content))
    elif failure == "existing":
        destination.write_bytes(b"preserve this existing file")
    elif failure == "traversal":
        record["parts"][0]["file"] = "../outside.001"
    (tmp_path / "DOWNLOAD-PARTS.json").write_text(
        json.dumps({"installer": record}), encoding="utf-8"
    )
    shell = (
        Path(os.environ["SystemRoot"])
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    result = subprocess.run(
        [str(shell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True,
        check=False,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if failure:
        assert result.returncode != 0
        expected_error = {
            "missing": b"Missing download",
            "damaged": b"Download is incomplete or damaged",
            "existing": b"An existing output file has a different checksum",
            "traversal": b"Invalid part name",
        }
        assert expected_error[failure] in result.stderr, result.stderr
        if failure == "existing":
            assert destination.read_bytes() == b"preserve this existing file"
        else:
            assert not destination.exists()
    else:
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        assert destination.read_bytes() == content
    assert not list(tmp_path.glob("*.assembling"))
