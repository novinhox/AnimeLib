"""Lightweight OTA Auto-Updater (~35 KB code patch zip) & Release Packager for AniLibV6."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile

from PySide6.QtCore import QThread, Signal

from AniLibV6.config import APP_VERSION, DEFAULT_UPDATE_URL, UPDATES_DIR, USER_AGENT


def parse_version(v: str | None) -> tuple[int, ...]:
    """Parse version string like 'v6.1.2' into comparable integer tuple (6, 1, 2)."""
    if not v:
        return (0,)
    nums = [int(x) for x in re.findall(r"\d+", str(v))]
    return tuple(nums) if nums else (0,)


def is_newer(remote_ver: str, current_ver: str = APP_VERSION) -> bool:
    """Return True if remote_ver is strictly greater than current_ver."""
    return parse_version(remote_ver) > parse_version(current_ver)


def _extract_github_repo(source: str) -> str | None:
    """If source is 'owner/repo' or 'https://github.com/owner/repo', return 'owner/repo'."""
    s = (source or "").strip()
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", s):
        return s
    m = re.match(r"^https?://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git|/)?$", s)
    if m:
        return m.group(1)
    return None


def normalize_update_source(source: str) -> list[str]:
    """Convert a GitHub repo shorthand ('owner/repo' or 'https://github.com/owner/repo')
    or direct manifest URL into a prioritized list of candidate endpoint URLs."""
    s = (source or "").strip()
    if not s:
        return []
    # Local file path for testing or LAN shares
    if os.path.exists(s):
        return [s]
    repo = _extract_github_repo(s)
    if repo:
        # Check direct raw branch manifests first (works immediately on `git push` without creating a Release),
        # then fall back to GitHub Releases API
        return [
            f"https://raw.githubusercontent.com/{repo}/main/V6/release/version.json",
            f"https://raw.githubusercontent.com/{repo}/main/release/version.json",
            f"https://raw.githubusercontent.com/{repo}/master/V6/release/version.json",
            f"https://api.github.com/repos/{repo}/releases/latest",
        ]
    return [s]


def _fetch_bytes(url_or_path: str, timeout: int = 20) -> bytes:
    """Fetch bytes from an HTTP/HTTPS URL or a local/LAN file path."""
    if os.path.exists(url_or_path):
        return Path(url_or_path).read_bytes()
    req = urllib.request.Request(
        url_or_path,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json, application/json, */*",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check_remote_update(source: str, current_ver: str = APP_VERSION) -> dict:
    """Check update source for a newer version.
    Returns dict with keys:
      available (bool), version (str), current (str), download_url (str),
      notes (str), sha256 (str), size (int)
    """
    endpoints = normalize_update_source(source or DEFAULT_UPDATE_URL)
    if not endpoints:
        raise ValueError("No update server / repository URL configured.")

    data = None
    used_endpoint = ""
    last_err = None
    for ep in endpoints:
        try:
            raw = _fetch_bytes(ep, timeout=15)
            data = json.loads(raw.decode("utf-8"))
            used_endpoint = ep
            break
        except Exception as e:
            last_err = e
            continue

    if data is None:
        raise RuntimeError(f"Could not reach update server ({last_err})")
    endpoint = used_endpoint

    # Support both GitHub Releases API format and custom version.json manifest format
    if "tag_name" in data:
        remote_ver = str(data.get("tag_name") or "").lstrip("vV")
        notes = str(data.get("body") or "").strip()
        dl_url = ""
        size = 0
        for asset in data.get("assets") or []:
            name = (asset.get("name") or "").lower()
            if name.endswith(".zip"):
                dl_url = asset.get("browser_download_url") or ""
                size = int(asset.get("size") or 0)
                break
        if not dl_url:
            dl_url = data.get("zipball_url") or ""
        sha256 = ""
    else:
        remote_ver = str(data.get("version") or "").lstrip("vV")
        notes = str(data.get("notes") or data.get("changelog") or "").strip()
        dl_url = str(data.get("url") or data.get("download_url") or "").strip()
        sha256 = str(data.get("sha256") or "").strip().lower()
        size = int(data.get("size") or 0)
        # Resolve relative download_url if endpoint is a local/remote manifest
        if dl_url and not dl_url.startswith(("http://", "https://")) and not os.path.isabs(dl_url):
            if os.path.exists(endpoint):
                dl_url = str((Path(endpoint).parent / dl_url).resolve())
            elif "/" in endpoint:
                base = endpoint.rsplit("/", 1)[0]
                dl_url = f"{base}/{dl_url}"

    if not remote_ver:
        raise RuntimeError("Invalid update manifest (missing version).")

    avail = is_newer(remote_ver, current_ver)
    return {
        "available": avail,
        "version": remote_ver,
        "current": current_ver,
        "download_url": dl_url,
        "notes": notes,
        "sha256": sha256,
        "size": size,
    }


def apply_update_package(zip_bytes: bytes, version: str, expected_sha256: str = "") -> Path:
    """Verify and extract an AniLibV6 code update zip into UPDATES_DIR/current (and local dev dir if writable)."""
    if expected_sha256:
        actual = hashlib.sha256(zip_bytes).hexdigest().lower()
        if actual != expected_sha256.lower():
            raise RuntimeError(f"SHA-256 mismatch (expected {expected_sha256[:12]}…, got {actual[:12]}…)")

    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    staging = UPDATES_DIR / f"staging_{int(time.time())}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            zf.extractall(staging)

        # Locate the AniLibV6 package folder inside the extracted archive
        pkg_dir = None
        if (staging / "AniLibV6" / "__init__.py").is_file():
            pkg_dir = staging / "AniLibV6"
        elif (staging / "__init__.py").is_file() and (staging / "main.py").is_file():
            pkg_dir = staging
        else:
            for cand in staging.rglob("__init__.py"):
                if (cand.parent / "main.py").is_file() and cand.parent.name == "AniLibV6":
                    pkg_dir = cand.parent
                    break
            if pkg_dir is None:
                for cand in staging.rglob("main.py"):
                    if (cand.parent / "config.py").is_file() and (cand.parent / "ui").is_dir():
                        pkg_dir = cand.parent
                        break

        if pkg_dir is None:
            raise RuntimeError("Update archive does not contain a valid AniLibV6 package.")

        target_root = UPDATES_DIR / "current"
        target_pkg = target_root / "AniLibV6"
        if target_root.exists():
            shutil.rmtree(target_root, ignore_errors=True)
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(pkg_dir, target_pkg)

        # Write active update metadata
        meta = {
            "version": version,
            "installed_at": time.time(),
            "size": len(zip_bytes),
        }
        (UPDATES_DIR / "active.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        # Also sync local source folder if running from unpacked source and writable
        if not getattr(sys, "frozen", False):
            local_pkg = Path(__file__).resolve().parent
            if local_pkg.name == "AniLibV6" and not str(local_pkg).startswith(str(UPDATES_DIR)):
                try:
                    for src_file in target_pkg.rglob("*.py"):
                        rel = src_file.relative_to(target_pkg)
                        dst_file = local_pkg / rel
                        dst_file.parent.mkdir(parents=True, exist_ok=True)
                        dst_file.write_bytes(src_file.read_bytes())
                except OSError:
                    pass

        return target_root
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def build_release_bundle(out_dir: str | Path | None = None, download_url: str = "AniLibV6_update.zip", notes: str = "") -> tuple[Path, Path]:
    """Package the current AniLibV6 Python code into a tiny ~35 KB zip + version.json manifest
    ready to upload to GitHub Releases or any static web host."""
    pkg_dir = Path(__file__).resolve().parent
    dest_dir = Path(out_dir) if out_dir else (pkg_dir.parent / "release")
    dest_dir.mkdir(parents=True, exist_ok=True)

    zip_path = dest_dir / "AniLibV6_update.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for f in sorted(pkg_dir.rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            rel = f.relative_to(pkg_dir.parent)
            zf.write(f, rel.as_posix())

    raw_bytes = buf.getvalue()
    zip_path.write_bytes(raw_bytes)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    manifest = {
        "version": APP_VERSION,
        "url": download_url,
        "sha256": sha256,
        "size": len(raw_bytes),
        "notes": notes or f"AniLib V6 v{APP_VERSION} OTA Code Update",
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    manifest_path = dest_dir / "version.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return zip_path, manifest_path


class UpdateWorker(QThread):
    """Background worker that checks for OTA updates and optionally downloads & applies them."""

    checked = Signal(dict)          # Emits update info dict
    downloaded = Signal(str, str)   # Emits (new_version, notes) when applied
    failed = Signal(str, bool)      # Emits (error_message, was_manual)

    def __init__(self, source: str, auto_apply: bool = True, manual: bool = False) -> None:
        super().__init__()
        self.source = source
        self.auto_apply = auto_apply
        self.manual = manual

    def run(self) -> None:
        try:
            info = check_remote_update(self.source, APP_VERSION)
            self.checked.emit(info)
            if info.get("available") and self.auto_apply and info.get("download_url"):
                raw = _fetch_bytes(info["download_url"], timeout=30)
                apply_update_package(raw, info["version"], info.get("sha256", ""))
                self.downloaded.emit(info["version"], info.get("notes", ""))
        except Exception as e:
            self.failed.emit(str(e), self.manual)
