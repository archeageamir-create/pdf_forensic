from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.adapters.base import AdapterResult, CancellationToken, CommandRunner, ToolAdapter
from app.models import Finding, FindingLevel, ToolRunStatus


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
        run = self.runner.run(
            "ExifTool",
            [self.command, "-json", "-G1", "-a", "-s", str(path)],
            [self.command, "-ver"],
        )
        findings: list[Finding] = []
        if run.status == ToolRunStatus.COMPLETED:
            findings.extend(self._parse_json(run.stdout))
        return AdapterResult(findings=findings, tool_runs=[run])

    @staticmethod
    def _parse_json(output: str) -> list[Finding]:
        try:
            documents: Any = json.loads(output)
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
        if not isinstance(documents, list) or not documents or not isinstance(documents[0], dict):
            return []

        findings: list[Finding] = []
        for key, value in documents[0].items():
            if key == "SourceFile":
                continue
            group, _, name = key.partition(":")
            if not name:
                group, name = "Other", group
            if group == "PDF":
                category = "PDF Info"
            elif group.startswith("XMP"):
                category = "XMP"
            else:
                category = "File properties"
            findings.append(
                Finding(
                    category=category,
                    name=name,
                    value=value,
                    source=f"ExifTool/{group}",
                )
            )
        return findings
