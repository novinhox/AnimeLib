"""VisionOS modal dialogs: SettingsDialog, SettingsCard, and MatchDialog."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import (
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from AniLibV6.anilist import anilist_request, media_title
from AniLibV6.config import APP_DIR, APP_VERSION, SEARCH_Q
from AniLibV6.theme import T, qc, ui_fm, ui_font
from AniLibV6.ui.common import AA, SmoothScrollArea
from AniLibV6.ui.components import AppleSwitch
from AniLibV6.utils import open_path


class SettingsCard(QFrame):
    """Rounded translucent glass container for grouped settings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsCard")
        self.setStyleSheet(
            "QFrame#settingsCard {"
            "  background: rgba(255, 255, 255, 0.05);"
            "  border: 1px solid rgba(255, 255, 255, 0.09);"
            "  border-radius: 18px;"
            "}"
        )
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(20, 14, 20, 14)
        self.lay.setSpacing(11)

    def add_row(self, title: str, desc: str = "", control: QWidget | None = None) -> QWidget:
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 4, 0, 4)
        rl.setSpacing(16)

        tl = QVBoxLayout()
        tl.setSpacing(2)
        t_lbl = QLabel(title)
        t_lbl.setFont(ui_font(14, True))
        t_lbl.setStyleSheet("color: #ffffff;")
        tl.addWidget(t_lbl)
        if desc:
            d_lbl = QLabel(desc)
            d_lbl.setWordWrap(True)
            d_lbl.setFont(ui_font(12))
            d_lbl.setStyleSheet("color: rgba(255, 255, 255, 0.55);")
            tl.addWidget(d_lbl)
        rl.addLayout(tl, 1)

        if control:
            rl.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lay.addWidget(row)
        return row

    def add_separator(self) -> None:
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(255, 255, 255, 0.07);")
        self.lay.addWidget(sep)


