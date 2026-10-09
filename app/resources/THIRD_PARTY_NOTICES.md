# Document Forensic Inspector — build inventory

This standalone build bundles Python, Qt, ExifTool (including Perl), qpdf, pdfcpu, Poppler, ffprobe, Java, JHOVE, veraPDF, PDFBox and the repository PDF scripts. No separate runtime installation is needed. Exact engine files and hashes are in binaries/RUNTIME_MANIFEST.json; upstream download hashes are in compliance/runtime-dependencies.lock.json.

The inventory records the actual build environment; build-only packages are labelled separately. Third-party rights and license notices are retained. This distribution is unsigned.

- Bundled exiftool 13.59: Artistic-1.0-Perl OR GPL-1.0-or-later. Upstream: https://downloads.sourceforge.net/project/exiftool/exiftool-13.59_64.zip.
- Bundled ffprobe 8.1.2: GPL-3.0-or-later. Upstream: https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1.2-essentials_build.zip.
- Bundled java 21.0.11+10: GPL-2.0-only WITH Classpath-exception-2.0. Upstream: https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.11%2B10/OpenJDK21U-jre_x64_windows_hotspot_21.0.11_10.zip.
- Bundled jhove 1.34.0: LGPL-2.1-or-later. Upstream: https://software.openpreservation.org/releases/jhove-installer-1.34.jar.
- Bundled pdfbox 3.0.8: Apache-2.0. Upstream: https://archive.apache.org/dist/pdfbox/3.0.8/pdfbox-app-3.0.8.jar.
- Bundled pdfcpu 0.13.0: Apache-2.0. Upstream: https://github.com/pdfcpu/pdfcpu/releases/download/v0.13.0/pdfcpu_0.13.0_Windows_x86_64.zip.
- Bundled poppler 26.02.0: GPL-2.0-or-later. Upstream: https://github.com/oschwartz10612/poppler-windows/releases/download/v26.02.0-0/Release-26.02.0-0.zip.
- Bundled qpdf 12.3.2: Apache-2.0 OR Artistic-2.0. Upstream: https://github.com/qpdf/qpdf/releases/download/v12.3.2/qpdf-12.3.2-msvc64.zip.
- Bundled verapdf 1.30.2: MPL-2.0 OR GPL-3.0-or-later. Upstream: https://software.verapdf.org/releases/1.30/verapdf-greenfield-1.30.2-installer.zip.
- altgraph 0.17.5: MIT. License files: 1.
- asn1crypto 1.5.1: MIT. License files: 1.
- certifi 2026.7.22: MPL-2.0. License files: 1.
- cffi 2.1.1: MIT-0. License files: 1.
- charset-normalizer 3.5.1: MIT. License files: 1.
- colorama 0.4.6: NOASSERTION. License files: 1.
- cryptography 50.0.1: Apache-2.0 OR BSD-3-Clause. License files: 3.
- idna 3.19: BSD-3-Clause. License files: 1.
- iniconfig 2.3.0: MIT. License files: 1.
- lxml 6.1.3: BSD-3-Clause. License files: 2.
- oscrypto 1.3.0: MIT. License files: 1.
- packaging 26.3: Apache-2.0 OR BSD-2-Clause. License files: 3.
- pefile 2024.8.26: MIT. License files: 1.
- pillow 12.3.0: MIT-CMU. License files: 1.
- pip 25.0.1: MIT. License files: 2.
- pluggy 1.6.0: MIT. License files: 1.
- pycparser 3.0: BSD-3-Clause. License files: 1.
- Pygments 2.21.0: BSD-2-Clause. License files: 2.
- pyHanko 0.35.2: MIT. License files: 2.
- pyhanko-certvalidator 0.31.4: MIT. License files: 1.
- pyinstaller 6.22.3: NOASSERTION. License files: 1.
- pyinstaller-hooks-contrib 2026.7: NOASSERTION. License files: 1.
- pypdf 6.18.1: BSD-3-Clause. License files: 1.
- PySide6 6.11.2: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only. License files: 1.
- PySide6_Addons 6.11.2: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only. License files: 1.
- PySide6_Essentials 6.11.2: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only. License files: 1.
- pytest 8.4.2: MIT. License files: 2.
- python-docx 1.2.0: MIT. License files: 1.
- pywin32-ctypes 0.2.3: BSD-3-Clause. License files: 1.
- PyYAML 6.0.3: MIT. License files: 1.
- requests 2.34.2: Apache-2.0. License files: 2.
- ruff 0.16.7: MIT. License files: 1.
- setuptools 84.0.0: MIT. License files: 5.
- shiboken6 6.11.2: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only. License files: 1.
- typing_extensions 4.16.0: PSF-2.0. License files: 1.
- tzdata 2026.4: Apache-2.0. License files: 2.
- tzlocal 5.4.4: MIT. License files: 1.
- uritools 6.1.3: MIT. License files: 1.
- urllib3 2.7.0: MIT. License files: 1.