"""Background worker threads for metadata fetching and video frame extraction."""
from __future__ import annotations

from collections import deque
import os
import time

from PySide6.QtCore import QThread, Signal

from AniLibV6.anilist import (
    anilist_request,
    download_image,
)
from AniLibV6.config import FRAME_DIR, ID_Q, REQUEST_DELAY, SEARCH_Q
from AniLibV6.models import best_match
from AniLibV6.utils import extract_frame, frame_path


class MetaWorker(QThread):
    """Scrapes AniList GraphQL in the background respecting rate limits."""
    progress = Signal(int, int, str)
    result = Signal(str, str, object, object, bool)  # path, query, media, search results, ok

    def __init__(self, jobs: list[tuple[str, str, int | None]], media_cache: dict, search_cache: dict) -> None:
        super().__init__()
        self.jobs = jobs
        self.media = dict(media_cache)
        self.search = dict(search_cache)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def _pause(self) -> None:
        time.sleep(REQUEST_DELAY)

    def resolve(self, query: str, forced_id: int | None) -> tuple[dict | None, list | None]:
        results = None
        if forced_id:
            media = self.media.get(str(forced_id))
            if not media or "relations" not in media:
                data = anilist_request(ID_Q, {"id": int(forced_id)})
                self._pause()
                media = data["Media"] if data else None
        else:
            ids = self.search.get(query)
            cands = (
                [self.media[str(i)] for i in ids if str(i) in self.media]
                if ids is not None
                else None
            )
            if not cands or any("relations" not in c for c in cands):
                data = anilist_request(SEARCH_Q, {"s": query})
                self._pause()
                cands = data["Page"]["media"] if data else []
                results = cands
            media = best_match(query, cands)

        if media:
            media = dict(media)
            if not (media.get("_cover") and os.path.exists(media["_cover"])):
                cover = media.get("coverImage") or {}
                p = download_image(cover.get("large") or cover.get("extraLarge"))
                if p is not None:
                    media["_cover"] = p
            if not (media.get("_banner") and os.path.exists(media["_banner"])):
                p = download_image(media.get("bannerImage"))
                if p is not None:
                    media["_banner"] = p
        return media, results

    def run(self) -> None:
        total = len(self.jobs)
        for i, (path, query, forced_id) in enumerate(self.jobs, 1):
            if self._stop:
                break
            self.progress.emit(i, total, query)
            try:
                media, results = self.resolve(query, forced_id)
                self.result.emit(path, query, media, results, True)
            except Exception:
                self.result.emit(path, query, None, None, False)


class FrameWorker(QThread):
    """Extracts video frame thumbnails in the background via FFmpeg."""
    frame_ready = Signal(str, str)
    progress = Signal(int, int)

    def __init__(self, ffmpeg: str, queue: deque[str]) -> None:
        super().__init__()
        self.ffmpeg, self.queue = ffmpeg, queue
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        done = 0
        while not self._stop:
            try:
                video = self.queue.popleft()
            except IndexError:
                break
            out = frame_path(video)
            fail = out.with_suffix(".fail")
            if not out.exists() and not fail.exists():
                if extract_frame(self.ffmpeg, video, out):
                    self.frame_ready.emit(video, str(out))
                else:
                    try:
                        FRAME_DIR.mkdir(parents=True, exist_ok=True)
                        fail.write_bytes(b"")
                    except OSError:
                        pass
            done += 1
            self.progress.emit(done, done + len(self.queue))
