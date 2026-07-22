from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from app.core.formats import detect_file_kind
from app.core.hashing import calculate_hashes, sha256_file
from app.core.workspace import EvidenceWorkspace
from app.models import FileKind
from tests.helpers import write_minimal_pdf


class IntegrityTests(unittest.TestCase):
    def test_streaming_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "данные.bin"
            data = (b"abc123" * 300_000) + b"tail"
            path.write_bytes(data)
            hashes = calculate_hashes(path, chunk_size=7777)
            self.assertEqual(hashes["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(hashes["sha1"], hashlib.sha1(data).hexdigest())
            self.assertEqual(hashes["md5"], hashlib.md5(data).hexdigest())

    def test_workspace_copies_without_touching_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "оригинал.pdf"
            original = write_minimal_pdf(source)
            workspace = EvidenceWorkspace(root / "cases")
            evidence = workspace.prepare(source)

            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(Path(evidence.working_copy_path).read_bytes(), original)
            self.assertEqual(evidence.sha256, sha256_file(source))
            self.assertEqual(evidence.working_copy_sha256, evidence.sha256)
            self.assertTrue(workspace.verify(evidence))
            self.assertEqual(evidence.kind, FileKind.PDF)

    def test_format_is_detected_by_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "misleading.bin"
            write_minimal_pdf(path)
            self.assertEqual(detect_file_kind(path), FileKind.PDF)


if __name__ == "__main__":
    unittest.main()

