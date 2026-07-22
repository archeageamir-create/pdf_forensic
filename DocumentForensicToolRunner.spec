# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project_root = Path(SPECPATH)

a = Analysis(
    [str(project_root / "app" / "tool_runner.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(str(project_root / "app" / "resources" / "tools"), "app/resources/tools")],
    hiddenimports=[
        "binascii", "collections", "configparser", "fnmatch", "glob", "hashlib",
        "io", "json", "math", "msvcrt", "operator", "optparse", "re", "struct",
        "textwrap", "time", "traceback", "urllib.request", "xml.dom.minidom",
        "zipfile", "zlib",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DocumentForensicToolRunner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
