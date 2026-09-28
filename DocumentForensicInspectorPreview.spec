# Local development preview: onedir, current Python libraries, optional CLI tools.
from pathlib import Path

project_root = Path(SPECPATH)
resources = project_root / "build" / "preview-resources"
tool_runner = project_root / "build-tools" / "DocumentForensicToolRunner.exe"
if not tool_runner.is_file() or not (resources / "BUILD_INVENTORY.json").is_file():
    raise FileNotFoundError("Run build-preview.ps1 to prepare the runner and build inventory")
datas = [
    (str(project_root / "app/resources/tools"), "app/resources/tools"),
    (str(project_root / "app/resources/AUTHORSHIP.txt"), "app/resources"),
    (str(resources), "app/resources"),
    (str(tool_runner), "app/resources/bin"),
    (str(project_root / "LICENSE"), "app/resources/compliance"),
    (str(project_root / "NOTICE"), "app/resources/compliance"),
    (str(project_root / "docs/LGPL_COMPLIANCE.md"), "app/resources/compliance"),
    (str(project_root / "docs/UNIVERSAL_PREVIEW.md"), "."),
    (str(project_root / "docs/RESEARCH_ASSISTANT_KZ.md"), "."),
]
a = Analysis([str(project_root / "app/main.py")], pathex=[str(project_root)], binaries=[], datas=datas, hiddenimports=["pyhanko_certvalidator"], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["pytest"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="DocumentForensicInspectorPreview", debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False, version=str(project_root / "app/resources/version_info.txt"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="DocumentForensicInspectorPreview")
