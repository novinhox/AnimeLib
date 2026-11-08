"""MainWindow controller, Root container widget, and Windows application icon integration."""
from __future__ import annotations

from collections import deque
import os
from pathlib import Path
import random
import struct
import subprocess
import sys
import time

import shiboken6

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from AniLibV6.anilist import clean_desc, media_ready, media_relations, media_title
from AniLibV6.config import (
    APP_DIR,
    APP_VERSION,
    CACHE_FILE,
    CONFIG_FILE,
    DEFAULT_UPDATE_URL,
    FRAME_DIR,
    SORTS,
    STATUS_FILTERS,
    load_json,
    save_json,
)
from AniLibV6.models import Entry, Episode, best_match, clean_name, fmt_time, norm
from AniLibV6.scanner import scan_library
from AniLibV6.theme import T, qc, ui_fm, ui_font
from AniLibV6.ui.cards import EpisodeCard, PosterCard, PreviewCard
from AniLibV6.ui.common import (
    AA,
    CardGrid,
    ChipStrip,
    FadeStack,
    Row,
    SmoothScrollArea,
    Toast,
    bake_poster,
    cover_pixmap,
    draw_app_icon,
    episode_thumb,
    frame_thumb,
    load_pixmap,
    rounded_pixmap,
    tint_for,
)
from AniLibV6.ui.components import NavBar
from AniLibV6.ui.dialogs import MatchDialog, SettingsDialog
from AniLibV6.ui.hero import BannerWidget, HeroBanner
from AniLibV6.ui.intro import NetflixIntro
from AniLibV6.ui.player import HAVE_MM, PlayerPage
from AniLibV6.updater import UpdateWorker, build_release_bundle
from AniLibV6.utils import clear_layout, find_ffmpeg, find_player, open_path
from AniLibV6.workers import FrameWorker, MetaWorker

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
_app_icon = None
_win_icons = []


def app_icon() -> QIcon:
    """Return multi-resolution application icon."""
    global _app_icon
    if _app_icon is None:
        _app_icon = QIcon()
        for sz in ICON_SIZES + (512,):
            _app_icon.addPixmap(draw_app_icon(sz))
    return _app_icon


def build_ico_bytes() -> bytes:
    """Multi-size .ico (PNG-compressed entries) built from the code-drawn icon."""
    entries = []
    for sz in ICON_SIZES:
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        draw_app_icon(sz).save(buf, "PNG")
        entries.append((sz, bytes(buf.data())))
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    directory, blobs = b"", b""
    for sz, data in entries:
        directory += struct.pack(
            "<BBBBHHII",
            0 if sz >= 256 else sz,
            0 if sz >= 256 else sz,
            0,
            0,
            1,
            32,
            len(data),
            offset + len(blobs),
        )
        blobs += data
    return header + directory + blobs


