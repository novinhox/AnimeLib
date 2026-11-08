"""Data models for anime entries, episodes, subtitle tracks, and regex matchers."""
from __future__ import annotations

from dataclasses import dataclass, field
import difflib
from functools import lru_cache
from pathlib import Path
import re

# Noise tokens stripped from folder/file names to improve AniList queries
NOISE = re.compile(
    r"\b(?:480p|720p|1080p|2160p|4k|bd|bluray|blu-ray|bdrip|web-?dl|web-?rip|webrip|hevc|"
    r"x26[45]|h\.?26[45]|av1|aac|flac|opus|10-?bit|8-?bit|dual[ -]?audio|multi[ -]?subs?|"
    r"batch|complete|uncensored|remux|repack)\b",
    re.IGNORECASE,
)
_BRACKETS_RE = re.compile(r"[\[\(\{].*?[\]\)\}]")
_DOTS_RE = re.compile(r"[._]+")
_WS_RE = re.compile(r"\s+")
_TS_PREFIX_RE = re.compile(r"^\d{8,}[_\-. ]*")
_TAG_BRACKETS_RE = re.compile(r"[\[\(].*?[\]\)]")
_SE_RE = re.compile(r"\bS(\d{1,2})\s*E(\d{1,3})\b", re.IGNORECASE)
_EP_RE = re.compile(r"(?<![a-z])(?:episode|ep|e)\s*(\d{1,3})(?!\d)", re.IGNORECASE)
_DASH_EP_RE = re.compile(r"\s-\s*(\d{1,3})(?:v\d)?(?!\d)")
_NUM_EP_RE = re.compile(r"(?<![A-Za-z\d])(\d{1,3})(?!\d|[pPkK]\b|x)")
_SEASON_DIR_RE = re.compile(r"season\s*(\d+)|^s(\d{1,2})$", re.IGNORECASE)


def norm(s: str) -> str:
    """Normalize string for fuzzy matching (lowercase alphanumeric)."""
    return re.sub(r"[\W_]+", " ", s or "").strip().lower()


def clean_name(name: str) -> str:
    """Strip bracketed release tags and quality words to extract the clean anime title."""
    s = _BRACKETS_RE.sub(" ", name)
    s = _DOTS_RE.sub(" ", s)
    s = NOISE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip(" -")
    return s or name


@lru_cache(maxsize=4096)
def parse_episode(filename: str) -> tuple[int | None, int | None]:
    """Return (season or None, episode number or None) parsed from filename."""
    s = Path(filename).stem
    s = _TS_PREFIX_RE.sub("", s)
    s = _TAG_BRACKETS_RE.sub(" ", s)
    s = s.replace("_", " ").replace(".", " ")
    m = _SE_RE.search(s)
    if m:
        return int(m[1]), int(m[2])
    m = _EP_RE.search(s)
    if m:
        return None, int(m[1])
    m = _DASH_EP_RE.search(s)
    if m:
        return None, int(m[1])
    nums = _NUM_EP_RE.findall(s)
    if nums:
        return None, int(nums[-1])
    return None, None


def season_from_dirs(parts: list[str]) -> int | None:
    """Extract season number from directory path components."""
    for part in reversed(parts):
        m = _SEASON_DIR_RE.search(part)
        if m:
            return int(m[1] or m[2])
    return None


def best_match(query: str, cands: list[dict]) -> dict | None:
    """Score search candidates by title similarity to find the best match."""
    qn = norm(query)

    def score(m: dict) -> float:
        t = m.get("title") or {}
        syns = [norm(x) for x in (t.get("romaji"), t.get("english"), t.get("native")) if x]
        syns += [norm(x) for x in m.get("synonyms") or [] if x]
        if not syns:
            return 0.0
        if any(s == qn for s in syns):
            return 2.0
        return max(difflib.SequenceMatcher(None, qn, s).ratio() for s in syns)

    return max(cands, key=score, default=None)


def fmt_time(ms: int | float | None) -> str:
    """Format milliseconds into H:MM:SS or M:SS string."""
    if ms is None or ms < 0:
        return "0:00"
    s = int(ms // 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


@dataclass
class Episode:
    """Represents a single video episode."""
    path: str
    key: str  # path relative to the anime folder (used for watch tracking)
    season: int | None
    number: int | None
    sub: str | None


@dataclass
class Entry:
    """Represents an anime entry containing one or more episodes and AniList metadata."""
    path: str
    name: str
    query: str
    mtime: float
    episodes: list[Episode]
    media: dict | None = None
    _ep_keys: frozenset = field(init=False, repr=False)
    _multi_season: bool = field(init=False, repr=False)
    _search_blob: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        self._ep_keys = frozenset(e.key for e in self.episodes)
        self._multi_season = len({(x.season or 1) for x in self.episodes}) > 1
        self._rebuild_search_blob()

    def _rebuild_search_blob(self) -> None:
        m = self.media or {}
        t = m.get("title") or {}
        names = [
            self.name,
            self.query,
            self.title,
            t.get("romaji") or "",
            t.get("english") or "",
            t.get("native") or "",
        ] + list(m.get("synonyms") or [])
        self._search_blob = " | ".join(norm(n) for n in names if n)

    @property
    def title(self) -> str:
        if self.media:
            t = self.media.get("title") or {}
            return t.get("english") or t.get("romaji") or t.get("native") or self.query
        return self.query


class SubTrack:
    """Subtitle track representation."""
    def __init__(self, title: str, cues: list[tuple[int, int, str]], is_external: bool = False):
        self.title = title
        self.cues = cues
        self.is_external = is_external
