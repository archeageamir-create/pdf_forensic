"""Compare a candidate ffprobe with a reference on generated media containers."""
from __future__ import annotations

import argparse
import json
import struct
import subprocess
import zlib
from pathlib import Path


def compressed_mov(data: bytes) -> bytes:
    """Replace a trailing moov atom with the legacy QuickTime zlib form."""
    output, position = bytearray(), 0
    while position < len(data):
        size, kind = struct.unpack(">I4s", data[position:position + 8])
        if size < 8 or position + size > len(data):
            raise ValueError("Invalid fixture atom")
        box = data[position:position + size]
        if kind == b"moov":
            if position + size != len(data):
                raise ValueError("Fixture moov must be last to preserve media offsets")
            compressed = zlib.compress(box)
            dcom = struct.pack(">I4s4s", 12, b"dcom", b"zlib")
            cmvd = struct.pack(">I4sI", len(compressed) + 12, b"cmvd", len(box)) + compressed
            cmov = struct.pack(">I4s", 8 + len(dcom + cmvd), b"cmov") + dcom + cmvd
            box = struct.pack(">I4s", 8 + len(cmov), b"moov") + cmov
        output.extend(box)
        position += size
    return bytes(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generator", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    fixtures = []
    for kind, settings, source in (
        ("audio", [("wav", "pcm_s16le"), ("mp3", "libmp3lame"), ("flac", "flac"), ("ogg", "libvorbis"), ("m4a", "aac"), ("opus", "libopus")], "sine=frequency=440:duration=1"),
        ("video", [("mp4", "libx264"), ("webm", "libvpx-vp9"), ("avi", "mpeg4"), ("mkv", "ffv1"), ("mov", "qtrle")], "testsrc=size=160x120:rate=10:duration=1"),
    ):
        for extension, codec in settings:
            target = args.output / f"{kind}.{extension}"
            subprocess.run([str(args.generator.resolve()), "-v", "error", "-f", "lavfi", "-i", source, "-metadata", "title=ANSE Test", "-c:a" if kind == "audio" else "-c:v", codec, str(target.resolve())], check=True, timeout=60)
            fixtures.append(target)
    target = args.output / "video-compressed.mov"
    target.write_bytes(compressed_mov((args.output / "video.mov").read_bytes()))
    fixtures.append(target)
    results = []
    for file in fixtures:
        values = []
        for exe in (args.reference, args.candidate):
            run = subprocess.run([str(exe.resolve()), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(file.resolve())], check=True, capture_output=True, timeout=30)
            values.append(json.loads(run.stdout))
        identical = values[0] == values[1]
        results.append({"file": file.name, "identical": identical})
        if not identical:
            (args.output / (file.name + ".diff.json")).write_text(json.dumps(values, indent=2), encoding="utf-8")
    (args.output / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    if not all(item["identical"] for item in results):
        raise ValueError("Candidate differs from the reference; inspect diff files")
    print(json.dumps({"formats_verified": len(results), "identical": True}))


if __name__ == "__main__":
    main()
