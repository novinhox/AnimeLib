"""Library filesystem scanner, episode matcher, and subtitle finder."""
from __future__ import annotations

import os
from pathlib import Path

from AniLibV6.config import SUB_EXT, VIDEO_EXT
from AniLibV6.models import (
    Episode,
    Entry,
    clean_name,
    parse_episode,
    season_from_dirs,
)


def _match_sub(video_stem: str, ident: tuple[int | None, int | None], sub_files: list[Path]) -> str | None:
    """Find matching subtitle file for a video based on stem or parsed episode identity."""
    for p in sub_files:
        if p.stem == video_stem or p.stem.startswith(video_stem + "."):
            return str(p)
    if ident[1] is not None:
        same = [p for p in sub_files if parse_episode(p.name) == ident]
        if len(same) == 1:
            return str(same[0])
    return None


def find_sub(video: Path) -> str | None:
    """Find subtitle for a specific video path."""
    try:
        siblings = [p for p in video.parent.iterdir() if p.suffix.lower() in SUB_EXT]
    except OSError:
        return None
    return _match_sub(video.stem, parse_episode(video.name), siblings)


def sibling_subs(video: str | Path) -> list[Path]:
    """Every subtitle file next to the video that belongs to the same episode."""
    v = Path(video)
    ident = parse_episode(v.name)
    out: list[Path] = []
    try:
        files = sorted(v.parent.iterdir())
    except OSError:
        return out
    for f in files:
        if f.suffix.lower() not in SUB_EXT:
            continue
        if (
            f.stem == v.stem
            or f.stem.startswith(v.stem + ".")
            or (ident[1] is not None and parse_episode(f.name) == ident)
        ):
            out.append(f)
    return out


def scan_library(root: str | Path) -> list[Entry]:
    """Scan root folder for anime series directories and their episode files."""
    entries: list[Entry] = []
    try:
        folders = sorted(
            (p for p in Path(root).iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name.lower(),
        )
    except OSError:
        return entries

    for d in folders:
        eps: list[Episode] = []
        max_mtime = 0.0
        for dirpath, dirnames, files in os.walk(d):
            dirnames[:] = [x for x in dirnames if not x.startswith(".")]
            vid_files: list[Path] = []
            sub_files: list[Path] = []
            dp = Path(dirpath)
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in VIDEO_EXT:
                    vid_files.append(dp / f)
                elif ext in SUB_EXT:
                    sub_files.append(dp / f)
            if not vid_files:
                continue
            rel_dir = dp.relative_to(d)
            dir_season = season_from_dirs(list(rel_dir.parts)) if rel_dir.parts else None
            for p in vid_files:
                rel = p.relative_to(d)
                ident = parse_episode(p.name)
                season, num = ident
                if season is None:
                    season = dir_season
                sub = _match_sub(p.stem, ident, sub_files) if sub_files else None
                eps.append(Episode(str(p), rel.as_posix(), season, num, sub))
                try:
                    mt = p.stat().st_mtime
                    max_mtime = max(max_mtime, mt)
                except OSError:
                    pass

        if not eps:
            continue

        eps.sort(
            key=lambda e: (
                e.season or 1,
                e.number if e.number is not None else 10**6,
                e.key.lower(),
            )
        )
        entries.append(Entry(str(d), d.name, clean_name(d.name), max_mtime, eps))

    return entries
