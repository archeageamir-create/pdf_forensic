# Component source inventory — 0.5.1

The ANSE ffprobe build uses unmodified FFmpeg commit
38b88335f99e76ed89ff3c93f877fdefce736c13 and replaceable LGPL libraries.
The recipe is `scripts/build_ffprobe.py`. Network support, GPL/nonfree features,
encoders and muxers are disabled. zlib, bzip2 and liblzma support is retained for
compressed containers, including legacy QuickTime headers.

The delivery includes:

- The original eight full source archives: Qt/PySide6, Poppler/data, JHOVE,
  veraPDF applications, OpenJDK and FFmpeg core.
- Exact conda-forge recipes, patches and sources matched to the 15 redistributed
  Poppler libraries by SHA-256. Only the six used tools and their dependency
  closure are shipped; their private Visual C++ runtime DLLs are included.
- Source JARs and build/parent POMs for 70 Java components. Saxon-HE 11.4 and
  12.8 were identified separately from their runtime version and build POMs.
- The exact Temurin build-scripts commit identified in the JRE release record.
- Pillow 12.3.0 source and Windows build scripts, its LGPL FriBiDi loading shim,
  and sources for rebuilding the text-shaping module. GPL libimagequant is
  disabled in the shipped Pillow wheel.
- Additional original QtBase, QtSvg and QtImageFormats license/attribution files.
  The unused QtPdf, QtVirtualKeyboard and related QML plugins are excluded.

`SOURCE_DELIVERY.json` fixes the archive and recipe hashes.
`verify_source_delivery.py` verifies those files and the Poppler binary/source
mapping. The build and release audit fail if this verification fails.
`verify_native_dependencies.py` requires private DLLs locally instead of accepting
a host-installed Visual C++ runtime as proof of a complete package.

The base archives and 0.5.1 supplement are supplied together. See
`docs/DEPENDENCY_SOURCES.md` for extraction, rebuilding and replacement.
The source offer and original third-party notices remain in force.
