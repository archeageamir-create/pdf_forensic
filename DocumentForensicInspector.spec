# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project_root = Path(SPECPATH)
tool_runner = project_root / "build-tools" / "DocumentForensicToolRunner.exe"
if not tool_runner.is_file():
    raise FileNotFoundError("Build the bundled tool runner before the main application")

exiftool_dir = Path.home() / "AppData" / "Local" / "Programs" / "ExifTool"
qpdf_root = Path("C:/Program Files/qpdf 12.3.2")
pdfcpu_dir = project_root / "app" / "resources" / "binaries" / "pdfcpu"
pdfcpu_license = project_root / "app" / "resources" / "licenses" / "pdfcpu" / "LICENSE.txt"
extended_binary_dirs = ("java", "jhove", "verapdf", "pdfbox")
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
]
if (exiftool_dir / "ExifTool.exe").is_file():
    datas.append((str(exiftool_dir), "app/resources/binaries"))
if (qpdf_root / "bin" / "qpdf.exe").is_file():
    for filename in (
        "qpdf.exe", "qpdf30.dll", "msvcp140.dll", "vcruntime140.dll",
        "vcruntime140_1.dll",
    ):
        source = qpdf_root / "bin" / filename
        if source.is_file():
            datas.append((str(source), "app/resources/binaries/qpdf"))
    qpdf_license = qpdf_root / "share" / "doc" / "qpdf" / "manual-html" / "license.html"
    if qpdf_license.is_file():
        datas.append((str(qpdf_license), "app/resources/licenses/qpdf"))
if (pdfcpu_dir / "pdfcpu.exe").is_file():
    datas.append((str(pdfcpu_dir), "app/resources/binaries/pdfcpu"))
    if pdfcpu_license.is_file():
        datas.append((str(pdfcpu_license), "app/resources/licenses/pdfcpu"))
poppler_dir = project_root / "app" / "resources" / "binaries" / "poppler"
for filename in (
    "pdfinfo.exe", "pdffonts.exe", "pdfimages.exe", "pdfdetach.exe",
    "pdftotext.exe", "pdftoppm.exe", "deflate.dll", "freetype.dll",
    "jpeg8.dll", "lcms2.dll", "Lerc.dll", "libcrypto-3-x64.dll",
    "libcurl.dll", "liblzma.dll", "libpng16.dll", "libssh2.dll",
    "openjp2.dll", "poppler.dll", "tiff.dll", "zlib.dll", "zstd.dll",
):
    source = poppler_dir / "bin" / filename
    if source.is_file():
        datas.append((str(source), "app/resources/binaries/poppler/bin"))
if (poppler_dir / "share").is_dir():
    datas.append((str(poppler_dir / "share"), "app/resources/binaries/poppler/share"))
for directory_name in extended_binary_dirs:
    directory = project_root / "app" / "resources" / "binaries" / directory_name
    if directory.is_dir():
        datas.append((str(directory), f"app/resources/binaries/{directory_name}"))
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
