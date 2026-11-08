"""Subtitle parsing (.vtt, .srt, .ass, .ssa) and SubTrack cue indexer."""
from __future__ import annotations

import bisect
import html
from pathlib import Path
import re

_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
_ASS_BRACE_RE = re.compile(r"\{[^}]*\}")
_ITALIC_START_RE = re.compile(r"\s*<i>", re.IGNORECASE)
_BLANK_BLOCK_RE = re.compile(r"\n\s*\n")
_TAG_ALL = re.compile(r"<[^>]+>")


def _ts_ms(m: re.Match) -> int:
    """Convert timestamp regex match to milliseconds."""
    return (
        (int(m.group(1) or 0) * 60 + int(m.group(2))) * 60 + int(m.group(3))
    ) * 1000 + int(m.group(4).ljust(3, "0"))


def clean_sub_text(t: str) -> tuple[str, bool]:
    """Strip ASS/HTML tags. Returns (text, italic)."""
    t = _ASS_BRACE_RE.sub("", t)
    t = t.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
    italic = bool(_ITALIC_START_RE.match(t))
    t = _TAG_ALL.sub("", t)
    return html.unescape(t).strip(), italic


def parse_subtitles(path: str | Path) -> list[tuple[int, int, str, bool]]:
    """Parse .vtt / .srt / .ass into a sorted list of (start_ms, end_ms, text, italic)."""
    raw = Path(path).read_bytes()
    text = ""
    for enc in ("utf-8-sig", "cp1252", "latin-1", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        text = raw.decode("utf-8", errors="replace")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cues: list[tuple[int, int, str, bool]] = []

    if Path(path).suffix.lower() in (".ass", ".ssa"):
        cols = [
            "layer",
            "start",
            "end",
            "style",
            "name",
            "marginl",
            "marginr",
            "marginv",
            "effect",
            "text",
        ]
        for line in text.split("\n"):
            low = line.lower()
            if low.startswith("format:") and "start" in low and "text" in low:
                cols = [c.strip().lower() for c in line.split(":", 1)[1].split(",")]
            elif low.startswith("dialogue:"):
                parts = line.split(":", 1)[1].split(",", len(cols) - 1)
                if len(parts) < len(cols):
                    continue
                d = dict(zip(cols, parts, strict=False))
                a, b = _TS.search(d.get("start", "").strip()), _TS.search(d.get("end", "").strip())
                if a and b:
                    t, it = clean_sub_text(d.get("text", ""))
                    if t:
                        cues.append((_ts_ms(a), _ts_ms(b), t, it))
    else:
        for block in _BLANK_BLOCK_RE.split(text):
            lines = block.split("\n")
            idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
            if idx is None:
                head = lines[0].strip().upper() if lines and lines[0].strip() else ""
                if (
                    cues
                    and head
                    and not head.startswith(("WEBVTT", "NOTE", "STYLE", "REGION"))
                    and not head.isdigit()
                ):
                    t, _ = clean_sub_text("\n".join(lines))
                    if t:
                        s, e, pt, it = cues[-1]
                        cues[-1] = (s, e, pt + "\n" + t, it)
                continue
            left, right = lines[idx].split("-->", 1)
            a, b = _TS.search(left.strip()), _TS.search(right.strip())
            if not (a and b):
                continue
            t, it = clean_sub_text("\n".join(lines[idx + 1:]))
            if t:
                cues.append((_ts_ms(a), _ts_ms(b), t, it))

    cues.sort(key=lambda c: c[0])
    return cues


class SubTrack:
    """Indexed subtitle track with binary search lookup."""
    def __init__(self, cues: list[tuple[int, int, str, bool]]):
        self.cues = cues
        self.starts = [c[0] for c in cues]

    def at(self, ms: int) -> list[tuple[str, bool]]:
        """Return all active (text, italic) cues at timestamp ms."""
        i = bisect.bisect_right(self.starts, ms)
        out: list[tuple[str, bool]] = []
        for j in range(i - 1, max(-1, i - 14), -1):
            s, e, t, it = self.cues[j]
            if s <= ms < e and (t, it) not in out:
                out.append((t, it))
        out.reverse()
        return out
