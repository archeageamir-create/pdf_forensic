# LGPL compliance and library replacement

The Windows package uses PySide6, shiboken6 and Qt 6 under the LGPLv3 option.
The application code is separate Python code and loads those libraries
dynamically. The installer uses a PyInstaller **onedir** layout: Qt DLLs,
plugins and PySide `.pyd` modules remain individual files below the installed
`_internal\PySide6` and `_internal` directories.

Recipients may inspect, replace and debug modified LGPL components. The project
does not prohibit reverse engineering for that purpose. Keep a backup and use a
binary-compatible Qt/PySide6 6.11.2 build when replacing files.

## Rebuild with modified Qt/PySide6

1. Install Python 3.12 x64 and create a virtual environment.
2. Obtain the exact corresponding sources listed in
   `compliance/THIRD_PARTY_SOURCES.json`.
3. Build/install the modified PySide6, shiboken6 and Qt libraries into that
   environment.
4. Install this application's source with `python -m pip install -e .`.
5. Install the development requirements, restore the dependency source archives
   and prepared ffprobe build as described in `DEPENDENCY_SOURCES.md`, then run
   `build.ps1`. This also prepares the external tools and their inventory.
6. Replace compatible files in the installed `_internal` directory or reinstall
   the newly built onedir package.

The project's own Apache-2.0 license does not replace or narrow rights granted
by any third-party license. See `SOURCE_OFFER.md`, `THIRD_PARTY_NOTICES.md` and
`SBOM.spdx.json` for the full compliance record.
