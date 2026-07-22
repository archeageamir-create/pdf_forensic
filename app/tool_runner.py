from __future__ import annotations

import runpy
import sys
from pathlib import Path


TOOLS = {
    "pdfid": "pdfid.py",
    "pdf-parser": "pdf-parser.py",
}


def _configure_utf8_stdio() -> None:
    """Keep bundled console tools independent from the Windows ANSI code page."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def main() -> int:
    _configure_utf8_stdio()
    if len(sys.argv) < 2 or sys.argv[1] not in TOOLS:
        print("Usage: DocumentForensicToolRunner.exe pdfid|pdf-parser [arguments]", file=sys.stderr)
        return 64
    tool = sys.argv[1]
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    script = root / "app" / "resources" / "tools" / TOOLS[tool]
    if not script.is_file():
        print(f"Bundled script not found: {script}", file=sys.stderr)
        return 66
    sys.argv = [str(script), *sys.argv[2:]]
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
