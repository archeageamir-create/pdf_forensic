# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys
from PyInstaller.building.datastruct import Tree

project_root = Path(SPECPATH)
sys.path.insert(0, str(project_root))
from scripts.prepare_runtime_dependencies import verify_bundle
verify_bundle()
tool_runner = project_root / "build-tools" / "DocumentForensicToolRunner.exe"
if not tool_runner.is_file():
    raise FileNotFoundError("Build the bundled tool runner before the main application")

datas = [
    (str(project_root / "app" / "resources" / "tools"), "app/resources/tools"),
    (str(project_root / "app" / "resources" / "THIRD_PARTY_NOTICES.md"), "app/resources"),
    (str(project_root / "app" / "resources" / "SBOM.spdx.json"), "app/resources"),
    (str(project_root / "app" / "resources" / "AUTHORSHIP.txt"), "app/resources"),
    (str(project_root / "LICENSE"), "app/resources/compliance"),
    (str(project_root / "NOTICE"), "app/resources/compliance"),
    (str(project_root / "SOURCE_OFFER.md"), "app/resources/compliance"),
    (str(project_root / "docs" / "LGPL_COMPLIANCE.md"), "app/resources/compliance"),
    (str(project_root / "compliance"), "app/resources/compliance"),
    (str(tool_runner), "app/resources/bin"),
    (str(project_root / "docs/user-guide/DocumentForensicInspector-User-Guide-RU.pdf"), "docs/user-guide"),
    (str(project_root / "docs/user-guide/examples"), "docs/user-guide/examples"),
]
license_root = project_root / "app" / "resources" / "licenses"
if license_root.is_dir():
    datas.append((str(license_root), "app/resources/licenses"))

a = Analysis(
    [str(project_root / "app" / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=["pyhanko_certvalidator"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
a.datas += Tree(str(project_root / "app/resources/binaries"), prefix="app/resources/binaries", typecode="DATA")
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DocumentForensicInspector",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    version=str(project_root / "app" / "resources" / "version_info.txt"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DocumentForensicInspector",
)