class CloseButton(QPushButton):
    """Frosted glass circular close button with vector-drawn '×' icon."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._over = False
        self._down = False

    def enterEvent(self, e) -> None:
        self._over = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._over = False
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._down = True
            self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        self._down = False
        self.update()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # Frosted glass background
        if self._down:
            bg = QColor(255, 255, 255, 20)
        elif self._over:
            bg = QColor(255, 255, 255, 52)
        else:
            bg = QColor(255, 255, 255, 26)

        p.setPen(QPen(QColor(255, 255, 255, 48 if self._over else 34), 1))
        p.setBrush(bg)
        p.drawEllipse(r)

        # Vector cross 'X'
        cx, cy = self.width() / 2.0, self.height() / 2.0
        s = 4.2
        pen = QPen(QColor(255, 255, 255, 255 if self._over else 215), 1.9)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(cx - s, cy - s), QPointF(cx + s, cy + s))
        p.drawLine(QPointF(cx - s, cy + s), QPointF(cx + s, cy - s))


class SettingsDialog(QDialog):
    """Apple TV / visionOS-style frosted glass settings sheet."""

    def __init__(self, win) -> None:
        super().__init__(win)
        self.win = win
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        if win and win.width() > 0:
            self.setGeometry(win.rect())
        else:
            self.resize(1000, 750)

        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.sheet = QFrame(self)
        self.sheet.setObjectName("settingsSheet")
        self.sheet.setFixedSize(
            min(760, max(640, int(self.width() * 0.70))),
            min(700, max(520, int(self.height() * 0.88))),
        )
        self.sheet.setStyleSheet(
            "QFrame#settingsSheet {"
            "  background: rgba(18, 20, 28, 0.96);"
            "  border: 1px solid rgba(255, 255, 255, 0.16);"
            "  border-radius: 26px;"
            "}"
        )
        main_lay.addWidget(self.sheet, 0, Qt.AlignmentFlag.AlignCenter)

        sheet_lay = QVBoxLayout(self.sheet)
        sheet_lay.setContentsMargins(28, 22, 28, 24)
        sheet_lay.setSpacing(14)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 4)

        title_lay = QVBoxLayout()
        title_lay.setSpacing(2)
        title = QLabel("Settings")
        title.setFont(ui_font(22, True, display=True))
        title.setStyleSheet("color: white;")
        sub = QLabel("Preferences & Library Configuration")
        sub.setFont(ui_font(12))
        sub.setStyleSheet("color: rgba(255, 255, 255, 0.50);")
        title_lay.addWidget(title)
        title_lay.addWidget(sub)
        top_bar.addLayout(title_lay)

        top_bar.addStretch(1)

        btn_close = CloseButton(self.sheet)
        btn_close.clicked.connect(self.close)
        top_bar.addWidget(btn_close)
        sheet_lay.addLayout(top_bar)

        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        c_lay = QVBoxLayout(content)
        c_lay.setContentsMargins(0, 4, 12, 16)
        c_lay.setSpacing(8)

        def add_section_header(text: str) -> None:
            if c_lay.count() > 0:
                c_lay.addSpacing(12)
            lbl = QLabel(text.upper())
            lbl.setFont(ui_font(11, True, tracking=1.2))
            lbl.setMinimumHeight(22)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            lbl.setStyleSheet("color: rgba(255, 255, 255, 0.45); padding: 2px 4px;")
            c_lay.addWidget(lbl)

        # LIBRARY
        add_section_header("Library")
        lib_card = SettingsCard()

        root_path = self.win.cfg.get("root", "") or "No folder selected"
        btn_change_root = QPushButton("Change Folder…")
        btn_change_root.setObjectName("glassPill")
        btn_change_root.setFixedHeight(32)
        btn_change_root.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_change_root.clicked.connect(self._change_folder)
        self.row_root = lib_card.add_row("Library Location", root_path, btn_change_root)

        lib_card.add_separator()
        btn_rescan = QPushButton("Rescan")
        btn_rescan.setObjectName("glassPill")
        btn_rescan.setFixedHeight(32)
        btn_rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_rescan.clicked.connect(lambda: (self.close(), self.win.start_scan()))
        lib_card.add_row(
            "Rescan Library",
            "Scan library folder for newly added or renamed anime and episodes",
            btn_rescan,
        )

        lib_card.add_separator()
        btn_rematch = QPushButton("Re-match All")
        btn_rematch.setObjectName("glassPill")
        btn_rematch.setFixedHeight(32)
        btn_rematch.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_rematch.clicked.connect(lambda: (self.close(), self.win.start_scan(rematch=True)))
        lib_card.add_row(
            "Deep Re-match",
            "Clear cache and query AniList fresh for all metadata and cover artwork",
            btn_rematch,
        )
        c_lay.addWidget(lib_card)

        # PLAYBACK
        add_section_header("Playback")
        play_card = SettingsCard()

        self.sw_builtin = AppleSwitch(checked=self.win.builtin_enabled())
        self.sw_builtin.toggled.connect(self.win.set_builtin)
        play_card.add_row(
            "Built-in Video Player",
            "Hardware-accelerated embedded player with custom subtitles, tracks and progress sync",
            self.sw_builtin,
        )

        play_card.add_separator()
        self.sw_autoplay = AppleSwitch(checked=bool(self.win.cfg["ui"].get("autoplay", True)))
        self.sw_autoplay.toggled.connect(
            lambda on: (
                self.win.cfg["ui"].__setitem__("autoplay", bool(on)),
                self.win.save_all(),
            )
        )
        play_card.add_row(
            "Autoplay Next Episode",
            "Automatically advance to the next episode when the current one finishes",
            self.sw_autoplay,
        )

        play_card.add_separator()
        self.combo_sub_font = QComboBox()
        self.combo_sub_font.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_sub_font.addItems([
            "Modern Clean",
            "Anime Rounded",
            "Cinema Heavy",
            "Classic Serif",
        ])
        cur_font = self.win.cfg["ui"].get("sub_font", "Modern Clean")
        if cur_font in ["Modern Clean", "Anime Rounded", "Cinema Heavy", "Classic Serif"]:
            self.combo_sub_font.setCurrentText(cur_font)
        self.combo_sub_font.currentTextChanged.connect(self._on_sub_font_changed)
        play_card.add_row(
            "Subtitle Font Preset",
            "Typography style used for rendering embedded and external subtitles",
            self.combo_sub_font,
        )

        play_card.add_separator()
        self.combo_sub_scale = QComboBox()
        self.combo_sub_scale.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_sub_scale.addItems(["Small", "Normal", "Large", "Huge"])
        cur_scale = self.win.cfg["ui"].get("sub_scale", "Normal")
        if cur_scale in ["Small", "Normal", "Large", "Huge"]:
            self.combo_sub_scale.setCurrentText(cur_scale)
        self.combo_sub_scale.currentTextChanged.connect(self._on_sub_scale_changed)
        play_card.add_row(
            "Subtitle Text Size",
            "Relative text scaling for player subtitles",
            self.combo_sub_scale,
        )

        play_card.add_separator()
        ext_ctrls = QWidget()
        el = QHBoxLayout(ext_ctrls)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(8)
        btn_auto_p = QPushButton("Auto-detect")
        btn_auto_p.setObjectName("glassPill")
        btn_auto_p.setFixedHeight(32)
        btn_auto_p.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_auto_p.clicked.connect(self._auto_player)
        btn_choose_p = QPushButton("Choose Player…")
        btn_choose_p.setObjectName("glassPill")
        btn_choose_p.setFixedHeight(32)
        btn_choose_p.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_choose_p.clicked.connect(self._choose_player)
        el.addWidget(btn_auto_p)
        el.addWidget(btn_choose_p)

        cur_p = self.win.cfg.get("player") or "Auto-detected (mpv / VLC / Default)"
        self.row_player = play_card.add_row("External Player", f"Active: {cur_p}", ext_ctrls)
        c_lay.addWidget(play_card)

        # THUMBNAILS
        add_section_header("Thumbnails & Video Frames")
        thumb_card = SettingsCard()

        self.sw_frames = AppleSwitch(checked=self.win.frames_enabled())
        self.sw_frames.toggled.connect(self.win.set_frames)
        thumb_card.add_row(
            "Video-Frame Thumbnails",
            "Capture real high-definition episode screenshots directly from video files (needs FFmpeg)",
            self.sw_frames,
        )

        thumb_card.add_separator()
        btn_ffmpeg = QPushButton("Locate FFmpeg…")
        btn_ffmpeg.setObjectName("glassPill")
        btn_ffmpeg.setFixedHeight(32)
        btn_ffmpeg.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ffmpeg.clicked.connect(self._choose_ffmpeg)
        ff_p = self.win.ffmpeg_path() or "Not found / not configured"
        self.row_ffmpeg = thumb_card.add_row("FFmpeg Binary", f"Path: {ff_p}", btn_ffmpeg)

        thumb_card.add_separator()
        btn_clear_frames = QPushButton("Clear Cache")
        btn_clear_frames.setObjectName("glassPill")
        btn_clear_frames.setFixedHeight(32)
        btn_clear_frames.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear_frames.clicked.connect(self.win.clear_frames)
        thumb_card.add_row(
            "Clear Thumbnail Cache",
            "Free up storage space by removing cached episode preview images",
            btn_clear_frames,
        )
        c_lay.addWidget(thumb_card)

        # APPEARANCE & SOUND
        add_section_header("Appearance & Experience")
        app_card = SettingsCard()

        self.sw_anim = AppleSwitch(checked=self.win.cfg["ui"].get("animations", True))
        self.sw_anim.toggled.connect(self.win.set_animations)
        app_card.add_row(
            "Fluid Animations",
            "Smooth hover zoom, page slides, card parallax and animated scrolling",
            self.sw_anim,
        )

        app_card.add_separator()
        self.sw_intro = AppleSwitch(checked=bool(self.win.cfg["ui"].get("intro_sound", True)))
        self.sw_intro.toggled.connect(
            lambda on: (
                self.win.cfg["ui"].__setitem__("intro_sound", bool(on)),
                self.win.save_all(),
                self.win.toast("Intro sound on" if on else "Intro sound muted"),
            )
        )
        app_card.add_row(
            "Startup Intro Sound",
            "Play signature intro sound on application launch",
            self.sw_intro,
        )

        app_card.add_separator()
        btn_replay = QPushButton("Replay")
        btn_replay.setObjectName("glassPill")
        btn_replay.setFixedHeight(32)
        btn_replay.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_replay.clicked.connect(lambda: (self.close(), self.win.replay_intro()))
        app_card.add_row(
            "Replay Intro Animation",
            "Preview the animated ribbon intro and startup sequence",
            btn_replay,
        )
        c_lay.addWidget(app_card)

        # KEYBOARD SHORTCUTS
        add_section_header("Keyboard Shortcuts")
        kb_card = SettingsCard()
        shortcuts = [
            ("Space", "Play next episode / Pause in player"),
            ("/", "Focus search box"),
            ("R", "Surprise me (pick random anime)"),
            ("F", "Toggle favorite on current anime"),
            ("[ / ]", "Speed down / up (0.25× – 3.0×)"),
            ("\\", "Reset speed to 1.0×"),
            ("Esc", "Go back / clear search / close sheet"),
            ("Arrows", "Navigate cards and episodes"),
            ("Ctrl+,", "Open settings"),
        ]
        for i, (k, desc) in enumerate(shortcuts):
            if i > 0:
                kb_card.add_separator()
            badge = QLabel(k)
            badge.setStyleSheet(
                "background: rgba(255, 255, 255, 0.12); color: white;"
                "border: 1px solid rgba(255, 255, 255, 0.18); border-radius: 8px;"
                "padding: 4px 10px; font-weight: 700; font-family: monospace;"
            )
            kb_card.add_row(desc, "", badge)
        c_lay.addWidget(kb_card)

        # UPDATES (OTA)
        add_section_header("Automatic Updates")
        upd_card = SettingsCard()

        self.sw_autoupd = AppleSwitch(checked=bool(self.win.cfg["ui"].get("auto_update", True)))
        self.sw_autoupd.toggled.connect(
            lambda on: (
                self.win.cfg["ui"].__setitem__("auto_update", bool(on)),
                self.win.save_all(),
            )
        )
        upd_card.add_row(
            "Check & Install Updates on Startup",
            "Automatically fetch lightweight code updates in the background when connected to the internet",
            self.sw_autoupd,
        )
        c_lay.addWidget(upd_card)

        # ABOUT
        add_section_header("About & Storage")
        about_card = SettingsCard()
        anime_count = len(self.win.entries)
        unmatched = sum(1 for e in self.win.entries if not e.media)
        stats = f"{anime_count} anime loaded" + (f" ({unmatched} unmatched)" if unmatched else "")
        about_card.add_row("Anime Library", f"v{APP_VERSION} · visionOS Edition · {stats}")
        about_card.add_separator()

        btn_open_appdir = QPushButton("Open Folder")
        btn_open_appdir.setObjectName("glassPill")
        btn_open_appdir.setFixedHeight(32)
        btn_open_appdir.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open_appdir.clicked.connect(lambda: open_path(str(APP_DIR)))
        about_card.add_row("Application Data", str(APP_DIR), btn_open_appdir)
        c_lay.addWidget(about_card)

        scroll.setWidget(content)
        sheet_lay.addWidget(scroll)

    def _on_sub_font_changed(self, name: str) -> None:
        self.win.cfg["ui"]["sub_font"] = name
        self.win.save_all()
        if hasattr(self.win, "player") and self.win.player is not None:
            self.win.player.sub_font_name = name
            if hasattr(self.win.player, "surface") and self.win.player.surface is not None:
                self.win.player.surface.update()

    def _on_sub_scale_changed(self, name: str) -> None:
        self.win.cfg["ui"]["sub_scale"] = name
        self.win.save_all()
        if hasattr(self.win, "player") and self.win.player is not None:
            scales = getattr(
                self.win.player,
                "SUB_SCALES",
                {"Small": 0.8, "Normal": 1.0, "Large": 1.3, "Huge": 1.6},
            )
            self.win.player.sub_scale = scales.get(name, 1.0)
            if hasattr(self.win.player, "surface") and self.win.player.surface is not None:
                self.win.player.surface.update()

    def _change_folder(self) -> None:
        self.win.choose_root()
        self.close()

    def _choose_player(self) -> None:
        self.win.choose_player()
        self.close()

    def _auto_player(self) -> None:
        self.win.auto_player()
        self.close()

    def _choose_ffmpeg(self) -> None:
        self.win.choose_ffmpeg()
        self.close()

    def mousePressEvent(self, e) -> None:
        if not self.sheet.geometry().contains(e.position().toPoint()):
            self.close()
            return
        super().mousePressEvent(e)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Escape, Qt.Key.Key_W):
            self.close()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        p.fillRect(self.rect(), QColor(0, 0, 0, 160))


class MatchDialog(QDialog):
    """visionOS modal search sheet for manual AniList re-matching."""

    def __init__(self, query: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Fix Match — Search AniList")
        self.resize(680, 520)
        self.setStyleSheet(
            f"QDialog {{ background: {T.SURFACE}; }}"
            "QLineEdit { background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.16);"
            "  border-radius: 14px; padding: 8px 16px; color: white; font-size: 14px; }"
            "QLineEdit:focus { border-color: " + T.ACCENT + "; background: rgba(255, 255, 255, 0.12); }"
            "QListWidget { background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.10);"
            "  border-radius: 16px; padding: 8px; color: white; }"
            "QListWidget::item { padding: 12px 14px; border-radius: 10px; margin-bottom: 4px; }"
            "QListWidget::item:selected { background: " + T.ACCENT + "; color: white; }"
            "QListWidget::item:hover:!selected { background: rgba(255, 255, 255, 0.09); }"
        )

        self.results: list[dict] = []
        self.selected: dict | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(14)

        header_lbl = QLabel("Search AniList for Correct Anime")
        header_lbl.setFont(ui_font(18, True, display=True))
        lay.addWidget(header_lbl)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.edit = QLineEdit(query)
        self.edit.setPlaceholderText("Enter anime title...")
        self.edit.setClearButtonEnabled(True)

        btn = QPushButton("Search")
        btn.setObjectName("primary")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(38)
        row.addWidget(self.edit, 1)
        row.addWidget(btn)
        lay.addLayout(row)

        self.lst = QListWidget()
        lay.addWidget(self.lst, 1)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

        btn.clicked.connect(self.search)
        self.edit.returnPressed.connect(self.search)
        self.lst.itemDoubleClicked.connect(lambda _: self.accept())

        QTimer.singleShot(0, self.search)

    def search(self) -> None:
        q = self.edit.text().strip()
        if not q:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            data = anilist_request(SEARCH_Q, {"s": q})
            self.results = data["Page"]["media"] if data else []
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Search failed", str(e))
            return
        QApplication.restoreOverrideCursor()

        self.lst.clear()
        for m in self.results:
            title = media_title(m)
            year = m.get("seasonYear") or "?"
            fmt = m.get("format") or "?"
            eps = m.get("episodes") or "?"
            score = f"★ {m.get('averageScore') / 10:.1f}" if m.get("averageScore") else ""
            item_text = f"{title}\n   {year} · {fmt} · {eps} eps   {score}   [#{m['id']}]"
            item = QListWidgetItem(item_text)
            self.lst.addItem(item)

        if self.results:
            self.lst.setCurrentRow(0)

    def accept(self) -> None:
        row = self.lst.currentRow()
        if row >= 0 and row < len(self.results):
            self.selected = self.results[row]
            super().accept()
        else:
            self.reject()
