"""AniList GraphQL API client, image caching, and metadata helpers."""
from __future__ import annotations

import difflib
import hashlib
import html
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from AniLibV6.config import ANILIST_URL, IMG_DIR, USER_AGENT

_TAG_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_ALL = re.compile(r"<[^>]+>")
_NORM_RE = re.compile(r"[^a-z0-9]+")


def anilist_request(query: str, variables: dict, retries: int = 3) -> dict | None:
    """Execute a GraphQL request against AniList API with retry and rate-limiting support."""
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    last = None
    for _ in range(retries):
        req = urllib.request.Request(
            ANILIST_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8")).get("data")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    wait = int(e.headers.get("Retry-After", "30"))
                except ValueError:
                    wait = 30
                time.sleep(wait + 1)
                last = e
                continue
            if e.code == 404:
                return None
            last = e
            time.sleep(2)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            time.sleep(2)
    raise RuntimeError(f"AniList request failed: {last}")


def download_image(url: str | None) -> str | None:
    """Download image to disk cache and return local file path ('None' on error, '' if no url)."""
    if not url:
        return ""
    ext = Path(url.split("?")[0]).suffix or ".jpg"
    dest = IMG_DIR / (hashlib.md5(url.encode()).hexdigest() + ext)
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)
    try:
        IMG_DIR.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            dest.write_bytes(r.read())
        return str(dest)
    except Exception:
        return None


def media_title(m: dict | None) -> str:
    """Extract display title (prefer English, fallback to Romaji/Native)."""
    if not m:
        return "?"
    t = m.get("title") or {}
    return t.get("english") or t.get("romaji") or t.get("native") or "?"


def clean_desc(s: str | None) -> str:
    """Strip HTML tags and unescape text entities for description display."""
    s = _TAG_BR.sub("\n", s or "")
    s = _TAG_ALL.sub("", s)
    return html.unescape(s).strip()


def media_ready(m: dict | None) -> bool:
    """Return True if media metadata and downloaded cover/banner images are valid on disk."""
    if not m or "relations" not in m:
        return False
    for key in ("_cover", "_banner"):
        if key not in m:
            return False
        if m[key] and not os.path.exists(m[key]):
            return False
    return True


def media_relations(m: dict | None) -> list[dict]:
    """Extract anime relations (PREQUEL, SEQUEL, etc.) from AniList media dict."""
    if not m:
        return []
    edges = ((m.get("relations") or {}).get("edges")) or []
    out: list[dict] = []
    seen: set[int] = set()
    for edge in edges:
        if not edge:
            continue
        rel_type = edge.get("relationType")
        node = edge.get("node") or {}
        if node.get("type") != "ANIME" or not node.get("id"):
            continue
        nid = int(node["id"])
        if nid in seen:
            continue
        seen.add(nid)
        out.append(
            {
                "id": nid,
                "relationType": rel_type or "RELATED",
                "title": media_title(node),
                "format": node.get("format"),
                "seasonYear": node.get("seasonYear"),
                "episodes": node.get("episodes"),
            }
        )
    return out
