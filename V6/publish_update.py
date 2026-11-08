"""One-click OTA Release Publisher for AniLib V6.

Usage:
  python V6/publish_update.py                 # Auto-increments patch version (e.g. 6.0.0 -> 6.0.1), builds zip, commits & pushes to GitHub
  python V6/publish_update.py 6.1.0 "Notes"   # Sets version to 6.1.0, builds zip, commits & pushes to GitHub
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

V6_DIR = Path(__file__).resolve().parent
REPO_ROOT = V6_DIR.parent
CONFIG_PY = V6_DIR / "AniLibV6" / "config.py"
INIT_PY = V6_DIR / "AniLibV6" / "__init__.py"


def get_current_version() -> str:
    txt = CONFIG_PY.read_text(encoding="utf-8")
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', txt)
    return m.group(1) if m else "6.0.0"


def bump_patch(ver: str) -> str:
    parts = [int(x) for x in re.findall(r"\d+", ver)]
    while len(parts) < 3:
        parts.append(0)
    parts[-1] += 1
    return ".".join(str(x) for x in parts)


def set_version(new_ver: str) -> None:
    for f, pat, repl in (
        (CONFIG_PY, r'APP_VERSION\s*=\s*"[^"]+"', f'APP_VERSION = "{new_ver}"'),
        (INIT_PY, r'__version__\s*=\s*"[^"]+"', f'__version__ = "{new_ver}"'),
    ):
        if f.is_file():
            txt = f.read_text(encoding="utf-8")
            txt = re.sub(pat, repl, txt)
            f.write_text(txt, encoding="utf-8")


def main() -> None:
    cur = get_current_version()
    new_ver = sys.argv[1].lstrip("vV") if len(sys.argv) >= 2 else bump_patch(cur)
    notes = sys.argv[2] if len(sys.argv) >= 3 else f"AniLib V6 v{new_ver} OTA Update"

    print(f"Updating version: {cur} -> {new_ver}")
    set_version(new_ver)

    if str(V6_DIR) not in sys.path:
        sys.path.insert(0, str(V6_DIR))
    import importlib
    import AniLibV6.config as cfg
    import AniLibV6.updater as upd
    importlib.reload(cfg)
    importlib.reload(upd)

    zp, mp = upd.build_release_bundle(notes=notes)
    print(f"Built OTA package: {zp.name} ({zp.stat().st_size / 1024:.1f} KB)")
    print(f"Built manifest:    {mp.name}")

    # Git commit & push
    try:
        subprocess.run(["git", "add", "."], cwd=REPO_ROOT, check=True)
        subprocess.run(["git", "commit", "-m", f"Release v{new_ver}: {notes}"], cwd=REPO_ROOT, check=True)
        res = subprocess.run(["git", "push"], cwd=REPO_ROOT, check=False)
        if res.returncode == 0:
            print(f"\nSUCCESS! v{new_ver} is now live on GitHub! Clients will auto-update on launch.")
        else:
            print("\nCommitted locally! Run `git push -u origin main` once your GitHub remote is linked.")
    except Exception as e:
        print(f"\nBundle ready in V6/release/. Git step message: {e}")


if __name__ == "__main__":
    main()
