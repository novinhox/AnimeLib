"""Build AnimeLibraryV6.exe using PyInstaller (Thin OTA-capable executable).

Usage:
  python V6/build_exe.py
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

V6_DIR = Path(__file__).resolve().parent
ENTRY = V6_DIR / "anime_libraryV6.py"
ICON = V6_DIR / "anime_library.ico"
BUILD_TMP = V6_DIR / "_pyinstaller_build"


def main() -> None:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "AnimeLibraryV6",
        "--distpath",
        str(V6_DIR),
        "--workpath",
        str(BUILD_TMP),
        "--specpath",
        str(BUILD_TMP),
        "--paths",
        str(V6_DIR),
        "--collect-submodules",
        "AniLibV6",
    ]
    if ICON.is_file():
        cmd.extend(["--icon", str(ICON)])
    cmd.append(str(ENTRY))

    print("Building AnimeLibraryV6.exe ...")
    try:
        subprocess.run(cmd, check=True)
        exe_path = V6_DIR / "AnimeLibraryV6.exe"
        if exe_path.is_file():
            mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"\nSUCCESS! Built: {exe_path} ({mb:.1f} MB)")
            print("Note: You only need to build this .exe ONCE! Future updates are delivered via ~84 KB OTA packages.")
    finally:
        shutil.rmtree(BUILD_TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
