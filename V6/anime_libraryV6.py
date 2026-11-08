"""
AniLib V6 — Smart Thin Launcher & OTA Hot-Loader
Loads the newest OTA-updated AniLibV6 package (~35 KB) from ~/.anime_library/updates/current
if available and newer than the bundled version, falling back to the local/frozen package.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

BUNDLED_VERSION = "6.0.0"


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
    """Prepend ~/.anime_library/updates/current to sys.path if its version > bundled version."""
    try:
        local_init = root / "AniLibV6" / "__init__.py"
        local_ver = BUNDLED_VERSION
        if local_init.is_file():
            m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', local_init.read_text(encoding="utf-8"))
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
                return
    except Exception:
        pass


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_activate_ota_if_newer(ROOT)

from AniLibV6.main import main  # noqa: E402

if __name__ == "__main__":
    main()
