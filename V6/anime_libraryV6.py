"""
AniLib V6 — Smart Thin Launcher & OTA Hot-Loader
Loads the newest OTA-updated AniLibV6 package (~84 KB) from ~/.anime_library/updates/current
if available and newer than the bundled version, falling back to the local/frozen package.
Works identically in both Python source mode and compiled PyInstaller .exe mode.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import sys

BUNDLED_VERSION = "6.0.0"


class _OtaFinder:
    """MetaPathFinder that intercepts AniLibV6 imports so PyInstaller .exe loads OTA .py files first."""

    def __init__(self, ota_root: Path) -> None:
        self.ota_root = ota_root

    def find_spec(self, fullname: str, path=None, target=None):
        if fullname == "AniLibV6" or fullname.startswith("AniLibV6."):
            rel_parts = fullname.split(".")
            pkg_init = self.ota_root.joinpath(*rel_parts, "__init__.py")
            if pkg_init.is_file():
                return importlib.util.spec_from_file_location(
                    fullname,
                    pkg_init,
                    submodule_search_locations=[str(pkg_init.parent)],
                )
            mod_file = self.ota_root.joinpath(*rel_parts).with_suffix(".py")
            if mod_file.is_file():
                return importlib.util.spec_from_file_location(fullname, mod_file)
        return None


def _parse_ver(v: str | None) -> tuple[int, ...]:
    if not v:
        return (0,)
    nums = [int(x) for x in re.findall(r"\d+", str(v))]
    return tuple(nums) if nums else (0,)


def _get_app_dir() -> Path:
    env = os.environ.get("ANIME_LIBRARY_HOME")
    if env:
        return Path(env)
    return Path.home() / ".anime_library"


def _activate_ota_if_newer(root: Path) -> None:
    """Install _OtaFinder at the front of sys.meta_path if an OTA update is newer than bundled."""
    try:
        local_ver = BUNDLED_VERSION
        local_cfg = root / "AniLibV6" / "config.py"
        if local_cfg.is_file():
            m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', local_cfg.read_text(encoding="utf-8"))
            if m:
                local_ver = m.group(1)

        updates_dir = _get_app_dir() / "updates"
        active_meta = updates_dir / "active.json"
        current_dir = updates_dir / "current"
        ota_pkg = current_dir / "AniLibV6" / "__init__.py"

        if active_meta.is_file() and ota_pkg.is_file():
            meta = json.loads(active_meta.read_text(encoding="utf-8"))
            ota_ver = str(meta.get("version") or "")
            if _parse_ver(ota_ver) > _parse_ver(local_ver):
                sys.path.insert(0, str(current_dir))
                sys.meta_path.insert(0, _OtaFinder(current_dir))
    except Exception:
        pass


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_activate_ota_if_newer(ROOT)

from AniLibV6.main import main  # noqa: E402

if __name__ == "__main__":
    main()
