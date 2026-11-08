"""Configuration, paths, constants, and JSON helpers for AniLibV6."""
from __future__ import annotations

import json
import os
from pathlib import Path

# Base directories
def _get_app_dir() -> Path:
    env = os.environ.get("ANIME_LIBRARY_HOME")
    if env:
        p = Path(env)
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except OSError:
            pass
    try:
        p = Path.home() / ".anime_library"
        p.mkdir(parents=True, exist_ok=True)
        test_file = p / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return p
    except Exception:
        local = Path(__file__).resolve().parent.parent / ".anime_library"
        try:
            local.mkdir(parents=True, exist_ok=True)
            return local
        except OSError:
            return Path.home() / ".anime_library"

APP_DIR = _get_app_dir()
IMG_DIR = APP_DIR / "images"
FONT_DIR = APP_DIR / "fonts"
SOUND_DIR = APP_DIR / "sounds"
FRAME_DIR = IMG_DIR / "frames"
UPDATES_DIR = APP_DIR / "updates"
CONFIG_FILE = APP_DIR / "config.json"
CACHE_FILE = APP_DIR / "cache.json"

APP_VERSION = "6.0.1"
DEFAULT_UPDATE_URL = os.environ.get("ANIME_LIBRARY_UPDATE_URL", "novinhox/AnimeLib")

def ensure_dirs() -> None:
    """Safely create required directories without crashing if permissions are restricted."""
    for p in (APP_DIR, IMG_DIR, FONT_DIR, SOUND_DIR, FRAME_DIR, UPDATES_DIR):
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

ensure_dirs()

# Media extensions
VIDEO_EXT = {".mkv", ".mp4", ".avi", ".webm", ".m4v", ".mov", ".wmv", ".flv", ".ts"}
SUB_EXT = (".vtt", ".srt", ".ass", ".ssa")

# AniList API config
ANILIST_URL = "https://graphql.anilist.co"
REQUEST_DELAY = 0.8  # AniList allows ~90 requests/minute
USER_AGENT = f"AniLibV6/{APP_VERSION} (visionOS AppleTV Edition)"

ACCENT = "#e50914"

# Browse filters & sorts
STATUS_FILTERS = ["All", "Unwatched", "In progress", "Completed"]
SORTS = ["A–Z", "Recently added", "Top rated", "Newest", "Most watched"]

# GraphQL queries
MEDIA_FIELDS = (
    "id title{romaji english native} synonyms description(asHtml:false) "
    "coverImage{large extraLarge color} bannerImage genres averageScore "
    "episodes seasonYear format status "
    "relations{edges{relationType(version:2) node{id type title{romaji english native} format seasonYear episodes}}}"
)
SEARCH_Q = (
    "query($s:String){Page(perPage:8){media(search:$s,type:ANIME,sort:SEARCH_MATCH){%s}}}"
    % MEDIA_FIELDS
)
ID_Q = "query($id:Int){Media(id:$id,type:ANIME){%s}}" % MEDIA_FIELDS


def load_json(path: Path, default):
    """Safely load JSON data from a file with fallback default."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data):
    """Safely atomically write JSON data to a file."""
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
