from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from app.adapters.base import AdapterResult, CancellationToken, CommandRunner, ToolAdapter
from app.models import Finding, FindingLevel, ToolRunStatus


class _ObjectPairs(list):
    """Distinguish a JSON object's ordered pairs from a JSON array."""


def _json_value(value):
    if isinstance(value, _ObjectPairs):
        if len({key for key, _ in value}) != len(value):
            return {"json_object_pairs": [{"key": key, "value": _json_value(item)} for key, item in value]}
        return {key: _json_value(item) for key, item in value}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


class ExifToolAdapter(ToolAdapter):
    def __init__(
        self,
        command: str = "exiftool",
        timeout_seconds: int = 120,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self.command = command
        self.runner = CommandRunner(timeout_seconds, cancellation_token)

    def analyze(self, path: Path) -> AdapterResult:
        command = [self.command, "-json", "-G1", "-a", "-s"]
        arguments = None
        if os.name == "nt":
            # ExifTool's Windows command-line decoding may lose Unicode names.
            # Feed its documented UTF-8 argfile protocol through stdin instead.
            name = path.resolve().as_posix()
            if "\n" in name or "\r" in name:
                raise ValueError("A filename cannot contain an ExifTool argument separator")
            arguments = name + "\n"
            command += ["-charset", "filename=utf8", "-@", "-"]
        else:
            command.append(str(path.resolve()))
        run = self.runner.run(
            "ExifTool",
            command,
            [self.command, "-ver"],
            input_bytes=arguments.encode("utf-8") if arguments is not None else None,
        )
        if arguments is not None:
            run.parsed_result["stdin_utf8"] = arguments
        findings: list[Finding] = []
        if run.status == ToolRunStatus.COMPLETED:
            findings.extend(self._parse_json(run.stdout))
            if any(f.name in {"ExifTool JSON parse error", "Error"} for f in findings):
                run.status = ToolRunStatus.FAILED
                run.stderr += "\nExifTool returned an error or invalid JSON."
        return AdapterResult(findings=findings, tool_runs=[run])

    @staticmethod
    def _parse_json(output: str) -> list[Finding]:
        try:
            documents: Any = json.loads(output, object_pairs_hook=_ObjectPairs)
        except json.JSONDecodeError:
            return [
                Finding(
                    category="Tool diagnostics",
                    name="ExifTool JSON parse error",
                    value="Output was not valid JSON",
                    source="ExifTool",
                    level=FindingLevel.MEDIUM,
                )
            ]
        if type(documents) is not list or len(documents) != 1 or not isinstance(documents[0], _ObjectPairs):
            return [Finding("Tool diagnostics", "ExifTool JSON parse error", "Unexpected JSON structure", "ExifTool", FindingLevel.MEDIUM)]

        findings: list[Finding] = []
        counts = Counter(key for key, _ in documents[0])
        occurrences = Counter()
        for key, raw_value in documents[0]:
            value = _json_value(raw_value)
            occurrences[key] += 1
            if key == "SourceFile":
                continue
            group, _, name = key.partition(":")
            if not name:
                group, name = "Other", group
            if group == "PDF":
                category = "PDF Info"
            elif group.startswith("XMP"):
                category = "XMP"
            elif group == "GPS" or name.startswith("GPS"):
                category = "GPS"
            elif group in {"IFD0", "IFD1", "ExifIFD", "InteropIFD", "MakerNotes"}:
                category = "EXIF"
            elif group in {"QuickTime", "Matroska", "RIFF", "ID3", "ID3v2_3", "ID3v2_4"}:
                category = "Media metadata"
            else:
                category = "File properties"
            if name in {"Error", "Warning"}:
                category = "Tool diagnostics"
            findings.append(
                Finding(
                    category=category,
                    name=name,
                    value=value,
                    source=f"ExifTool/{group}",
                    level=FindingLevel.MEDIUM if name == "Error" else FindingLevel.LOW if name == "Warning" else FindingLevel.INFO,
                    location=f"{group}:{name}" + (f" (JSON occurrence {occurrences[key]})" if counts[key] > 1 else ""),
                    details="Свойство файловой системы рабочей копии. Даты и путь оригинала указаны отдельно в карточке файла." if group == "System" else "",
                )
            )
        return findings
