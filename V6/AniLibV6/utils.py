"""System utilities, external player detection, ffmpeg frame extraction, and helpers."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics

from AniLibV6.config import FRAME_DIR


def open_path(path: str | Path) -> None:
    """Open folder or file in the native system file explorer."""
    p_str = str(path)
    if sys.platform.startswith("win"):
        os.startfile(p_str)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p_str])
    else:
        subprocess.Popen(["xdg-open", p_str])


def find_player() -> str | None:
    """Find installed external media player (mpv, vlc, mpc-hc, potplayer)."""
    for exe in ("mpv", "vlc", "mpc-hc64", "mpc-hc", "mpc-be64", "PotPlayer64"):
        p = shutil.which(exe)
        if p:
            return p
    for p in (
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files\mpv\mpv.exe",
        r"C:\Program Files\MPC-HC\mpc-hc64.exe",
        r"C:\Program Files (x86)\MPC-HC\mpc-hc.exe",
        r"C:\Program Files\MPC-BE x64\mpc-be64.exe",
        r"C:\Program Files\DAUM\PotPlayer\PotPlayer64.exe",
        "/Applications/VLC.app/Contents/MacOS/VLC",
    ):
        if os.path.exists(p):
            return p
    return None


def find_ffmpeg(configured: str = "") -> str | None:
    """Locate ffmpeg binary on the host machine."""
    if configured and os.path.exists(configured):
        return configured
    p = shutil.which("ffmpeg")
    if p:
        return p
    for c in (
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ):
        if os.path.exists(c):
            return c
    return None


def frame_path(video: str | Path) -> Path:
    """Compute deterministic cache path for a video's thumbnail frame."""
    video_str = str(video)
    try:
        st = os.stat(video_str)
        sig = f"{video_str}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        sig = video_str
    return FRAME_DIR / (hashlib.md5(sig.encode("utf-8", "replace")).hexdigest() + ".jpg")


def _run_quiet(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Execute a process silently without a popping console window on Windows."""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
    return subprocess.run(
        cmd, capture_output=True, timeout=timeout, creationflags=flags, check=False
    )


def extract_frame(ffmpeg: str, video: str, out: Path) -> bool:
    """Extract one representative frame (~20% into video) using FFmpeg."""
    try:
        FRAME_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    dur = 0.0
    probe = Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix)
    probe_str = str(probe) if probe.exists() else (shutil.which("ffprobe") or "")
    if probe_str:
        try:
            r = _run_quiet(
                [
                    probe_str,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    video,
                ],
                20,
            )
            dur = float(r.stdout.decode().strip().split()[0])
        except Exception:
            dur = 0.0

    times = [max(5.0, dur * 0.2)] if dur > 0 else [60.0]
    times += [5.0, 0.0]
    tmp = out.with_name(out.stem + ".part.jpg")
    for t in times:
        try:
            _run_quiet(
                [
                    ffmpeg,
                    "-y",
                    "-v",
                    "error",
                    "-ss",
                    f"{t:.1f}",
                    "-i",
                    video,
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=640:-2",
                    "-q:v",
                    "4",
                    str(tmp),
                ],
                45,
            )
        except Exception:
            continue
        if tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(out)
            return True
    return False


def clear_layout(lay) -> None:
    """Safely recursively remove and hide all widgets without turning them into top-level windows."""
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w is not None:
            w.hide()
            w.deleteLater()
        elif it.layout() is not None:
            clear_layout(it.layout())


def wrap_lines(text: str, fm: QFontMetrics, width: int, max_lines: int) -> list[str]:
    """Word-wrap text to at most max_lines, eliding the last line with an ellipsis."""
    lines: list[str] = []
    cur = ""
    for word in (text or "").split():
        trial = f"{cur} {word}".strip()
        if fm.horizontalAdvance(trial) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        rest = " ".join(lines[max_lines - 1:])
        lines = lines[:max_lines - 1] + [
            fm.elidedText(rest, Qt.TextElideMode.ElideRight, width)
        ]
    else:
        lines = [fm.elidedText(l, Qt.TextElideMode.ElideRight, width) for l in lines]
    return lines


_shimmer: Shimmer | None = None


class Shimmer(QObject):
    """Shared 30fps timer driving shimmer placeholder animations across all cards."""
    tick = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._step)

    def _step(self) -> None:
        self.phase = (self.phase + 0.02) % 1.0
        self.tick.emit()

    def set_active(self, on: bool) -> None:
        if on and not self.timer.isActive():
            self.timer.start()
        elif not on:
            self.timer.stop()


def shimmer() -> Shimmer:
    """Singleton getter for Shimmer."""
    global _shimmer
    if _shimmer is None:
        _shimmer = Shimmer()
    return _shimmer
