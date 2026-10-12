import hashlib

import pytest

from scripts.verify_source_delivery import verify_file


def test_source_tampering_and_absence_stop_delivery(tmp_path):
    source = tmp_path / "recipe.patch"
    source.write_bytes(b"reviewed patch")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    verify_file(tmp_path, source.name, sha)
    source.write_bytes(b"different patch")
    with pytest.raises(ValueError, match="changed"):
        verify_file(tmp_path, source.name, sha)
    source.unlink()
    with pytest.raises(ValueError, match="Missing"):
        verify_file(tmp_path, source.name, sha)


def test_source_manifest_cannot_escape_delivery_folder(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        verify_file(tmp_path, "../outside", "0" * 64)
