# Standalone onedir preview: Python, Qt and every supported external engine.
from pathlib import Path
import sys
from PyInstaller.building.datastruct import Tree

project_root = Path(SPECPATH)
sys.path.insert(0, str(project_root))
from scripts.prepare_runtime_dependencies import verify_bundle
verify_bundle()
resources = project_root / "build" / "release-resources"
tool_runner = project_root / "build-tools" / "DocumentForensicToolRunner.exe"
if not tool_runner.is_file() or not (resources / "BUILD_INVENTORY.json").is_file():
    raise FileNotFoundError("Run build.ps1 to prepare the runner and build inventory")
datas = [
    (str(project_root / "app/resources/tools"), "app/resources/tools"),
    (str(project_root / "app/resources/icons"), "app/resources/icons"),
    (str(project_root / "app/resources/AUTHORSHIP.txt"), "app/resources"),
    (str(resources), "app/resources"),
    (str(tool_runner), "app/resources/bin"),
    (str(project_root / "LICENSE"), "app/resources/compliance"),
    (str(project_root / "NOTICE"), "app/resources/compliance"),
    (str(project_root / "SOURCE_OFFER.md"), "app/resources/compliance"),
    (str(project_root / "compliance/runtime-dependencies.lock.json"), "app/resources/compliance"),
    (str(project_root / "docs/LGPL_COMPLIANCE.md"), "app/resources/compliance"),
    (str(project_root / "docs/release"), "docs/release"),
    (str(project_root / "installer/USER_AGREEMENT_RU.txt"), "app/resources/compliance"),
    (str(project_root / "compliance/THIRD_PARTY_SOURCES.json"), "app/resources/compliance"),
    (str(project_root / "compliance/SOURCE_DELIVERY.json"), "app/resources/compliance"),
    (str(project_root / "docs/DEPENDENCY_SOURCES.md"), "app/resources/compliance"),
    (str(project_root / "app/resources/branding"), "app/resources/branding"),
    (str(project_root / "docs/RESEARCH_ASSISTANT_KZ.md"), "."),
    (str(project_root / "docs/user-guide/DocumentForensicInspector-User-Guide-RU.pdf"), "docs/user-guide"),
    (str(project_root / "docs/user-guide/examples"), "docs/user-guide/examples"),
]
a = Analysis([str(project_root / "app/main.py")], pathex=[str(project_root)], binaries=[], datas=datas, hiddenimports=["pyhanko_certvalidator"], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["pytest"], noarchive=False)
# This Widgets application renders PDF pages through Poppler. Qt's PDF image
# plugin and virtual keyboard are unused and pull GPL-only modules into the
# generic QtGui hook. Keep the normal Windows input/accessibility support.
unused_qt = {
    "qpdf.dll", "qtvirtualkeyboardplugin.dll", "Qt6Pdf.dll",
    "Qt6VirtualKeyboard.dll", "Qt6Quick.dll", "Qt6Qml.dll",
    "Qt6QmlMeta.dll", "Qt6QmlModels.dll", "Qt6QmlWorkerScript.dll",
}
a.binaries = [item for item in a.binaries if Path(item[0]).name not in unused_qt]
# Preserve the upstream tool directories byte-for-byte. Their private DLLs
# must not be analysed as Qt's dependencies or copied into the shared DLL root.
a.datas += Tree(str(project_root / "app/resources/binaries"), prefix="app/resources/binaries", typecode="DATA")
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="DocumentForensicInspector", debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False, icon=str(project_root / "app/resources/icons/anse.ico"), version=str(project_root / "app/resources/version_info.txt"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="DocumentForensicInspector")
