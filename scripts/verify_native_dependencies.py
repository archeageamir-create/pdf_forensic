"""Check private native tool directories without trusting the host's PATH/CRT."""
from __future__ import annotations

from pathlib import Path

import pefile

WINDOWS_DLLS = frozenset(["advapi32.dll", "bcrypt.dll", "bcryptprimitives.dll", "cabinet.dll", "comctl32.dll", "comdlg32.dll", "crypt32.dll", "cryptbase.dll", "dbghelp.dll", "dnsapi.dll", "dwmapi.dll", "gdi32.dll", "imm32.dll", "iphlpapi.dll", "kernel32.dll", "mpr.dll", "msimg32.dll", "msvcrt.dll", "ncrypt.dll", "netapi32.dll", "normaliz.dll", "ntdll.dll", "ole32.dll", "oleaut32.dll", "powrprof.dll", "propsys.dll", "psapi.dll", "rpcrt4.dll", "secur32.dll", "setupapi.dll", "shell32.dll", "shlwapi.dll", "user32.dll", "userenv.dll", "usp10.dll", "uxtheme.dll", "version.dll", "winhttp.dll", "wininet.dll", "winmm.dll", "winspool.drv", "wintrust.dll", "wldap32.dll", "ws2_32.dll", "wtsapi32.dll", "ucrtbase.dll"])


def imports(path: Path) -> set[str]:
    with pefile.PE(str(path), fast_load=True) as binary:
        binary.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
        ])
        return {item.dll.decode("ascii").lower() for key in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT") for item in getattr(binary, key, [])}


def system_library(name: str) -> bool:
    return name in WINDOWS_DLLS or name.startswith(("api-ms-win-", "ext-ms-win-"))


def closure(folder: Path, roots: list[str]) -> set[str]:
    available = {p.name.lower(): p for p in folder.iterdir() if p.is_file()}
    needed, queue = set(), list(roots)
    while queue:
        name = queue.pop().lower()
        if name in needed or system_library(name):
            continue
        if name not in available:
            raise ValueError(f"Missing private dependency {name} in {folder.name}")
        needed.add(name)
        queue.extend(imports(available[name]))
    return needed


def verify(payload: Path) -> dict:
    groups = {
        "ffmpeg": ["ffprobe.exe"],
        "poppler/bin": [f"{name}.exe" for name in ("pdfinfo", "pdffonts", "pdfimages", "pdfdetach", "pdftotext", "pdftoppm")],
    }
    return {name: sorted(closure(payload / name, roots)) for name, roots in groups.items()}