def apply_windows_icon(win) -> bool:
    """Windows only: set title-bar and taskbar icon through Win32 API WM_SETICON."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        APP_DIR.mkdir(parents=True, exist_ok=True)
        ico = APP_DIR / "app_icon.ico"
        ico.write_bytes(build_ico_bytes())
        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x80
        hwnd = int(win.winId())
        for which, metric in ((1, 11), (0, 49)):
            size = user32.GetSystemMetrics(metric)
            h = user32.LoadImageW(None, str(ico), IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if h:
                _win_icons.append(h)
                user32.SendMessageW(hwnd, WM_SETICON, which, h)
        return True
    except Exception:
        return False


class Root(QWidget):
    """Holds page stack and floats nav bar, preview card, toast, and cinematic intro above it."""

    def __init__(self) -> None:
        super().__init__()
        self.nav = None
        self.stack = None
        self.toast = None
        self.intro = None
        self._ambient = QColor(T.ACCENT)

    def set_ambient(self, color: str | QColor) -> None:
        c = QColor(color) if color else QColor(T.ACCENT)
        if not c.isValid():
            c = QColor(T.ACCENT)
        if c != self._ambient:
            self._ambient = c
            self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        W, H = float(self.width()), float(self.height())
        if W <= 0 or H <= 0:
            return

        p.fillRect(self.rect(), QColor(T.BG))

        # Top-left dynamic ambient aura
        amb = QColor(self._ambient)
        amb.setAlpha(38)
        rg1 = QRadialGradient(QPointF(W * 0.16, H * 0.10), max(W, H) * 0.62)
        rg1.setColorAt(0.0, amb)
        amb_mid = QColor(self._ambient)
        amb_mid.setAlpha(14)
        rg1.setColorAt(0.5, amb_mid)
        rg1.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), rg1)

        # Bottom-right violet nebula glow
        rg2 = QRadialGradient(QPointF(W * 0.88, H * 0.86), max(W, H) * 0.65)
        rg2.setColorAt(0.0, QColor(88, 36, 175, 34))
        rg2.setColorAt(0.5, QColor(42, 20, 95, 14))
        rg2.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), rg2)

        # Center-top crimson spotlight
        rg3 = QRadialGradient(QPointF(W * 0.52, -H * 0.12), max(W, H) * 0.50)
        rg3.setColorAt(0.0, QColor(229, 9, 20, 24))
        rg3.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), rg3)

        # Optical vignette
        vg = QRadialGradient(QPointF(W * 0.5, H * 0.45), max(W, H) * 0.75)
        vg.setColorAt(0.0, QColor(0, 0, 0, 0))
        vg.setColorAt(0.7, QColor(0, 0, 0, 20))
        vg.setColorAt(1.0, QColor(4, 4, 7, 120))
        p.fillRect(self.rect(), vg)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self.stack:
            self.stack.setGeometry(0, 0, self.width(), self.height())
        if self.nav:
            self.nav.setGeometry(0, 0, self.width(), T.NAV_H)
            self.nav.raise_()
        if self.toast and self.toast.isVisible():
            self.toast.reposition()
        if self.intro and shiboken6.isValid(self.intro) and self.intro.isVisible():
            self.intro.setGeometry(0, 0, self.width(), self.height())
            self.intro.raise_()


class MainWindow(QMainWindow):
    """Main application controller and orchestrator."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Anime Library")
        self.resize(1440, 900)
        self.setMinimumSize(760, 520)

        self.cfg = load_json(CONFIG_FILE, {})
        for k, v in (
            ("root", ""),
            ("player", ""),
            ("matches", {}),
            ("progress", {}),
            ("favorites", []),
            ("ui", {}),
        ):
            self.cfg.setdefault(k, v)
        self.cfg["ui"].setdefault("sub_font", "Modern Clean")
        self.cfg["ui"].setdefault("sub_scale", "Normal")
        self.cfg["ui"].setdefault("auto_update", True)
        self.cfg["ui"].setdefault("update_url", DEFAULT_UPDATE_URL)
        self.cache = load_json(CACHE_FILE, {"media": {}, "search": {}})
        self.cache.setdefault("media", {})
        self.cache.setdefault("search", {})
        T.animations = bool(self.cfg["ui"].get("animations", True))

        self.entries: list[Entry] = []
        self.by_path: dict[str, Entry] = {}
        self.by_media_id: dict[int, Entry] = {}
        self.worker: MetaWorker | None = None
        self.pending_jobs: list = []
        self.loading_paths: set[str] = set()
        self.fresh: set[str] = set()
        self.hero_paths: list[str] = []
        self.hero_index: int = 0
        self.hero_dirty: bool = True
        self.cur: Entry | None = None
        self.back_stack: list = []
        self.home_groups: list = []
        self.d_season: int | None = None
        self.d_ep_reverse: bool = False
        self.d_ep_query: str = ""
        self._restored: bool = False
        self._first_home_build: bool = True
        self._pv_target = None
        self.b_status: int = 0
        self.b_genre: str | None = None
        self.b_fav_only: bool = False
        self._genre_sig: tuple | None = None
        self.frame_worker: FrameWorker | None = None
        self.frame_queue: deque[str] = deque()
        self.update_worker: UpdateWorker | None = None
        self.pending_update_ver: str | None = None
        self.player: PlayerPage | None = None
        self._player_from = (0, None)
        self._was_max: bool = False

        self.frame_timer = QTimer(self)
        self.frame_timer.setSingleShot(True)
        self.frame_timer.setInterval(500)
        self.frame_timer.timeout.connect(self._refresh_frames_view)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(900)
        self.refresh_timer.timeout.connect(self.refresh_views)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(200)
        self.search_timer.timeout.connect(self.run_search)

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self._show_preview)

        self.preview_hide_timer = QTimer(self)
        self.preview_hide_timer.setSingleShot(True)
        self.preview_hide_timer.timeout.connect(self._hide_preview_tick)

        self._build_ui()

        geo = self.cfg["ui"].get("geometry")
        if geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))

        self.setWindowState(
            (self.windowState() & ~Qt.WindowState.WindowMinimized & ~Qt.WindowState.WindowFullScreen)
            | Qt.WindowState.WindowMaximized
        )
        self.rebuild_home()
        self.refresh_browse()
        QTimer.singleShot(0, self.start_scan)
        if self.cfg["ui"].get("auto_update", True):
            QTimer.singleShot(1800, lambda: self.check_for_updates(manual=False))

    def _build_ui(self) -> None:
        self.root = Root()
        self.setCentralWidget(self.root)
        self.stack = FadeStack()
        self.stack.setParent(self.root)
        self.root.stack = self.stack

        self.home_scroll = SmoothScrollArea()
        self.home_content = QWidget()
        self.home_lay = QVBoxLayout(self.home_content)
        self.home_lay.setContentsMargins(0, 0, 0, 40)
        self.home_lay.setSpacing(4)
        self.home_scroll.setWidget(self.home_content)

        self.stack.addWidget(self.home_scroll)
        self.stack.addWidget(self._build_browse())
        self.stack.addWidget(self._build_detail())

        self.player = PlayerPage(self) if HAVE_MM else None
        self.stack.addWidget(self.player if self.player else QWidget())

        self.nav = NavBar(self)
        self.nav.setParent(self.root)
        self.root.nav = self.nav
        self.search_edit = self.nav.search
        self.search_edit.textChanged.connect(lambda _: self.search_timer.start())
        self.nav.gear.clicked.connect(self.open_settings)

        self.preview = PreviewCard(self, self.root)
        self.toast_w = Toast(self.root)
        self.root.toast = self.toast_w

        self.intro = NetflixIntro(self.root, self)
        self.root.intro = self.intro
        self.intro.setGeometry(0, 0, self.root.width(), self.root.height())
        if T.animations:
            QTimer.singleShot(30, self.intro.start)
        else:
            self.intro.hide()
            self.intro.deleteLater()
            self.intro = None
            self.root.intro = None

        for area in (self.home_scroll, self.b_scroll, self.d_scroll):
            area.verticalScrollBar().valueChanged.connect(lambda v, a=area: self.on_scroll(a, v))

        self.status = QLabel("")
        self.statusBar().addWidget(self.status, 1)
        self.nav.set_page(0)

    def _build_browse(self) -> SmoothScrollArea:
        self.b_scroll = SmoothScrollArea()
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, T.NAV_H + 22, 0, 40)
        lay.setSpacing(12)

        head = QWidget()
        hl = QVBoxLayout(head)
        hl.setContentsMargins(T.MARGIN, 0, T.MARGIN, 0)
        hl.setSpacing(12)

        self.b_title = QLabel("Browse")
        self.b_title.setFont(ui_font(30, True, display=True))
        hl.addWidget(self.b_title)

        row = QHBoxLayout()
        row.setSpacing(8)

        self.b_status_group = QButtonGroup(self)
        self.b_status_group.setExclusive(True)
        for i, name in enumerate(STATUS_FILTERS):
            b = QPushButton(name)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.b_status_group.addButton(b, i)
            row.addWidget(b)
        self.b_status_group.idClicked.connect(self.on_status_chip)

        row.addStretch(1)
        lbl_sort = QLabel("Sort by")
        lbl_sort.setStyleSheet(f"color: {T.MUTED}; font-weight: 600; font-size: 13px;")
        row.addWidget(lbl_sort)

        self.b_sort = QComboBox()
        self.b_sort.addItems(SORTS)
        self.b_sort.currentIndexChanged.connect(lambda _: self.refresh_browse())
        row.addWidget(self.b_sort)
        hl.addLayout(row)

        self.b_strip = ChipStrip()
        self.b_strip_w = QWidget()
        self.b_strip_lay = QHBoxLayout(self.b_strip_w)
        self.b_strip_lay.setContentsMargins(0, 4, 0, 4)
        self.b_strip_lay.setSpacing(8)
        self.b_strip.setWidget(self.b_strip_w)
        hl.addWidget(self.b_strip)

        self.b_count = QLabel("")
        self.b_count.setStyleSheet(f"color: {T.MUTED}; font-size: 13px; font-weight: 500;")
        hl.addWidget(self.b_count)

        lay.addWidget(head)
        self.b_grid = CardGrid(self)
        lay.addWidget(self.b_grid)
        lay.addStretch(1)
        self.b_scroll.setWidget(content)
        return self.b_scroll

    def _build_detail(self) -> SmoothScrollArea:
        self.d_scroll = SmoothScrollArea()
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.d_banner = BannerWidget(360)
        bl = QVBoxLayout(self.d_banner)
        bl.setContentsMargins(T.MARGIN, T.NAV_H + 10, T.MARGIN, 26)

        back = QPushButton("←  Back")
        back.setObjectName("ghost")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFixedHeight(36)
        back.clicked.connect(self.go_back)
        bl.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        bl.addStretch(1)

        self.d_title = QLabel()
        self.d_title.setWordWrap(True)
        self.d_title.setFont(ui_font(40, True, display=True))
        self.d_meta = QLabel()
        self.d_meta.setStyleSheet("color: #d4d4de; font-size: 14px; font-weight: 500;")
        bl.addWidget(self.d_title)
        bl.addWidget(self.d_meta)
        lay.addWidget(self.d_banner)

        body = QWidget()
        bl2 = QVBoxLayout(body)
        bl2.setContentsMargins(T.MARGIN, 8, T.MARGIN, 48)
        bl2.setSpacing(22)

        top = QHBoxLayout()
        top.setSpacing(30)
        self.d_poster = QLabel()
        self.d_poster.setFixedSize(210, 308)
        top.addWidget(self.d_poster, 0, Qt.AlignmentFlag.AlignTop)

        right = QVBoxLayout()
        right.setSpacing(12)
        self.d_genres = QLabel()
        self.d_genres.setStyleSheet(f"color: {T.GREEN}; font-weight: 700; font-size: 14px;")
        right.addWidget(self.d_genres)

        self.d_desc = QLabel()
        self.d_desc.setWordWrap(True)
        self.d_desc.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.d_desc.setStyleSheet("color: #cfcfda; font-size: 14px; line-height: 155%;")
        right.addWidget(self.d_desc)
        right.addStretch(1)

        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.d_play = QPushButton("▶  Play")
        self.d_play.setObjectName("primary")
        self.d_play.setFont(ui_font(15, True))
        self.d_play.setMinimumHeight(46)
        self.d_play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.d_play.clicked.connect(lambda: self.cur and self.play_next(self.cur))
        btns.addWidget(self.d_play)

        self.d_fav = QPushButton("♡  My List")
        self.d_fav.setObjectName("ghost")
        self.d_fav.setMinimumHeight(46)
        self.d_fav.setCursor(Qt.CursorShape.PointingHandCursor)
        self.d_fav.clicked.connect(self._toggle_cur_fav)
        btns.addWidget(self.d_fav)

        for text, fn in (
            ("Mark all watched", self.mark_all_watched),
            ("Reset progress", self.reset_progress),
            ("Fix match…", lambda: self.cur and self.fix_match(self.cur)),
            ("Open folder", lambda: self.cur and open_path(self.cur.path)),
        ):
            b = QPushButton(text)
            b.setObjectName("ghost")
            b.setMinimumHeight(46)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch(1)
        right.addLayout(btns)
        top.addLayout(right, 1)
        bl2.addLayout(top)

        self.d_rel_wrap = QWidget()
        rl = QVBoxLayout(self.d_rel_wrap)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        rel_lab = QLabel("Timeline & Related Series")
        rel_lab.setFont(ui_font(20, True, display=True))
        rl.addWidget(rel_lab)
        self.d_rel_lay = QHBoxLayout()
        self.d_rel_lay.setContentsMargins(0, 0, 0, 0)
        self.d_rel_lay.setSpacing(14)
        rl.addLayout(self.d_rel_lay)
        self.d_rel_wrap.hide()
        bl2.addWidget(self.d_rel_wrap)

        self.d_next_wrap = QWidget()
        nl = QVBoxLayout(self.d_next_wrap)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(10)
        self.d_next_title = QLabel("Up Next")
        self.d_next_title.setFont(ui_font(20, True, display=True))
        nl.addWidget(self.d_next_title)
        self.d_next_lay = QVBoxLayout()
        nl.addLayout(self.d_next_lay)
        bl2.addWidget(self.d_next_wrap)

        ep_bar = QFrame()
        ep_bar.setObjectName("epControlBar")
        ep_bar.setStyleSheet(
            "QFrame#epControlBar {"
            "  background: rgba(255, 255, 255, 0.05);"
            "  border: 1px solid rgba(255, 255, 255, 0.09);"
            "  border-radius: 20px;"
            "}"
        )
        eh = QHBoxLayout(ep_bar)
        eh.setContentsMargins(18, 12, 18, 12)
        eh.setSpacing(14)

        lab2 = QLabel("Episodes")
        lab2.setFont(ui_font(20, True, display=True))
        lab2.setStyleSheet("color: white;")
        eh.addWidget(lab2)

        self.d_ep_count = QLabel("0 episodes")
        self.d_ep_count.setFont(ui_font(12, True))
        self.d_ep_count.setStyleSheet(
            "background: rgba(255, 255, 255, 0.09); color: rgba(255, 255, 255, 0.65);"
            "border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 10px; padding: 4px 10px;"
        )
        eh.addWidget(self.d_ep_count)
        eh.addSpacing(6)

        self.d_season_wrap = QWidget()
        self.d_season_lay = QHBoxLayout(self.d_season_wrap)
        self.d_season_lay.setContentsMargins(0, 0, 0, 0)
        self.d_season_lay.setSpacing(8)
        self.d_season_grp = QButtonGroup(self.d_season_wrap)
        self.d_season_grp.setExclusive(True)
        eh.addWidget(self.d_season_wrap)
        eh.addStretch(1)

        self.d_ep_search = QLineEdit()
        self.d_ep_search.setPlaceholderText("Filter episodes…")
        self.d_ep_search.setClearButtonEnabled(True)
        self.d_ep_search.setFixedWidth(230)
        self.d_ep_search.setFixedHeight(36)
        self.d_ep_search.setStyleSheet(
            "QLineEdit { background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.14);"
            " border-radius: 18px; padding: 0 16px; color: white; font-size: 13px; }"
            "QLineEdit:hover { background: rgba(255, 255, 255, 0.13); border-color: rgba(255, 255, 255, 0.25); }"
            "QLineEdit:focus { background: rgba(18, 20, 28, 0.95); border: 1.5px solid #e50914; }"
        )
        self.d_ep_search.textChanged.connect(self._on_ep_filter)
        eh.addWidget(self.d_ep_search)

        self.d_ep_order = QPushButton("↑  Oldest first")
        self.d_ep_order.setObjectName("glassPill")
        self.d_ep_order.setFixedHeight(36)
        self.d_ep_order.setCursor(Qt.CursorShape.PointingHandCursor)
        self.d_ep_order.setToolTip("Toggle episode sort order")
        self.d_ep_order.clicked.connect(self._toggle_ep_order)
        eh.addWidget(self.d_ep_order)
        bl2.addWidget(ep_bar)

        self.d_eps_lay = QVBoxLayout()
        self.d_eps_lay.setSpacing(10)
        bl2.addLayout(self.d_eps_lay)
        bl2.addStretch(1)
        lay.addWidget(body, 1)

        self.d_scroll.setWidget(content)
        return self.d_scroll

    def open_settings(self) -> None:
        dlg = SettingsDialog(self)
        dlg.exec()

    def check_for_updates(self, manual: bool = False) -> None:
        src = (self.cfg["ui"].get("update_url") or DEFAULT_UPDATE_URL).strip()
        if not src:
            if manual:
                self.toast("Set an Update Server URL or GitHub Repo in Settings first")
            return
        if self.update_worker and self.update_worker.isRunning():
            if manual:
                self.toast("Already checking for updates…")
            return
        if manual:
            self.toast("Checking for OTA updates…")
        self.update_worker = UpdateWorker(src, auto_apply=True, manual=manual)
        self.update_worker.checked.connect(lambda info, m=manual: self._on_update_checked(info, m))
        self.update_worker.downloaded.connect(self._on_update_downloaded)
        self.update_worker.failed.connect(self._on_update_failed)
        self.update_worker.start()

    def _on_update_checked(self, info: dict, manual: bool) -> None:
        if not info.get("available"):
            if manual:
                self.toast(f"You are on the latest version (v{APP_VERSION})")
        else:
            sz_kb = (info.get("size") or 35840) / 1024
            self.status.setText(f"Downloading OTA update v{info['version']} (~{sz_kb:.0f} KB)…")

    def _on_update_downloaded(self, new_ver: str, notes: str) -> None:
        self.pending_update_ver = new_ver
        self.status.setText(f"Update v{new_ver} installed · Restart to apply")
        if hasattr(self, "nav") and self.nav and hasattr(self.nav, "btn_update"):
            self.nav.btn_update.setText(f"↻  Update Ready (v{new_ver})")
            self.nav.btn_update.setToolTip(
                f"OTA Update v{new_ver} downloaded!\n{notes or 'Click to restart and apply immediately.'}"
            )
            self.nav.btn_update.show()
        self.toast(f"Update v{new_ver} ready! Click 'Update Ready' in top bar to restart.", 4500)

    def _on_update_failed(self, err: str, manual: bool) -> None:
        if manual:
            QMessageBox.warning(self, "Update Check Failed", f"Could not check for updates:\n\n{err}")

    def export_update_bundle(self) -> None:
        try:
            zp, mp = build_release_bundle()
            kb = zp.stat().st_size / 1024
            self.toast(f"Built OTA bundle: {kb:.1f} KB ({zp.parent.name}/)", 3800)
            open_path(str(zp.parent))
        except Exception as e:
            QMessageBox.warning(self, "Build Bundle Failed", str(e))

    def restart_app(self) -> None:
        self.save_all()
        try:
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable] + sys.argv[1:])
            else:
                launcher = Path(__file__).resolve().parent.parent.parent / "anime_libraryV6.py"
                if launcher.is_file():
                    subprocess.Popen([sys.executable, str(launcher)] + sys.argv[1:])
                else:
                    subprocess.Popen([sys.executable, "-m", "AniLibV6"] + sys.argv[1:])
        except Exception as e:
            QMessageBox.warning(self, "Restart failed", str(e))
            return
        QApplication.quit()

    def save_all(self) -> None:
        save_json(CONFIG_FILE, self.cfg)
        save_json(CACHE_FILE, self.cache)
        self.update_nav_resume()

    def toast(self, text: str, ms: int = 2800) -> None:
        self.toast_w.show_message(text, ms)

    def set_animations(self, on: bool) -> None:
        T.animations = bool(on)
        self.cfg["ui"]["animations"] = bool(on)
        self.save_all()
        self.toast("Animations enabled" if on else "Animations reduced")

    def replay_intro(self) -> None:
        if self.intro and shiboken6.isValid(self.intro):
            self.intro.deleteLater()
        self.intro = NetflixIntro(self.root, self)
        self.root.intro = self.intro
        self.intro.setGeometry(0, 0, self.root.width(), self.root.height())
        self.intro.start()

    def choose_root(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "Select Anime Library Folder", self.cfg.get("root", ""))
        if p and p != self.cfg.get("root"):
            self.cfg["root"] = p
            self.save_all()
            self.start_scan()

    def choose_player(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Select Player Executable", self.cfg.get("player", ""))
        if p:
            self.cfg["player"] = p
            self.save_all()
            self.toast(f"Player: {Path(p).name}")

    def auto_player(self) -> None:
        p = find_player()
        if p:
            self.cfg["player"] = p
            self.save_all()
            self.toast(f"Detected: {p}")
        else:
            QMessageBox.information(
                self, "Not found", "Neither mpv nor VLC was found in standard locations."
            )

    def frames_enabled(self) -> bool:
        return bool(self.cfg["ui"].get("frames", True) and find_ffmpeg(self.ffmpeg_path()))

    def ffmpeg_path(self) -> str:
        return self.cfg["ui"].get("ffmpeg") or ""

    def choose_ffmpeg(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Select ffmpeg executable", self.ffmpeg_path())
        if p:
            self.cfg["ui"]["ffmpeg"] = p
            self.save_all()
            self.toast(f"FFmpeg set: {Path(p).name}")
            self.set_frames(True)

    def set_frames(self, on: bool) -> None:
        ff = find_ffmpeg(self.ffmpeg_path())
        if on and not ff:
            QMessageBox.information(
                self,
                "FFmpeg needed",
                "Video frame thumbnails require FFmpeg. Please install it or point to ffmpeg.exe.",
            )
            return
        self.cfg["ui"]["frames"] = bool(on)
        self.save_all()
        if on:
            self.queue_all_frames()
            self.toast("Frame thumbnails enabled")
        else:
            if self.frame_worker:
                self.frame_worker.stop()
            self.toast("Frame thumbnails off (using banner crops)")
            self.refresh_views()

    def clear_frames(self) -> None:
        if self.frame_worker:
            self.frame_worker.stop()
        if FRAME_DIR.exists():
            for f in FRAME_DIR.iterdir():
                try:
                    f.unlink()
                except OSError:
                    pass
        self.toast("Cleared thumbnail cache")
        if self.frames_enabled():
            self.queue_all_frames()
        else:
            self.refresh_views()

    def queue_all_frames(self) -> None:
        if not self.frames_enabled():
            return
        vids = [ep.path for e in self.entries for ep in e.episodes]
        self.queue_frames(vids, front=False)

    def queue_frames(self, videos: list[str], front: bool = False) -> None:
        if not self.frames_enabled():
            return
        seen = set(self.frame_queue)
        ff = find_ffmpeg(self.ffmpeg_path())
        if not ff:
            return
        add = [v for v in videos if v not in seen]
        if not add:
            return
        if front:
            for v in reversed(add):
                self.frame_queue.appendleft(v)
        else:
            self.frame_queue.extend(add)
        if self.frame_worker is None or not self.frame_worker.isRunning():
            self.frame_worker = FrameWorker(ff, self.frame_queue)
            self.frame_worker.frame_ready.connect(self.on_frame_ready)
            self.frame_worker.progress.connect(
                lambda d, t: self.status.setText(f"Extracting thumbnails… ({d}/{t})")
            )
            self.frame_worker.finished.connect(self.on_frames_done)
            self.frame_worker.start()

    def on_frame_ready(self, video: str, jpg: str) -> None:
        if not self.frame_timer.isActive():
            self.frame_timer.start()

    def _refresh_frames_view(self) -> None:
        if self.stack.currentIndex() == 2 and self.cur:
            self.populate_episodes(animate=False)

    def on_frames_done(self) -> None:
        self.frame_worker = None
        self.status.setText("")
        if self.stack.currentIndex() == 2 and self.cur:
            self.populate_episodes(animate=False)

    def start_scan(self, rematch: bool = False) -> None:
        root = self.cfg.get("root")
        if not root or not Path(root).is_dir():
            self.rebuild_home()
            self.refresh_browse()
            if (
                T.animations
                and self.root.intro
                and shiboken6.isValid(self.root.intro)
            ):
                self.root.intro.finished.connect(
                    lambda: QTimer.singleShot(60, self.choose_root)
                )
            else:
                QTimer.singleShot(60, self.choose_root)
            return

        self.status.setText("Scanning library folder…")
        QApplication.processEvents()
        self.entries = scan_library(root)
        self.by_path = {e.path: e for e in self.entries}

        if rematch:
            self.cfg["matches"] = {
                p: m for p, m in self.cfg.get("matches", {}).items()
                if isinstance(m, dict) and m.get("manual")
            }
            self.cache["search"] = {}

        self.hero_dirty = True
        jobs = []
        for e in self.entries:
            m_val = self.cfg.get("matches", {}).get(e.path)
            forced_id = None
            if isinstance(m_val, dict):
                forced_id = m_val.get("id")
            elif isinstance(m_val, (int, str)):
                try:
                    forced_id = int(m_val)
                except ValueError:
                    forced_id = None

            if forced_id is not None:
                m = self.cache["media"].get(str(forced_id))
                if m and media_ready(m):
                    e.media = m
                    continue
                jobs.append((e.path, e.query, forced_id))
            else:
                cands = self.cache["search"].get(e.query)
                if cands is not None:
                    matched = best_match(
                        e.query,
                        [self.cache["media"][str(i)] for i in cands if str(i) in self.cache["media"]],
                    )
                    if matched and media_ready(matched):
                        e.media = matched
                        continue
                jobs.append((e.path, e.query, None))

        self.loading_paths = {p for p, _, _ in jobs}
        self._rebuild_media_index()
        self.rebuild_genre_chips()
        self.rebuild_home()
        self.refresh_browse()
        if not self._restored:
            self._restored = True
            self.restore_page()
        if jobs:
            self.queue_jobs(jobs)
        else:
            self.status.setText(f"Ready · {len(self.entries)} anime")
            self.queue_all_frames()

    def queue_jobs(self, jobs: list) -> None:
        self.pending_jobs = jobs
        if not self.worker or not self.worker.isRunning():
            self.run_worker()

    def run_worker(self) -> None:
        if not self.pending_jobs:
            self.restore_page()
            self.queue_all_frames()
            return
        jobs, self.pending_jobs = self.pending_jobs, []
        self.worker = MetaWorker(jobs, self.cache["media"], self.cache["search"])
        self.worker.progress.connect(lambda i, tot, name: self.status.setText(f"Fetching metadata ({i}/{tot}): {name}"))
        self.worker.result.connect(self.on_result)
        self.worker.finished.connect(self.on_worker_done)
        self.worker.start()

    def on_result(self, path: str, query: str, media: dict | None, results: list | None, ok: bool) -> None:
        self.loading_paths.discard(path)
        if ok and media:
            mid = str(media["id"])
            self.cache["media"][mid] = media
            if results is not None:
                self.cache["search"][query] = [m["id"] for m in results]
                for m in results:
                    self.cache["media"].setdefault(str(m["id"]), m)
            e = self.by_path.get(path)
            if e:
                e.media = media
                e.__post_init__()
                self._rebuild_media_index()
                self.fresh.add(path)
                self.hero_dirty = True
                self.refresh_timer.start()
        self.save_all()

    def on_worker_done(self) -> None:
        self.worker = None
        if self.pending_jobs:
            self.run_worker()
            return
        self.status.setText(f"Ready · {len(self.entries)} anime")
        self.save_all()
        self.refresh_views()
        self.restore_page()
        self.queue_all_frames()

    def closeEvent(self, ev) -> None:
        if self.player and self.player.entry is not None:
            self.player.save_progress()
        if self.worker:
            self.worker.stop()
            self.worker.wait(1200)
        if self.frame_worker:
            self.frame_worker.stop()
            self.frame_worker.wait(1200)
        self.cfg["ui"]["geometry"] = self.saveGeometry().toBase64().data().decode()
        self.cfg["ui"]["last_page"] = self.stack.currentIndex()
        if self.cur:
            self.cfg["ui"]["last_path"] = self.cur.path
        self.save_all()
        super().closeEvent(ev)

    def restore_page(self) -> None:
        if self._restored:
            return
        self._restored = True
        lp = self.cfg["ui"].get("last_page", 0)
        lpath = self.cfg["ui"].get("last_path")
        if lp == 2 and lpath and lpath in self.by_path:
            self.show_detail(lpath, push=False, animate=False)
        elif lp == 1:
            self.show_browse(push=False)
        else:
            self.show_home()

    def _rebuild_media_index(self) -> None:
        self.by_media_id = {}
        for e in self.entries:
            if e.media and e.media.get("id"):
                try:
                    self.by_media_id[int(e.media["id"])] = e
                except (ValueError, TypeError):
                    pass

    def entry_relations(self, entry: Entry) -> list[tuple[str, dict, Entry | None]]:
        """Return chronological/related anime for entry: (relationType, node_dict, library_entry_or_None)."""
        if not entry or not entry.media:
            return []
        rels = media_relations(entry.media)
        priority = {"PREQUEL": 0, "SEQUEL": 1, "PARENT": 2, "SIDE_STORY": 3, "SPIN_OFF": 4, "ALTERNATIVE": 5}
        out = []
        for r in rels:
            rtype = r.get("relationType") or "RELATED"
            if rtype not in priority:
                continue
            lib_entry = self.by_media_id.get(int(r["id"]))
            if lib_entry is entry:
                continue
            if rtype in ("PREQUEL", "SEQUEL") or lib_entry is not None:
                out.append((rtype, r, lib_entry))
        out.sort(key=lambda x: (priority.get(x[0], 99), 0 if x[2] is not None else 1))
        return out

    def sequel_entry(self, entry: Entry) -> Entry | None:
        """Return the direct SEQUEL Entry in the local library if available."""
        for rtype, _, lib_entry in self.entry_relations(entry):
            if rtype == "SEQUEL" and lib_entry is not None:
                return lib_entry
        return None

    def prequel_entry(self, entry: Entry) -> Entry | None:
        """Return the direct PREQUEL Entry in the local library if available."""
        for rtype, _, lib_entry in self.entry_relations(entry):
            if rtype == "PREQUEL" and lib_entry is not None:
                return lib_entry
        return None

    def prog(self, entry: Entry) -> dict:
        return self.cfg["progress"].setdefault(entry.path, {})

    def watched(self, entry: Entry) -> set[str]:
        return set(self.prog(entry).get("watched", []))

    def fraction(self, entry: Entry) -> float:
        n = len(entry.episodes)
        return (len(self.watched(entry) & entry._ep_keys) / n) if n else 0.0

    def next_episode(self, entry: Entry) -> Episode | None:
        w = self.watched(entry)
        for ep in entry.episodes:
            if ep.key not in w:
                return ep
        return entry.episodes[0] if entry.episodes else None

    def continue_list(self) -> list[tuple[Entry, Episode]]:
        items = []
        seen_paths: set[str] = set()
        for e in self.entries:
            p = self.prog(e)
            if not p:
                continue
            f = self.fraction(e)
            if 0 < f < 1:
                ep = self.next_episode(e)
                if ep:
                    items.append((p.get("last", 0), e, ep))
                    seen_paths.add(e.path)
            elif f >= 1:
                seq = self.sequel_entry(e)
                if seq and seq.path not in seen_paths and self.fraction(seq) == 0:
                    ep = self.next_episode(seq)
                    if ep:
                        items.append((p.get("last", 0), seq, ep))
                        seen_paths.add(seq.path)
        items.sort(key=lambda t: -t[0])
        return [(e, ep) for _, e, ep in items if ep]

    def last_watched(self) -> tuple[Entry, Episode] | None:
        items = self.continue_list()
        if items:
            return items[0]
        latest_entry, latest_time = None, 0
        for e in self.entries:
            p = self.prog(e)
            t = p.get("last", 0)
            if t > latest_time:
                latest_time = t
                latest_entry = e
        if latest_entry:
            nxt = self.next_episode(latest_entry) or (latest_entry.episodes[0] if latest_entry.episodes else None)
            if nxt:
                return (latest_entry, nxt)
        return None

    def resume_last_watched(self) -> None:
        lw = self.last_watched()
        if lw:
            entry, ep = lw
            self.play(entry, ep)
        else:
            self.toast("No watch history to resume")

    def update_nav_resume(self) -> None:
        if not hasattr(self, "nav") or not self.nav or not hasattr(self.nav, "btn_resume"):
            return
        lw = self.last_watched()
        if lw:
            entry, ep = lw
            short_title = entry.title
            if len(short_title) > 20:
                short_title = short_title[:18].rstrip() + "…"
            ep_num = f"Ep {ep.number}" if ep.number is not None else Path(ep.key).stem
            self.nav.btn_resume.setText(f"▶  Resume: {short_title}  ({ep_num})")
            self.nav.btn_resume.setToolTip(
                f"Continue watching {entry.title} — {self.ep_label(entry, ep)}\nClick to play instantly (Space on Home)"
            )
            self.nav.btn_resume.show()
        else:
            self.nav.btn_resume.hide()

    def mark_watched(self, entry: Entry, ep: Episode, value: bool = True) -> None:
        w = self.watched(entry)
        if value:
            w.add(ep.key)
        else:
            w.discard(ep.key)
        self.prog(entry)["watched"] = sorted(w)
        self.prog(entry)["last"] = time.time()
        self.save_all()

    def mark_all_watched(self) -> None:
        if not self.cur:
            return
        self.prog(self.cur)["watched"] = sorted(e.key for e in self.cur.episodes)
        self.prog(self.cur)["last"] = time.time()
        self.save_all()
        self.populate_episodes()
        self.refresh_timer.start()
        self.toast("Marked all watched")

    def reset_progress(self) -> None:
        if not self.cur:
            return
        self.cfg["progress"].pop(self.cur.path, None)
        self.save_all()
        self.populate_episodes()
        self.refresh_timer.start()
        self.toast("Reset progress")

    def ep_label(self, entry: Entry, ep: Episode) -> str:
        s = f"S{ep.season} " if (entry._multi_season and ep.season is not None) else ""
        if ep.number is not None:
            return f"{s}Episode {ep.number}"
        return f"{s}{Path(ep.key).stem}"

    def play_label(self, e: Entry) -> str:
        f = self.fraction(e)
        if f <= 0:
            return "▶  Play"
        if f >= 1:
            return "▶  Watch again"
        nxt = self.next_episode(e)
        return f"▶  Resume {self.ep_label(e, nxt)}" if nxt else "▶  Play"

    def play_next(self, entry: Entry) -> None:
        nxt = self.next_episode(entry)
        if nxt:
            self.play(entry, nxt)

    def builtin_enabled(self) -> bool:
        if not HAVE_MM:
            return False
        return bool(self.cfg["ui"].get("builtin_player", True))

    def set_builtin(self, on: bool) -> None:
        if on and not HAVE_MM:
            QMessageBox.information(
                self, "Not available", "QtMultimedia is not available. Using external player only."
            )
            return
        self.cfg["ui"]["builtin_player"] = bool(on)
        self.save_all()
        self.toast("Built-in player active" if on else "External player active")

    def play(self, entry: Entry, ep: Episode) -> None:
        if self.builtin_enabled():
            self.play_builtin(entry, ep)
        else:
            self.play_external(entry, ep)

    def play_external(self, entry: Entry, ep: Episode) -> None:
        self.hide_preview(now=True)
        player = self.cfg.get("player") or find_player()
        self.prog(entry)["last"] = time.time()
        try:
            if player and os.path.exists(player):
                name = Path(player).stem.lower()
                cmd = [player, str(ep.path)]
                if ep.sub and name in ("mpv", "vlc"):
                    cmd.insert(1, f"--sub-file={ep.sub}")
                if name == "mpv":
                    cmd.insert(1, "--no-terminal")
                flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
                subprocess.Popen(
                    cmd,
                    creationflags=flags,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                open_path(ep.path)
        except Exception as e:
            QMessageBox.critical(self, "Could not start player", f"{player or ep.path}\n\n{e}")

    def get_pos(self, entry: Entry, ep: Episode) -> tuple[int, int]:
        pos = self.prog(entry).get("pos", {}).get(ep.key)
        return (int(pos["t"]), int(pos["d"])) if (pos and pos.get("d")) else (0, 0)

    def set_pos(self, entry: Entry, ep: Episode, t: int, d: int) -> None:
        m = self.prog(entry).setdefault("pos", {})
        if d > 0 and t >= 3000 and t < d * 0.92:
            m[ep.key] = {"t": int(t), "d": int(d), "at": time.time()}
        else:
            m.pop(ep.key, None)
        self.save_all()

    def ep_frac(self, entry: Entry, ep: Episode) -> float:
        t, d = self.get_pos(entry, ep)
        return (t / d) if d else 0.0

    def resume_ms(self, entry: Entry, ep: Episode) -> int:
        t, _ = self.get_pos(entry, ep)
        return t

    def play_builtin(self, entry: Entry, ep: Episode) -> None:
        if not self.player:
            self.play_external(entry, ep)
            return
        self.hide_preview(now=True)
        self._player_from = (self.stack.currentIndex(), self.cur)
        self.nav.hide()
        self.stack.go(3, animate=False)
        self.player.setFocus()
        try:
            self.player.open(entry, ep, self.resume_ms(entry, ep))
        except Exception as e:
            self.player_failed(str(e))

    def exit_player(self) -> None:
        if not self.player:
            return
        self.player.stop_playback()
        if self.isFullScreen():
            self.showNormal()
        self.nav.show()
        page, entry = self._player_from
        if page == 2 and entry and entry.path in self.by_path:
            self.show_detail(entry.path, push=False, animate=False)
        elif page == 1:
            self.show_browse(push=False)
        else:
            self.show_home()
        self.update_nav_resume()

    def player_failed(self, msg: str) -> None:
        self.toast(f"Built-in player failed ({msg}) — opening external player")
        entry, ep = (self.player.entry, self.player.ep) if self.player else (None, None)
        self.exit_player()
        if entry and ep:
            self.play_external(entry, ep)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            if self._was_max:
                self.showMaximized()
            if self.player:
                self.player.btn_full.active = False
                self.player.btn_full.update()
        else:
            self._was_max = self.isMaximized()
            self.showFullScreen()
            if self.player:
                self.player.btn_full.active = True
                self.player.btn_full.update()

    def fix_match(self, entry: Entry) -> None:
        dlg = MatchDialog(entry.query, self)
        if dlg.exec() and dlg.selected:
            m = dlg.selected
            self.cfg["matches"][entry.path] = m["id"]
            self.cache["media"][str(m["id"])] = m
            self.save_all()
            entry.media = m
            entry.__post_init__()
            self._rebuild_media_index()
            self.fresh.add(entry.path)
            self.hero_dirty = True
            self.queue_jobs([(entry.path, entry.query, m["id"])])
            self.refresh_views()
            if self.cur is entry:
                self.show_detail(entry.path, push=False)
            self.toast(f"Matched: {media_title(m)}")

    def is_fav(self, entry: Entry) -> bool:
        return entry.path in self.cfg.get("favorites", [])

    def toggle_fav(self, entry: Entry) -> None:
        favs = self.cfg.setdefault("favorites", [])
        if entry.path in favs:
            favs.remove(entry.path)
            self.toast(f"Removed from My List: {entry.title}")
        else:
            favs.append(entry.path)
            self.toast(f"Added to My List: {entry.title}")
        self.save_all()
        self.refresh_timer.start()

    def _toggle_cur_fav(self) -> None:
        if self.cur:
            self.toggle_fav(self.cur)
            self._sync_detail_fav()

    def _sync_detail_fav(self) -> None:
        if not self.cur:
            return
        fav = self.is_fav(self.cur)
        self.d_fav.setText("♥  In My List" if fav else "♡  My List")
        self.d_fav.setStyleSheet(f"color: {T.ACCENT}; border-color: {T.ACCENT};" if fav else "")

    def pick_random(self) -> None:
        if not self.entries:
            return
        e = random.choice(self.entries)
        self.show_detail(e.path)
        self.toast(f"Surprise: {e.title}")

    def _cur_state(self) -> tuple[int, Entry | None]:
        return (self.stack.currentIndex(), self.cur)

    def _push(self) -> None:
        st = self._cur_state()
        if not self.back_stack or self.back_stack[-1] != st:
            self.back_stack.append(st)

    def _switch(self, page: int) -> None:
        self.nav.set_page(page, fav_only=self.b_fav_only)
        self.stack.go(page, animate=True)
        self.update_nav_scroll()
        self.preview.hide_animated(now=True)

    def show_home(self) -> None:
        if self.stack.currentIndex() != 0:
            self._push()
        self.cur = None
        self.search_edit.clear()
        self.b_fav_only = False
        self._switch(0)
        self.rebuild_home()
        self.home_scroll.verticalScrollBar().setValue(0)
        self.update_nav_resume()

    def show_browse(self, push: bool = True, fav_only: bool | None = None) -> None:
        if push and self.stack.currentIndex() != 1:
            self._push()
        self.cur = None
        if fav_only is not None:
            self.b_fav_only = fav_only
        self._switch(1)
        self.refresh_browse()

    def open_entry(self, entry: Entry) -> None:
        self.show_detail(entry.path)

    def go_back(self) -> None:
        if not self.back_stack:
            self.show_home()
            return
        page, entry = self.back_stack.pop()
        if page == 2 and entry and entry.path in self.by_path:
            self.show_detail(entry.path, push=False)
        elif page == 1:
            self.show_browse(push=False)
        else:
            self.show_home()

    def current_scroll(self) -> SmoothScrollArea | None:
        idx = self.stack.currentIndex()
        return (self.home_scroll, self.b_scroll, self.d_scroll)[idx] if 0 <= idx < 3 else None

    def page_wheel(self, e) -> None:
        a = self.current_scroll()
        if a:
            a.wheelEvent(e)

    def on_scroll(self, area: SmoothScrollArea, value: int) -> None:
        if area is self.current_scroll():
            self.nav.set_scrolled(value > 12)

    def update_nav_scroll(self) -> None:
        a = self.current_scroll()
        self.nav.set_scrolled(bool(a and a.verticalScrollBar().value() > 12))

    def nav_groups(self) -> list:
        idx = self.stack.currentIndex()
        if idx == 0:
            return self.home_groups
        if idx == 1:
            return self.b_grid.groups
        return []

    def nav_move(self, card: PosterCard, dx: int, dy: int) -> None:
        groups = self.nav_groups()
        pos = next(((r, c) for r, row in enumerate(groups) for c, k in enumerate(row) if k is card), None)
        if not pos:
            return
        r, c = pos
        if dy != 0:
            nr = r + dy
            if 0 <= nr < len(groups):
                row = groups[nr]
                target = row[min(c, len(row) - 1)]
                target.setFocus()
                self.reveal(target)
        elif dx != 0:
            row = groups[r]
            nc = c + dx
            if 0 <= nc < len(row):
                target = row[nc]
                target.setFocus()
                self.reveal(target)

    def reveal(self, card: PosterCard) -> None:
        if card.row:
            card.row.ensure_visible(card)
        a = self.current_scroll()
        if not a:
            return
        sb = a.verticalScrollBar()
        p = card.mapTo(a.widget(), QPoint(0, 0))
        top, bot = p.y() - 14, p.y() + card.height() + 14
        vt, vb = sb.value(), sb.value() + a.viewport().height()
        if top < vt:
            a.smooth_to(top)
        elif bot > vb:
            a.smooth_to(bot - a.viewport().height())

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if k == Qt.Key.Key_Space and not self.search_edit.hasFocus():
            if self.stack.currentIndex() == 0:
                self.resume_last_watched()
                return
            elif self.stack.currentIndex() == 2 and self.cur:
                self.play_next(self.cur)
                return
        if k == Qt.Key.Key_Slash and not self.search_edit.hasFocus():
            self.search_edit.setFocus()
            self.search_edit.selectAll()
            e.accept()
            return
        if k == Qt.Key.Key_Escape:
            if self.search_edit.hasFocus():
                self.search_edit.clear()
                self.search_edit.clearFocus()
                return
            if self.preview.isVisible():
                self.hide_preview(now=True)
                return
            if self.stack.currentIndex() != 0:
                self.go_back()
                return
        if k == Qt.Key.Key_R and not self.search_edit.hasFocus():
            self.pick_random()
            return
        if k == Qt.Key.Key_F and not self.search_edit.hasFocus() and self.cur:
            self._toggle_cur_fav()
            return
        if k == Qt.Key.Key_Comma and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.open_settings()
            return
        super().keyPressEvent(e)

    def card_entered(self, card: PosterCard) -> None:
        self._pv_target = card
        self.preview_hide_timer.stop()
        self.preview_timer.start(550)

    def card_left(self, card: PosterCard) -> None:
        if self._pv_target is card:
            self.preview_timer.stop()
            self.preview_hide_timer.start(140)

    def _show_preview(self) -> None:
        if self._pv_target and self._pv_target.isVisible() and self.stack.currentIndex() != 3:
            self.preview.show_for(self._pv_target)

    def _hide_preview_tick(self) -> None:
        if not self.preview.underMouse():
            self.preview.hide_animated()

    def hide_preview(self, now: bool = False) -> None:
        self.preview_timer.stop()
        self.preview_hide_timer.stop()
        self.preview.hide_animated(now=now)

    def card_menu(self, entry: Entry, global_pos: QPoint) -> None:
        self.hide_preview(now=True)
        m = QMenu(self)
        m.addAction("▶  Play next", lambda: self.play_next(entry))
        fav = self.is_fav(entry)
        m.addAction("♥  Remove from My List" if fav else "♡  Add to My List", lambda: self.toggle_fav(entry))

        seq = self.sequel_entry(entry)
        preq = self.prequel_entry(entry)
        if seq or preq:
            m.addSeparator()
            if seq:
                m.addAction(f"⏭  Open Sequel: {seq.title}", lambda s=seq: self.open_entry(s))
            if preq:
                m.addAction(f"⏮  Open Prequel: {preq.title}", lambda p=preq: self.open_entry(p))

        m.addSeparator()
        m.addAction("Mark all watched", lambda: self._quick_mark_all(entry))
        m.addAction("Reset progress", lambda: self._quick_reset(entry))
        m.addSeparator()
        m.addAction("Fix match…", lambda: self.fix_match(entry))
        m.addAction("Open folder", lambda: open_path(entry.path))
        m.exec(global_pos)

    def _quick_mark_all(self, entry: Entry) -> None:
        self.prog(entry)["watched"] = sorted(e.key for e in entry.episodes)
        self.prog(entry)["last"] = time.time()
        self.save_all()
        self.refresh_timer.start()
        self.toast(f"Marked all watched: {entry.title}")

    def _quick_reset(self, entry: Entry) -> None:
        self.cfg["progress"].pop(entry.path, None)
        self.save_all()
        self.refresh_timer.start()
        self.toast(f"Reset progress: {entry.title}")

    def refresh_views(self) -> None:
        self.rebuild_home()
        self.update_nav_resume()
        if self.stack.currentIndex() == 1:
            self.refresh_browse()
        if self.stack.currentIndex() == 2 and self.cur:
            self.show_detail(self.cur.path, push=False, animate=False)

    def make_card(self, e: Entry, subtitle: str = "", fade_in: bool = False, delay_ms: int = 40) -> PosterCard:
        loading = e.path in self.loading_paths and not e.media
        c = PosterCard(self, e, subtitle, loading=loading, fade_in=fade_in, delay_ms=delay_ms)
        return c

    def make_rows(self) -> list[tuple[str, list[Entry]]]:
        cont = [e for e, _ in self.continue_list()][:12]
        by_mtime = sorted(self.entries, key=lambda e: -e.mtime)
        rated = [e for e in self.entries if (e.media or {}).get("averageScore")]
        rated.sort(key=lambda e: -((e.media or {}).get("averageScore") or 0))

        by_genre = {}
        for e in self.entries:
            for g in (e.media or {}).get("genres") or []:
                by_genre.setdefault(g, []).append(e)

        top_genres = sorted(
            [g for g in by_genre if len(by_genre[g]) >= 3],
            key=lambda g: -len(by_genre[g]),
        )[:4]

        rows = []
        if cont:
            rows.append(("Continue Watching", cont))
        rows.append(("Recently Added", by_mtime[:18]))
        if rated:
            rows.append(("Top Rated", rated[:18]))
        for g in top_genres:
            rows.append((g, by_genre[g][:18]))
        return rows

    def featured(self) -> list[Entry]:
        cont = [e for e, _ in self.continue_list()][:1]
        rated = [e for e in self.entries if ((e.media or {}).get("averageScore") or 0) >= 75]
        rated.sort(key=lambda e: -((e.media or {}).get("averageScore") or 0))
        seen, cands = set(), []
        for e in cont + rated[:8] + self.entries[:8]:
            if e.path not in seen and (e.media or {}).get("bannerImage"):
                seen.add(e.path)
                cands.append(e)
            if len(cands) >= 7:
                break
        return cands or self.entries[:5]

    def hero_slides(self) -> list[dict]:
        cands = self.featured()
        slides = []
        for e in cands:
            m = e.media or {}
            pm = load_pixmap(m.get("_banner")) or load_pixmap(m.get("_cover"))
            chips = []
            if m.get("averageScore"):
                chips.append((f"★ {m['averageScore'] / 10:.1f}", True))
            if m.get("seasonYear"):
                chips.append((str(m["seasonYear"]), False))
            if m.get("format"):
                chips.append((m["format"].replace("_", " "), False))
            for g in (m.get("genres") or [])[:2]:
                chips.append((g, False))
            slides.append(
                {
                    "entry": e,
                    "title": e.title,
                    "desc": clean_desc(m.get("description")),
                    "pm": pm,
                    "tint": (m.get("coverImage") or {}).get("color"),
                    "chips": chips,
                }
            )
        return slides

    def rebuild_home(self) -> None:
        self.rebuild_genre_chips()
        featured_paths = [e.path for e in self.featured()]
        if featured_paths != self.hero_paths:
            self.hero_paths = featured_paths
            self.hero_dirty = True

        first_build = self._first_home_build
        self._first_home_build = False
        clear_layout(self.home_lay)

        if not self.entries:
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 180, 0, 40)
            bl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bl.setSpacing(14)

            t = QLabel("Your library is empty")
            t.setFont(ui_font(28, True, display=True))
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setStyleSheet(f"color: {T.TEXT};")

            s = QLabel("Pick the folder that contains one sub-folder per anime.")
            s.setStyleSheet(f"color: {T.MUTED}; font-size: 15px; font-weight: 400;")
            s.setAlignment(Qt.AlignmentFlag.AlignCenter)

            b = QPushButton("Choose library folder")
            b.setObjectName("primary")
            b.setMinimumHeight(44)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"background: {T.ACCENT}; color: #ffffff; border-radius: 12px; "
                f"padding: 10px 24px; font-weight: 600; font-size: 15px;"
            )
            b.clicked.connect(self.choose_root)

            bl.addWidget(t)
            bl.addWidget(s)
            bl.addSpacing(12)
            bl.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)

            self.home_lay.addWidget(box)
            self.home_lay.addStretch(1)
            self.home_groups = []
            self.hero = None
            return

        slides = self.hero_slides()

        if slides:
            self.hero = HeroBanner(self, slides, start=self.hero_index)
            self.home_lay.addWidget(self.hero)
            self.root.set_ambient(slides[self.hero.index].get("tint") or T.ACCENT)
        else:
            self.hero = None

        self.home_groups = []
        fresh = set(self.fresh)
        for title, elist in self.make_rows():
            if not elist:
                continue
            cards = []
            for i, e in enumerate(elist):
                sub = ""
                if title == "Continue Watching":
                    nxt = self.next_episode(e)
                    preq = self.prequel_entry(e)
                    if self.fraction(e) == 0 and preq and self.fraction(preq) >= 1:
                        sub = f"Next Season · Ep {nxt.number}" if (nxt and nxt.number is not None) else "Next Season"
                    elif nxt and nxt.number is not None:
                        sub = f"Ep {nxt.number}"
                cards.append(
                    self.make_card(
                        e,
                        sub,
                        fade_in=(first_build or e.path in fresh),
                        delay_ms=40 + i * 25,
                    )
                )
            row = Row(self, title, cards)
            self.home_lay.addWidget(row)
            self.home_groups.append(cards)

        self.fresh.clear()
        self.home_lay.addStretch(1)

    def on_status_chip(self, i: int) -> None:
        self.b_status = i
        self.refresh_browse()

    def rebuild_genre_chips(self) -> None:
        counts = {}
        for e in self.entries:
            for g in (e.media or {}).get("genres") or []:
                counts[g] = counts.get(g, 0) + 1
        sig = tuple(sorted(counts))
        if sig == self._genre_sig:
            return
        self._genre_sig = sig
        clear_layout(self.b_strip_lay)
        if self.b_genre not in counts:
            self.b_genre = None
        self._genre_chips = {}
        for g in sorted(counts):
            b = QPushButton(g)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setChecked(g == self.b_genre)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda checked, g=g: self.on_genre_chip(g, checked))
            self.b_strip_lay.addWidget(b)
            self._genre_chips[g] = b
        self.b_strip_lay.addStretch(1)
        self.b_strip.setVisible(bool(counts))

    def on_genre_chip(self, g: str, checked: bool) -> None:
        self.b_genre = g if checked else None
        for name, b in self._genre_chips.items():
            b.blockSignals(True)
            b.setChecked(name == self.b_genre)
            b.blockSignals(False)
        self.refresh_browse()

    def browse_entries(self) -> list[Entry]:
        q = norm(self.search_edit.text())
        favs = set(self.cfg.get("favorites", [])) if self.b_fav_only else None
        res = []
        for e in self.entries:
            if favs is not None and e.path not in favs:
                continue
            m = e.media or {}
            if q and q not in e._search_blob:
                continue
            if self.b_genre and self.b_genre not in (m.get("genres") or []):
                continue
            f = self.fraction(e)
            if self.b_status == 1 and f > 0:
                continue
            if self.b_status == 2 and not (0 < f < 1):
                continue
            if self.b_status == 3 and f < 1:
                continue
            res.append(e)

        s = self.b_sort.currentIndex()
        if s == 0:
            res.sort(key=lambda e: e.title.lower())
        elif s == 1:
            res.sort(key=lambda e: -e.mtime)
        elif s == 2:
            res.sort(key=lambda e: -((e.media or {}).get("averageScore") or 0))
        elif s == 3:
            res.sort(key=lambda e: -((e.media or {}).get("seasonYear") or 0))
        else:
            res.sort(key=lambda e: -self.fraction(e))
        return res

    def refresh_browse(self) -> None:
        res = self.browse_entries()
        q = self.search_edit.text().strip()
        if q:
            self.b_title.setText(f"Results for “{q}”")
        elif self.b_fav_only:
            self.b_title.setText("♥  My List")
        else:
            self.b_title.setText("Browse")
        self.b_count.setText(f"{len(res)} anime")
        fresh = set(self.fresh)
        self.b_grid.set_cards([self.make_card(e, "", e.path in fresh) for e in res])

    def run_search(self) -> None:
        if self.search_edit.text().strip() and self.stack.currentIndex() != 1:
            self.show_browse(fav_only=False)
            return
        if self.stack.currentIndex() == 1:
            self.refresh_browse()

    def show_detail(self, path: str, push: bool = True, animate: bool = True) -> None:
        e = self.by_path.get(path)
        if not e:
            return
        self.hide_preview(now=True)
        if push and (self.stack.currentIndex() != 2 or self.cur is not e):
            self._push()
        self.cur = e
        m = e.media or {}
        self.d_title.setText(e.title)
        tint_col = (m.get("coverImage") or {}).get("color")
        self.d_banner.set_content(load_pixmap(m.get("_banner")), tint_col)
        self.root.set_ambient(tint_col or tint_for(e.title))

        meta = [str(m["seasonYear"])] if m.get("seasonYear") else []
        if m.get("format"):
            meta.append(m["format"].replace("_", " "))
        if m.get("averageScore"):
            meta.append(f"★ {m['averageScore'] / 10:.1f}")
        if m.get("status"):
            meta.append(m["status"].replace("_", " ").title())
        if m.get("episodes"):
            meta.append(f"{m['episodes']} episodes total")
        meta.append(f"{len(e.episodes)} on disk")
        self.d_meta.setText("   ·   ".join(meta))

        pm = cover_pixmap(m.get("_cover"), 210, 308)
        if pm is None:
            pm = QPixmap(210, 308)
            pm.fill(tint_for(e.title))
        self.d_poster.setPixmap(rounded_pixmap(pm, 14))

        self.d_genres.setText(
            "  ·  ".join(m.get("genres") or []) if m else "Not matched on AniList — use “Fix match…”"
        )
        self.d_desc.setText(clean_desc(m.get("description")) or e.name)
        self._sync_detail_fav()
        self.d_season = None
        self.d_ep_search.blockSignals(True)
        self.d_ep_search.clear()
        self.d_ep_search.blockSignals(False)
        self.d_ep_query = ""

        if self.frames_enabled():
            self.queue_frames([ep.path for ep in e.episodes], front=True)

        self.populate_relations(e)
        self.populate_episodes(animate=animate)
        self.d_scroll.verticalScrollBar().setValue(0)
        self._switch(2)
        if animate and T.animations:
            self.d_banner.zoom_in()

    def _on_ep_filter(self, txt: str) -> None:
        self.d_ep_query = norm(txt)
        self.populate_episodes(animate=False)

    def _toggle_ep_order(self) -> None:
        self.d_ep_reverse = not self.d_ep_reverse
        self.d_ep_order.setText("↓  Newest first" if self.d_ep_reverse else "↑  Oldest first")
        self.populate_episodes(animate=True)

    def _ep_card(self, e: Entry, ep: Episode, is_next: bool, big: bool = False, idx: int | None = None, watched_set: set | None = None) -> EpisodeCard:
        w = ep.key in (watched_set if watched_set is not None else self.watched(e))
        m = e.media or {}
        tint = (m.get("coverImage") or {}).get("color") or tint_for(e.title).name()
        if idx is None:
            try:
                idx = e.episodes.index(ep)
            except ValueError:
                idx = 0
        thumb = frame_thumb(ep.path, big) if self.frames_enabled() else None
        if thumb is None:
            thumb = episode_thumb(m, idx, len(e.episodes), big)
        card = EpisodeCard(
            self.ep_label(e, ep),
            Path(ep.key).name,
            ep.number,
            w,
            is_next,
            bool(ep.sub),
            tint,
            big,
            thumb,
            0.0 if w else self.ep_frac(e, ep),
        )
        card.clicked.connect(lambda e=e, ep=ep: self.play(e, ep))
        card.toggled.connect(
            lambda e=e, ep=ep, w=w: (
                self.mark_watched(e, ep, not w),
                self.populate_episodes(),
                self.refresh_timer.start(),
            )
        )
        return card

    def populate_episodes(self, animate: bool = False) -> None:
        e = self.cur
        if not e:
            return
        w = self.watched(e)
        nxt = self.next_episode(e)
        all_done = bool(e.episodes) and e._ep_keys.issubset(w)

        seasons = sorted({(ep.season or 1) for ep in e.episodes})
        if self.d_season not in seasons:
            self.d_season = (nxt.season or 1) if (nxt and (nxt.season or 1) in seasons) else seasons[0]

        for b in list(self.d_season_grp.buttons()):
            self.d_season_grp.removeButton(b)
        clear_layout(self.d_season_lay)
        self.d_season_wrap.setVisible(len(seasons) > 1)
        if len(seasons) > 1:
            for s in seasons:
                b = QPushButton(f"Season {s}")
                b.setObjectName("chip")
                b.setCheckable(True)
                b.setChecked(s == self.d_season)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda _=False, s=s: self.set_season(s))
                self.d_season_grp.addButton(b)
                self.d_season_lay.addWidget(b)

        clear_layout(self.d_next_lay)
        seq = self.sequel_entry(e)
        ep_idx = {id(ep): i for i, ep in enumerate(e.episodes)}
        if not all_done and nxt is not None:
            self.d_next_title.setText("Up Next")
            self.d_next_wrap.setVisible(True)
            self.d_next_lay.addWidget(
                self._ep_card(e, nxt, True, big=True, idx=ep_idx.get(id(nxt), 0), watched_set=w)
            )
        elif all_done and seq is not None and seq.episodes:
            seq_w = self.watched(seq)
            seq_nxt = self.next_episode(seq) or seq.episodes[0]
            seq_idx = {id(ep): i for i, ep in enumerate(seq.episodes)}
            self.d_next_title.setText(f"Up Next in Sequel  ·  {seq.title}")
            self.d_next_wrap.setVisible(True)
            self.d_next_lay.addWidget(
                self._ep_card(seq, seq_nxt, True, big=True, idx=seq_idx.get(id(seq_nxt), 0), watched_set=seq_w)
            )
        else:
            self.d_next_wrap.setVisible(False)

        clear_layout(self.d_eps_lay)
        eps = [ep for ep in e.episodes if (ep.season or 1) == self.d_season]
        if self.d_ep_query:
            q = self.d_ep_query
            eps = [ep for ep in eps if q in norm(self.ep_label(e, ep)) or q in norm(Path(ep.key).stem)]
        if self.d_ep_reverse:
            eps = list(reversed(eps))

        if hasattr(self, "d_ep_count"):
            if self.d_ep_query:
                self.d_ep_count.setText(f"{len(eps)} of {len(e.episodes)} eps")
            else:
                self.d_ep_count.setText(f"{len(eps)} episode{'s' if len(eps) != 1 else ''}")

        for i, ep in enumerate(eps):
            card = self._ep_card(
                e, ep, ep is nxt and not all_done, idx=ep_idx.get(id(ep), 0), watched_set=w
            )
            if animate and T.animations and i < 14:
                card.start_appear(120 + i * 45)
            self.d_eps_lay.addWidget(card)

        self.d_play.setText(self.play_label(e))

    def set_season(self, s: int) -> None:
        self.d_season = s
        self.populate_episodes(animate=True)

    def _relation_card(self, rtype: str, node: dict, lib_entry: Entry | None) -> QWidget:
        card = QFrame()
        card.setObjectName("relCard")
        in_lib = lib_entry is not None
        is_seq = rtype == "SEQUEL"
        is_preq = rtype == "PREQUEL"
        border_col = "rgba(229, 9, 20, 0.55)" if (in_lib and is_seq) else (
            "rgba(48, 209, 88, 0.45)" if in_lib else "rgba(255, 255, 255, 0.10)"
        )
        bg_col = "rgba(229, 9, 20, 0.10)" if (in_lib and is_seq) else (
            "rgba(255, 255, 255, 0.06)" if in_lib else "rgba(255, 255, 255, 0.03)"
        )
        hover_bg = "rgba(229, 9, 20, 0.18)" if (in_lib and is_seq) else (
            "rgba(255, 255, 255, 0.12)" if in_lib else "rgba(255, 255, 255, 0.05)"
        )
        card.setStyleSheet(
            f"QFrame#relCard {{"
            f"  background: {bg_col};"
            f"  border: 1.5px solid {border_col};"
            f"  border-radius: 18px;"
            f"}}"
            f"QFrame#relCard:hover {{"
            f"  background: {hover_bg};"
            f"}}"
        )
        card.setFixedHeight(106)
        card.setMinimumWidth(290)
        card.setMaximumWidth(440)
        if in_lib:
            card.setCursor(Qt.CursorShape.PointingHandCursor)

        hl = QHBoxLayout(card)
        hl.setContentsMargins(14, 12, 16, 12)
        hl.setSpacing(14)

        # Mini poster thumbnail if in library
        if in_lib:
            m = lib_entry.media or {}
            pm = cover_pixmap(m.get("_cover"), 56, 80)
            if pm is None:
                pm = QPixmap(56, 80)
                pm.fill(tint_for(lib_entry.title))
            poster = QLabel()
            poster.setFixedSize(56, 80)
            poster.setPixmap(rounded_pixmap(pm, 8))
            hl.addWidget(poster)

        vl = QVBoxLayout()
        vl.setSpacing(4)
        vl.setContentsMargins(0, 0, 0, 0)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        badge_map = {
            "PREQUEL": "←  PREQUEL",
            "SEQUEL": "SEQUEL  →",
            "PARENT": "MAIN STORY",
            "SIDE_STORY": "SIDE STORY",
            "SPIN_OFF": "SPIN-OFF",
            "ALTERNATIVE": "ALTERNATIVE",
        }
        b_txt = badge_map.get(rtype, rtype.replace("_", " "))
        lbl_type = QLabel(b_txt)
        lbl_type.setFont(ui_font(10, True, tracking=0.8))
        lbl_type.setStyleSheet(
            f"color: {'#ff4b58' if is_seq else ('#5ce67e' if is_preq else '#a8a8be')};"
        )
        top_row.addWidget(lbl_type)

        status_badge = QLabel("IN LIBRARY" if in_lib else "NOT IN LIBRARY")
        status_badge.setFont(ui_font(9, True, tracking=0.4))
        if in_lib:
            status_badge.setStyleSheet(
                "background: rgba(48, 209, 88, 0.20); color: #30d158; "
                "border: 1px solid rgba(48, 209, 88, 0.40); border-radius: 6px; padding: 2px 7px;"
            )
        else:
            status_badge.setStyleSheet(
                "background: rgba(255, 255, 255, 0.07); color: rgba(255, 255, 255, 0.45); "
                "border: 1px solid rgba(255, 255, 255, 0.10); border-radius: 6px; padding: 2px 7px;"
            )
        top_row.addWidget(status_badge)
        top_row.addStretch(1)
        vl.addLayout(top_row)

        disp_title = lib_entry.title if lib_entry else (node.get("title") or "?")
        lbl_title = QLabel(ui_fm(14, True).elidedText(disp_title, Qt.TextElideMode.ElideRight, 260))
        lbl_title.setFont(ui_font(14, True))
        lbl_title.setStyleSheet("color: white;" if in_lib else "color: rgba(255, 255, 255, 0.65);")
        lbl_title.setToolTip(disp_title)
        vl.addWidget(lbl_title)

        meta_bits = []
        yr = (lib_entry.media or {}).get("seasonYear") if lib_entry else node.get("seasonYear")
        fmt = (lib_entry.media or {}).get("format") if lib_entry else node.get("format")
        if yr:
            meta_bits.append(str(yr))
        if fmt:
            meta_bits.append(str(fmt).replace("_", " "))
        if lib_entry:
            w_cnt = len(self.watched(lib_entry) & lib_entry._ep_keys)
            tot_cnt = len(lib_entry.episodes)
            meta_bits.append(f"{w_cnt}/{tot_cnt} watched" if w_cnt else f"{tot_cnt} eps")
        elif node.get("episodes"):
            meta_bits.append(f"{node['episodes']} eps")

        lbl_meta = QLabel("  ·  ".join(meta_bits))
        lbl_meta.setFont(ui_font(11))
        lbl_meta.setStyleSheet(f"color: {T.MUTED};")
        vl.addWidget(lbl_meta)
        hl.addLayout(vl, 1)

        if in_lib:
            btn_play = QPushButton("▶")
            btn_play.setObjectName("circle_primary" if is_seq else "circle")
            btn_play.setFixedSize(36, 36)
            btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_play.setToolTip(f"Play {lib_entry.title}")
            btn_play.clicked.connect(lambda _=False, le=lib_entry: self.play_next(le))
            hl.addWidget(btn_play, 0, Qt.AlignmentFlag.AlignVCenter)

            orig_release = card.mouseReleaseEvent

            def _on_click(ev, le=lib_entry):
                if ev.button() == Qt.MouseButton.LeftButton and card.rect().contains(ev.position().toPoint()):
                    self.open_entry(le)
                else:
                    orig_release(ev)

            card.mouseReleaseEvent = _on_click  # type: ignore[method-assign]

        return card

    def populate_relations(self, entry: Entry) -> None:
        clear_layout(self.d_rel_lay)
        rels = self.entry_relations(entry)
        if not rels:
            self.d_rel_wrap.hide()
            return
        for rtype, node, lib_entry in rels[:4]:
            self.d_rel_lay.addWidget(self._relation_card(rtype, node, lib_entry))
        self.d_rel_lay.addStretch(1)
        self.d_rel_wrap.show()
