from __future__ import annotations

import json
from pathlib import Path

from app.adapters.base import (
    AdapterResult,
    CancellationToken,
    CommandRunner,
    ToolAdapter,
)
from app.models import FileKind, Finding, FindingLevel, ToolRunStatus


DEMUXERS = {
    FileKind.MP4: "mov",
    FileKind.MOV: "mov",
    FileKind.MP3: "mp3",
    FileKind.WAV: "wav",
    FileKind.FLAC: "flac",
    FileKind.OGG: "ogg",
    FileKind.MKV: "matroska",
    FileKind.AVI: "avi",
}


class FfprobeAdapter(ToolAdapter):
    def __init__(
        self,
        kind: FileKind,
        command: str = "ffprobe",
        timeout_seconds: int = 120,
        cancellation_token: CancellationToken | None = None,
    ):
        self.kind = kind
        self.command = command
        self.runner = CommandRunner(timeout_seconds, cancellation_token)

    def analyze(self, path: Path) -> AdapterResult:
        demuxer = DEMUXERS[self.kind]
        # Only a detected media container, never a playlist or remote URL.
        command = [
            self.command,
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-f",
            demuxer,
        ]
        if demuxer == "mov":
            command += ["-enable_drefs", "0", "-use_absolute_path", "0"]
        command += ["-show_format", "-show_streams", "-of", "json", str(path.resolve())]
        run = self.runner.run("ffprobe", command, [self.command, "-version"])
        findings = []
        artifacts = {}
        if run.status == ToolRunStatus.COMPLETED:
            try:
                payload = json.loads(run.stdout)
                if (
                    not isinstance(payload, dict)
                    or not isinstance(payload.get("streams", []), list)
                    or not isinstance(payload.get("format", {}), dict)
                ):
                    raise ValueError("Unexpected ffprobe JSON structure")
                artifacts["media_probe"] = payload
                for key, value in payload.get("format", {}).items():
                    if key == "filename":
                        continue
                    if key == "tags" and isinstance(value, dict):
                        for tag, content in value.items():
                            findings.append(
                                Finding(
                                    "Media metadata",
                                    tag,
                                    content,
                                    "ffprobe/format",
                                    location=f"format.tags.{tag}",
                                )
                            )
                    else:
                        findings.append(
                            Finding(
                                "Media container",
                                key,
                                value,
                                "ffprobe/format",
                                location=f"format.{key}",
                            )
                        )
                for stream in payload.get("streams", []):
                    if not isinstance(stream, dict):
                        raise ValueError("Unexpected ffprobe stream")
                    index = stream.get("index", "?")
                    for key, value in stream.items():
                        if key == "tags" and isinstance(value, dict):
                            for tag, content in value.items():
                                findings.append(
                                    Finding(
                                        "Media metadata",
                                        tag,
                                        content,
                                        f"ffprobe/stream {index}",
                                        location=f"streams[{index}].tags.{tag}",
                                    )
                                )
                        else:
                            findings.append(
                                Finding(
                                    "Media streams",
                                    key,
                                    value,
                                    f"ffprobe/stream {index}",
                                    location=f"streams[{index}].{key}",
                                )
                            )
            except (json.JSONDecodeError, ValueError) as exc:
                run.status = ToolRunStatus.FAILED
                run.stderr += f"\nInvalid ffprobe output: {exc}"
                findings.append(
                    Finding(
                        "Tool diagnostics",
                        "ffprobe JSON parse error",
                        str(exc),
                        "ffprobe",
                        FindingLevel.MEDIUM,
                    )
                )
        return AdapterResult(findings=findings, tool_runs=[run], artifacts=artifacts)
