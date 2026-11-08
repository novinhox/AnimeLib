"""VisionOS video player page, hardware-accelerated surface, overlay controls, and PillSlider."""
from __future__ import annotations

import os
from pathlib import Path
import time

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QLocale,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtMultimedia import (
        QAudioOutput,
        QMediaMetaData,
        QMediaPlayer,
        QVideoSink,
    )
    HAVE_MM = True
except Exception:
    HAVE_MM = False

from AniLibV6.models import fmt_time
from AniLibV6.scanner import sibling_subs
from AniLibV6.subtitles import SubTrack, clean_sub_text, parse_subtitles
from AniLibV6.theme import D, T, ui_font
from AniLibV6.ui.common import AA
from AniLibV6.utils import wrap_lines


class PillSlider(QWidget):
    """Thin modern slider used for seeking and volume."""

    changed = Signal(int)
    released = Signal(int)
    hovered = Signal(float, int)
    PAD = 9.0  # Exact compact margin ensuring radius-8 thumb is never clipped at min/max

    def __init__(self, maximum: int = 1000, height: int = 28) -> None:
        super().__init__()
        self._max = max(1, maximum)
        self._v = 0
        self._drag = False
        self._over = False
        self._hover_x = -1.0
        self.setFixedHeight(height)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def setMaximum(self, m: int | float) -> None:
        self._max = max(1, int(m))
        self.update()

    def setValue(self, v: int | float) -> None:
        if not self._drag:
            self._v = max(0, min(self._max, int(v)))
            self.update()

    def value(self) -> int:
        return self._v

    def _to_val(self, x: float) -> int:
        w = max(1.0, float(self.width() - 2 * self.PAD))
        return int(max(0.0, min(1.0, (x - self.PAD) / w)) * self._max)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        cy = self.height() / 2
        th = 6 if (self._over or self._drag) else 4
        x0, x1 = self.PAD, float(self.width() - self.PAD)

        # Base track
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 62))
        p.drawRoundedRect(QRectF(x0, cy - th / 2, x1 - x0, th), th / 2, th / 2)

        # Hover ghost track
        if self._over and not self._drag and self._hover_x > x0:
            hx = min(x1, max(x0, self._hover_x))
            p.setBrush(QColor(255, 255, 255, 80))
            p.drawRoundedRect(QRectF(x0, cy - th / 2, hx - x0, th), th / 2, th / 2)

        # Active progress track
        xf = x0 + (x1 - x0) * (self._v / self._max)
        p.setBrush(QColor(T.ACCENT))
        p.drawRoundedRect(QRectF(x0, cy - th / 2, max(0.0, xf - x0), th), th / 2, th / 2)

        # Scrubber thumb
        r = 8 if (self._over or self._drag) else 5
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(xf, cy), r, r)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = True
            self._v = self._to_val(e.position().x())
            self.changed.emit(self._v)
            self.update()

    def mouseMoveEvent(self, e) -> None:
        x = e.position().x()
        self._hover_x = x
        v = self._to_val(x)
        if self._drag:
            self._v = v
            self.changed.emit(v)
        self.update()
        self.hovered.emit(v / self._max, int(x))

    def mouseReleaseEvent(self, e) -> None:
        if self._drag and e.button() == Qt.MouseButton.LeftButton:
            self._drag = False
            self.released.emit(self._v)
            self.update()

    def enterEvent(self, e) -> None:
        self._over = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._over = False
        self._hover_x = -1.0
        self.hovered.emit(-1.0, 0)
        self.update()


class SeekBubble(QWidget):
    """VisionOS floating glass pill showing hover timestamp above seek slider."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFixedHeight(26)
        self._text = ""
        self.hide()

    def show_time(self, text: str, center_x: int, top_y: int) -> None:
        self._text = text
        fm = QFontMetrics(ui_font(12, True, mono=True))
        w = max(52, fm.horizontalAdvance(text) + 18)
        self.setFixedWidth(w)
        x = int(center_x - w / 2)
        p = self.parentWidget()
        if p is not None:
            x = max(8, min(p.width() - w - 8, x))
        self.move(x, max(2, top_y - self.height()))
        if not self.isVisible():
            self.show()
        self.raise_()
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # Frosted glass background
        p.setPen(QPen(QColor(255, 255, 255, 52), 1))
        p.setBrush(QColor(16, 18, 26, 235))
        p.drawRoundedRect(r, 7, 7)

        # Subtle specular top highlight
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0.0, QColor(255, 255, 255, 30))
        g.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r.adjusted(1, 1, -1, -self.height() / 2), 6, 6)

        # Mono text
        p.setFont(ui_font(12, True, mono=True))
        p.setPen(QColor("white"))
        p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), self._text)


class IconButton(QWidget):
    """Flat vector button for player controls (play, pause, next, volume, fullscreen, speed)."""

    clicked = Signal()
    wheeled = Signal(int)

    def __init__(self, kind: str, w: int = 40, h: int = 40, text: str = "") -> None:
        super().__init__()
        self.kind = kind
        self.text = text
        self._over = False
        self.active = False
        self.setFixedSize(w, h)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def wheelEvent(self, e) -> None:
        self.wheeled.emit(1 if e.angleDelta().y() > 0 else -1)

    def set_kind(self, kind: str, active: bool | None = None) -> None:
        self.kind = kind
        if active is not None:
            self.active = active
        self.update()

    def enterEvent(self, e) -> None:
        self._over = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._over = False
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        if self._over:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 30))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 9, 9)

        col = QColor("white") if self._over else QColor(255, 255, 255, 225)
        pen = QPen(col, 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        c = QPointF(self.width() / 2, self.height() / 2)
        k = self.kind
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)

        def poly(pts):
            path = QPainterPath()
            path.moveTo(*pts[0])
            for q in pts[1:]:
                path.lineTo(*q)
            path.closeSubpath()
            p.drawPath(path)

        x, y = c.x(), c.y()
        if k == "play":
            poly([(x - 7, y - 11), (x + 11, y), (x - 7, y + 11)])
        elif k == "pause":
            p.drawRoundedRect(QRectF(x - 9, y - 10, 6.5, 20), 2, 2)
            p.drawRoundedRect(QRectF(x + 2.5, y - 10, 6.5, 20), 2, 2)
        elif k == "prev":
            p.drawRoundedRect(QRectF(x - 11, y - 9, 3.2, 18), 1.5, 1.5)
            poly([(x + 10, y - 10), (x - 6, y), (x + 10, y + 10)])
        elif k == "next":
            p.drawRoundedRect(QRectF(x + 7.8, y - 9, 3.2, 18), 1.5, 1.5)
            poly([(x - 10, y - 10), (x + 6, y), (x - 10, y + 10)])
        elif k in ("vol", "mute"):
            poly([(x - 11, y - 4), (x - 6, y - 4), (x, y - 10), (x, y + 10), (x - 6, y + 4), (x - 11, y + 4)])
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(pen)
            if k == "mute":
                p.drawLine(QPointF(x + 4, y - 5), QPointF(x + 12, y + 5))
                p.drawLine(QPointF(x + 12, y - 5), QPointF(x + 4, y + 5))
            else:
                p.drawArc(QRectF(x - 5, y - 6, 12, 12), -50 * 16, 100 * 16)
                p.drawArc(QRectF(x - 8, y - 11, 20, 22), -50 * 16, 100 * 16)
        elif k == "full":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(pen)
            if not self.active:
                for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                    p.drawPolyline(
                        [
                            QPointF(x + sx * 9, y + sy * 3),
                            QPointF(x + sx * 9, y + sy * 9),
                            QPointF(x + sx * 3, y + sy * 9),
                        ]
                    )
            else:
                for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                    p.drawPolyline(
                        [
                            QPointF(x + sx * 3, y + sy * 9),
                            QPointF(x + sx * 3, y + sy * 3),
                            QPointF(x + sx * 9, y + sy * 3),
                        ]
                    )
        elif k == "back":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(pen)
            p.drawLine(QPointF(x + 9, y), QPointF(x - 9, y))
            p.drawPolyline([QPointF(x - 2, y - 8), QPointF(x - 10, y), QPointF(x - 2, y + 8)])
        elif k == "external":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(pen)
            p.drawPolyline(
                [
                    QPointF(x - 2, y - 9),
                    QPointF(x - 10, y - 9),
                    QPointF(x - 10, y + 9),
                    QPointF(x + 8, y + 9),
                    QPointF(x + 8, y + 1),
                ]
            )
            p.drawLine(QPointF(x - 1, y + 1), QPointF(x + 10, y - 10))
            p.drawPolyline(
                [
                    QPointF(x + 3, y - 10),
                    QPointF(x + 10, y - 10),
                    QPointF(x + 10, y - 3),
                ]
            )
        else:
            p.setPen(col)
            p.setFont(ui_font(14, True))
            p.drawText(QRectF(self.rect()), int(Qt.AlignmentFlag.AlignCenter), self.text)
            if k == "text_box":
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(col, 1.8))
                p.drawRoundedRect(QRectF(self.rect()).adjusted(5, 8, -5, -8), 4, 4)


class OverlayPanel(QWidget):
    """Top / bottom visionOS gradient overlay panel."""

    def __init__(self, page, top: bool) -> None:
        super().__init__(page)
        self.page = page
        self.top = top
        self.setMouseTracking(True)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        if self.top:
            g.setColorAt(0, QColor(0, 0, 0, 200))
            g.setColorAt(1, QColor(0, 0, 0, 0))
        else:
            g.setColorAt(0, QColor(0, 0, 0, 0))
            g.setColorAt(0.55, QColor(0, 0, 0, 150))
            g.setColorAt(1, QColor(0, 0, 0, 225))
        p.fillRect(self.rect(), g)

    def mouseMoveEvent(self, e) -> None:
        self.page.show_ui()

    def mousePressEvent(self, e) -> None:
        e.accept()


class PlayerSurface(QWidget):
    """Draws video frames, subtitle cues, and on-screen display messages."""

    def __init__(self, page) -> None:
        super().__init__(page)
        self.page = page
        self._frame = None
        self._img = None
        self._dirty = False
        self.sub_items: list[tuple[str, bool]] = []
        self.osd_text = ""
        self.osd_until = 0.0
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

        self._click = QTimer(self)
        self._click.setSingleShot(True)
        self._click.setInterval(230)
        self._click.timeout.connect(page.toggle_pause)

        self._osd_timer = QTimer(self)
        self._osd_timer.setSingleShot(True)
        self._osd_timer.timeout.connect(self.update)

    def on_frame(self, frame) -> None:
        self._frame = frame
        self._dirty = True
        self.update()

    def clear(self) -> None:
        self._frame = self._img = None
        self.sub_items = []
        self.update()

    def set_sub(self, items: list[tuple[str, bool]]) -> None:
        if items != self.sub_items:
            self.sub_items = items
            self.update()

    def osd(self, text: str, ms: int = 1400) -> None:
        self.osd_text = text
        self.osd_until = time.time() + ms / 1000
        self._osd_timer.start(ms + 30)
        self.update()

    def mouseMoveEvent(self, e) -> None:
        self.page.show_ui()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._click.start()

    def mouseDoubleClickEvent(self, e) -> None:
        self._click.stop()
        self.page.win.toggle_fullscreen()

    def wheelEvent(self, e) -> None:
        self.page.change_volume(5 if e.angleDelta().y() > 0 else -5)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        W, H = self.width(), self.height()
        p.fillRect(self.rect(), QColor(0, 0, 0))
        vr = QRectF(0, 0, W, H)

        if self._dirty and self._frame is not None and self._frame.isValid():
            self._img = self._frame.toImage()
            self._dirty = False

        if self._img is not None and not self._img.isNull():
            iw, ih = self._img.width(), self._img.height()
            s = min(W / iw, H / ih)
            vr = QRectF((W - iw * s) / 2, (H - ih * s) / 2, iw * s, ih * s)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawImage(vr, self._img)

        p.setRenderHints(AA)
        if self.sub_items and self.page.sub_visible:
            self._paint_subs(p, vr)

        if self.osd_text and time.time() < self.osd_until:
            f = ui_font(18, True)
            fm = QFontMetrics(f)
            w = fm.horizontalAdvance(self.osd_text) + 36
            box = QRectF(W - w - 28, 28 + (90 if self.page.ui_alpha > 0.5 else 0), w, 40)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(box, 10, 10)
            p.setPen(QColor("white"))
            p.setFont(f)
            p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), self.osd_text)

    def _paint_subs(self, p: QPainter, vr: QRectF) -> None:
        px = max(16, int(vr.height() * 0.05 * self.page.sub_scale))
        font_name = self.page.sub_font_name
        families = self.page.SUB_FONTS.get(font_name) or self.page.SUB_FONTS["Modern Clean"]

        base = QFont()
        base.setFamilies(families)
        base.setWeight(QFont.Weight.Bold)
        base.setPixelSize(px)
        base.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferQuality)

        maxw = int(vr.width() * 0.86)
        lines = []
        for text, italic in self.sub_items:
            f = QFont(base)
            f.setItalic(italic)
            for raw in text.split("\n"):
                for l in wrap_lines(raw, QFontMetrics(f), maxw, 4):
                    lines.append((l, italic))
        lift = 100 if self.page.ui_alpha > 0.5 else 0
        lh = int(px * 1.25)
        y = vr.bottom() - vr.height() * 0.05 - lift - lh * len(lines) + px
        for text, italic in lines:
            f = QFont(base)
            f.setItalic(italic)
            fm = QFontMetrics(f)
            x = vr.center().x() - fm.horizontalAdvance(text) / 2
            path = QPainterPath()
            path.addText(x, y, f, text)
            pen = QPen(QColor(0, 0, 0, 235), max(3.0, px * 0.17))
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.strokePath(path, pen)
            p.fillPath(path, QColor("white"))
            y += lh


class PlayerPage(QWidget):
    """Full-window video player with auto-hiding visionOS glass HUD controls."""

    RATES = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0)
    SUB_SCALES = {"Small": 0.8, "Normal": 1.0, "Large": 1.3, "Huge": 1.6}
    SUB_FONTS = {
        "Modern Clean": [
            "SF Pro Display",
            "SF Pro Text",
            "Segoe UI Variable Text",
            "Segoe UI",
            "Inter",
            "Helvetica Neue",
            "Arial",
        ],
        "Anime Rounded": [
            "Nunito",
            "Arial Rounded MT Bold",
            "Comfortaa",
            "Varela Round",
            "Segoe UI",
            "sans-serif",
        ],
        "Cinema Heavy": [
            "Trebuchet MS",
            "Impact",
            "Arial Black",
            "Franklin Gothic Medium",
            "Arial",
            "sans-serif",
        ],
        "Classic Serif": [
            "Georgia",
            "Palatino Linotype",
            "Times New Roman",
            "serif",
        ],
    }

    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self.entry = None
        self.ep = None
        self._resume = 0
        self._marked = False
        self._dur = 0
        self._ui_alpha = 1.0
        self._ui_visible = True
        self.sub_track = None
        self.sub_mode = ("off", None)
        self.sub_visible = True
        self.sub_delay = 0
        self.ext_subs = []
        self.sub_scale = self.SUB_SCALES.get(win.cfg["ui"].get("sub_scale", "Normal"), 1.0)
        self.sub_font_name = win.cfg["ui"].get("sub_font", "Modern Clean")
        self._countdown = 0
        self._next_ep = None
        self._next_entry = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self.surface = PlayerSurface(self)
        self.player = QMediaPlayer(self)
        self.audio = None
        if not os.environ.get("ANIME_LIBRARY_NO_AUDIO"):
            self.audio = QAudioOutput(self)
            self.player.setAudioOutput(self.audio)
            self.audio.setVolume(win.cfg["ui"].get("volume", 80) / 100)
            self.audio.setMuted(bool(win.cfg["ui"].get("muted", False)))

        self.sink = QVideoSink(self)
        self.player.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self.surface.on_frame)
        self.sink.subtitleTextChanged.connect(self.on_embedded_sub)
        self.player.positionChanged.connect(self.on_position)
        self.player.durationChanged.connect(self.on_duration)
        self.player.playbackStateChanged.connect(self.on_state)
        self.player.mediaStatusChanged.connect(self.on_status)
        self.player.errorOccurred.connect(self.on_error)

        # Top bar
        self.top = OverlayPanel(self, True)
        tl = QHBoxLayout(self.top)
        tl.setContentsMargins(22, 14, 22, 0)
        tl.setSpacing(14)
        self.btn_back = IconButton("back", 44, 44)
        self.btn_back.clicked.connect(self.win.exit_player)
        tl.addWidget(self.btn_back, 0, Qt.AlignmentFlag.AlignTop)

        tv = QVBoxLayout()
        tv.setSpacing(2)
        self.lbl_title = QLabel()
        self.lbl_title.setFont(ui_font(20, True, display=True))
        self.lbl_sub = QLabel()
        self.lbl_sub.setStyleSheet("color: #cfcfda; font-size: 14px;")
        tv.addWidget(self.lbl_title)
        tv.addWidget(self.lbl_sub)
        tl.addLayout(tv, 1)

        # Bottom controls
        self.controls = OverlayPanel(self, False)
        self.seek_bubble = SeekBubble(self.controls)
        cl = QVBoxLayout(self.controls)
        cl.setContentsMargins(26, 32, 26, 14)
        cl.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.lbl_cur = QLabel("0:00")
        self.lbl_cur.setMinimumWidth(54)
        self.lbl_tot = QLabel("0:00")
        self.lbl_tot.setMinimumWidth(54)
        self.lbl_tot.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for l in (self.lbl_cur, self.lbl_tot):
            l.setFont(ui_font(12, True, mono=True))
            l.setStyleSheet("color: white;")

        self.seek = PillSlider(1000, 30)
        self.seek.changed.connect(lambda v: self.lbl_cur.setText(fmt_time(v)))
        self.seek.released.connect(lambda v: self.player.setPosition(int(v)))
        self.seek.hovered.connect(self._seek_hover)
        row.addWidget(self.lbl_cur)
        row.addWidget(self.seek, 1)
        row.addWidget(self.lbl_tot)
        cl.addLayout(row)

        br = QHBoxLayout()
        br.setSpacing(4)
        self.btn_prev = IconButton("prev")
        self.btn_play = IconButton("pause", 48, 48)
        self.btn_next = IconButton("next")
        self.btn_vol = IconButton("vol")
        self.vol = PillSlider(100, 28)
        self.vol.setFixedWidth(96)
        self.vol.setValue(self.win.cfg["ui"].get("volume", 80))
        self.vol.changed.connect(self.set_volume)

        self.btn_prev.clicked.connect(lambda: self.step_episode(-1))
        self.btn_play.clicked.connect(self.toggle_pause)
        self.btn_next.clicked.connect(lambda: self.step_episode(1))
        self.btn_vol.clicked.connect(self.toggle_mute)

        for b in (self.btn_prev, self.btn_play, self.btn_next, self.btn_vol):
            br.addWidget(b)
        br.addWidget(self.vol)
        br.addStretch(1)

        self.btn_eps = IconButton("text_box", 54, 40, "EP")
        self.btn_eps.setToolTip("Episodes list (E)")
        self.btn_eps.clicked.connect(self.episodes_menu)

        self.btn_cc = IconButton("text_box", 52, 40, "CC")
        self.btn_audio = IconButton("text", 64, 40, "Audio")
        self.btn_speed = IconButton("text", 64, 40, "1×")
        self.btn_speed.setToolTip("Playback speed ([ / ]) — Click for menu, scroll to adjust")
        self.btn_speed.wheeled.connect(lambda d: self.adjust_rate(0.1 if d > 0 else -0.1))
        self.btn_ext = IconButton("external")
        self.btn_full = IconButton("full")

        self.btn_cc.clicked.connect(self.subs_menu)
        self.btn_audio.clicked.connect(self.audio_menu)
        self.btn_speed.clicked.connect(self.speed_menu)
        self.btn_ext.clicked.connect(self.open_external)
        self.btn_full.clicked.connect(self.win.toggle_fullscreen)

        self.btn_cc.setToolTip("Subtitles")
        self.btn_ext.setToolTip("Open in external player")
        self.btn_full.setToolTip("Fullscreen (F)")

        for b in (self.btn_eps, self.btn_cc, self.btn_audio, self.btn_speed, self.btn_ext, self.btn_full):
            br.addWidget(b)
        cl.addLayout(br)

        # Autoplay Next Box
        self.next_box = QFrame(self)
        self.next_box.setStyleSheet(
            "QFrame { background: rgba(20, 22, 32, 0.96); border: 1px solid rgba(255, 255, 255, 0.16);"
            "border-radius: 16px; } QLabel { border: none; }"
        )
        nb = QVBoxLayout(self.next_box)
        nb.setContentsMargins(18, 14, 18, 14)
        nb.setSpacing(10)
        self.lbl_next = QLabel()
        self.lbl_next.setFont(ui_font(15, True))
        nb.addWidget(self.lbl_next)

        nr = QHBoxLayout()
        self.btn_next_now = QPushButton("Play now")
        self.btn_next_now.setObjectName("primary")
        self.btn_next_cancel = QPushButton("Cancel")
        for b in (self.btn_next_now, self.btn_next_cancel):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            nr.addWidget(b)
        nb.addLayout(nr)

        self.btn_next_now.clicked.connect(self._play_next_now)
        self.btn_next_cancel.clicked.connect(self.hide_next_box)
        self.next_box.hide()

        self.next_timer = QTimer(self)
        self.next_timer.setInterval(1000)
        self.next_timer.timeout.connect(self._tick_next)

        self.top_eff = QGraphicsOpacityEffect(self.top)
        self.ctl_eff = QGraphicsOpacityEffect(self.controls)
        self.top.setGraphicsEffect(self.top_eff)
        self.controls.setGraphicsEffect(self.ctl_eff)

        self._ui_anim = QPropertyAnimation(self, b"ui_alpha", self)
        self._ui_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.setInterval(2800)
        self.hide_timer.timeout.connect(self._maybe_hide_ui)

        self.save_timer = QTimer(self)
        self.save_timer.setInterval(10000)
        self.save_timer.timeout.connect(self.save_progress)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        W, H = self.width(), self.height()
        self.surface.setGeometry(0, 0, W, H)
        self.top.setGeometry(0, 0, W, 100)
        self.controls.setGeometry(0, H - 132, W, 132)

    def _get_alpha(self) -> float:
        return self._ui_alpha

    def _set_alpha(self, v: float) -> None:
        self._ui_alpha = v
        self.top_eff.setOpacity(v)
        self.ctl_eff.setOpacity(v)
        self.top.setVisible(v > 0.01)
        self.controls.setVisible(v > 0.01)
        self.surface.update()

    ui_alpha = Property(float, _get_alpha, _set_alpha)

    def _fade_ui(self, show: bool) -> None:
        if not show and hasattr(self, "seek_bubble"):
            self.seek_bubble.hide()
        self._ui_visible = show
        self._ui_anim.stop()
        if not T.animations:
            self.ui_alpha = 1.0 if show else 0.0
            return
        self._ui_anim.setDuration(D(220))
        self._ui_anim.setStartValue(self._ui_alpha)
        self._ui_anim.setEndValue(1.0 if show else 0.0)
        self._ui_anim.start()

    def show_ui(self) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if not self._ui_visible:
            self._fade_ui(True)
        self.hide_timer.start(2800)

    def _maybe_hide_ui(self) -> None:
        if (
            self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            and not self.controls.underMouse()
            and not self.top.underMouse()
            and not self.seek._drag
            and not self.next_box.isVisible()
        ):
            if hasattr(self, "seek_bubble"):
                self.seek_bubble.hide()
            self._fade_ui(False)
            self.setCursor(Qt.CursorShape.BlankCursor)

    def open(self, entry, ep, resume_ms: int = 0) -> None:
        self.save_progress()
        self.entry, self.ep = entry, ep
        self._resume, self._marked, self._dur = resume_ms, False, 0
        self.hide_next_box()
        self.surface.clear()
        self.lbl_title.setText(entry.title)
        self.lbl_sub.setText(f"{self.win.ep_label(entry, ep)}   ·   {Path(ep.path).name}")
        self.seek.setValue(0)
        self.lbl_cur.setText("0:00")
        self.lbl_tot.setText("0:00")
        self.sub_track, self.sub_mode, self.sub_delay = None, ("off", None), 0
        self.sub_font_name = self.win.cfg["ui"].get("sub_font", "Modern Clean")
        self.sub_scale = self.SUB_SCALES.get(self.win.cfg["ui"].get("sub_scale", "Normal"), 1.0)
        self.ext_subs = sibling_subs(ep.path)
        if ep.sub and Path(ep.sub) not in self.ext_subs:
            self.ext_subs.insert(0, Path(ep.sub))

        if self.ext_subs:
            self.load_ext_sub(self.ext_subs[0], quiet=True)

        self.player.setPlaybackRate(1.0)
        self.btn_speed.text = "1×"
        self.btn_speed.update()
        self.player.setSource(QUrl.fromLocalFile(str(ep.path)))
        self.player.play()
        self.show_ui()
        self.setFocus()
        self.save_timer.start()

    def stop_playback(self) -> None:
        if hasattr(self, "seek_bubble"):
            self.seek_bubble.hide()
        self.save_timer.stop()
        self.hide_next_box()
        self.save_progress()
        self.player.stop()
        self.player.setSource(QUrl())
        self.surface.clear()
        self.entry = self.ep = None

    def save_progress(self) -> None:
        if self.entry is not None and self.ep is not None and self._dur > 0:
            pos = self.player.position()
            self.win.set_pos(self.entry, self.ep, pos, self._dur)

    def open_external(self) -> None:
        entry, ep = self.entry, self.ep
        if entry is None:
            return
        self.win.exit_player()
        self.win.play_external(entry, ep)

    def on_duration(self, ms: int) -> None:
        self._dur = ms
        self.seek.setMaximum(max(1, ms))
        self.lbl_tot.setText(fmt_time(ms))

    def on_position(self, ms: int) -> None:
        if not self.seek._drag:
            self.seek.setValue(ms)
            self.lbl_cur.setText(fmt_time(ms))
        if self.sub_track is not None:
            self.surface.set_sub(self.sub_track.at(ms - self.sub_delay))
        if (
            self.entry is not None
            and not self._marked
            and self._dur > 0
            and ms >= self._dur * 0.92
        ):
            self._marked = True
            self.win.mark_watched(self.entry, self.ep, True)

    def on_state(self, st) -> None:
        playing = st == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.set_kind("pause" if playing else "play")
        if not playing:
            self.show_ui()

    def on_status(self, st) -> None:
        MS = QMediaPlayer.MediaStatus
        if st in (MS.LoadedMedia, MS.BufferedMedia) and self._resume > 0:
            ms, self._resume = self._resume, 0
            self.player.setPosition(ms)
            self.surface.osd(f"Resumed at {fmt_time(ms)}   (Home = restart)", 2600)
        if (
            st in (MS.LoadedMedia, MS.BufferedMedia)
            and self.sub_mode[0] == "off"
            and not self.ext_subs
        ):
            self._auto_embedded_tracks()
        if st == MS.EndOfMedia:
            self.on_end()
        elif st == MS.InvalidMedia and self.entry is not None:
            self.win.player_failed("The file could not be decoded")

    def on_error(self, err, msg: str) -> None:
        if self.entry is not None:
            self.win.player_failed(msg or "Playback error")

    def on_embedded_sub(self, text: str) -> None:
        if self.sub_mode[0] != "emb":
            return
        items = []
        for chunk in (text or "").split("\n\n"):
            t, it = clean_sub_text(chunk)
            if t:
                items.append((t, it))
        self.surface.set_sub(items)

    def on_end(self) -> None:
        if self.entry is None:
            return
        self.win.mark_watched(self.entry, self.ep, True)
        self.win.set_pos(self.entry, self.ep, 0, 0)
        nxt = self.neighbour(1)
        if nxt is not None and self.win.cfg["ui"].get("autoplay", True):
            self.show_next_box(nxt, self.entry)
            return
        seq = self.win.sequel_entry(self.entry)
        if seq and seq.episodes and self.win.cfg["ui"].get("autoplay", True):
            seq_ep = self.win.next_episode(seq) or seq.episodes[0]
            self.show_next_box(seq_ep, seq)
            return
        self.win.exit_player()

    def neighbour(self, d: int):
        eps = self.entry.episodes
        try:
            i = eps.index(self.ep) + d
        except ValueError:
            return None
        return eps[i] if 0 <= i < len(eps) else None

    def step_episode(self, d: int) -> None:
        nxt = self.neighbour(d)
        if nxt is None:
            if d > 0 and self.entry:
                seq = self.win.sequel_entry(self.entry)
                if seq and seq.episodes:
                    seq_ep = self.win.next_episode(seq) or seq.episodes[0]
                    self.hide_next_box()
                    self.win.prog(seq)["last"] = time.time()
                    self.open(seq, seq_ep, self.win.resume_ms(seq, seq_ep))
                    self.surface.osd(f"Sequel: {seq.title}")
                    return
            elif d < 0 and self.entry:
                preq = self.win.prequel_entry(self.entry)
                if preq and preq.episodes:
                    preq_ep = preq.episodes[-1]
                    self.hide_next_box()
                    self.win.prog(preq)["last"] = time.time()
                    self.open(preq, preq_ep, self.win.resume_ms(preq, preq_ep))
                    self.surface.osd(f"Prequel: {preq.title}")
                    return
            self.surface.osd("No next episode" if d > 0 else "This is the first episode")
            return
        self.go_episode(nxt)

    def go_episode(self, ep) -> None:
        entry = self.entry
        self.hide_next_box()
        self.win.prog(entry)["last"] = time.time()
        self.open(entry, ep, self.win.resume_ms(entry, ep))

    @staticmethod
    def _track_label(md, i: int) -> str:
        lang = title = ""
        try:
            v = md.value(QMediaMetaData.Key.Language)
            if v is not None:
                lang = QLocale.languageToString(v)
                if lang in ("C", "AnyLanguage"):
                    lang = ""
        except Exception:
            pass
        try:
            title = md.stringValue(QMediaMetaData.Key.Title) or ""
        except Exception:
            pass
        return " · ".join(x for x in (lang, title) if x) or f"Track {i + 1}"

    def _auto_embedded_tracks(self) -> None:
        try:
            subs = self.player.subtitleTracks()
            auds = self.player.audioTracks()
        except Exception:
            return
        for i, md in enumerate(auds):
            if "japan" in self._track_label(md, i).lower():
                self.player.setActiveAudioTrack(i)
                break
        if subs:
            pick = next(
                (i for i, md in enumerate(subs) if "english" in self._track_label(md, i).lower()),
                0,
            )
            self.choose_embedded(pick, quiet=True)

    def load_ext_sub(self, path: str | Path, quiet: bool = False) -> None:
        try:
            cues = parse_subtitles(path)
        except Exception as e:
            self.surface.osd(f"Could not read subtitles: {e}", 2500)
            return
        self.player.setActiveSubtitleTrack(-1)
        self.sub_track = SubTrack(cues)
        self.sub_mode = ("ext", str(path))
        self.sub_visible = True
        self.surface.set_sub(self.sub_track.at(self.player.position() - self.sub_delay))
        if not quiet:
            self.surface.osd(f"Subtitles: {Path(path).name}", 1800)

    def choose_embedded(self, i: int, quiet: bool = False) -> None:
        self.sub_track = None
        self.sub_mode = ("emb", i)
        self.sub_visible = True
        self.surface.set_sub([])
        self.player.setActiveSubtitleTrack(i)
        if not quiet:
            self.surface.osd("Subtitles: " + self._track_label(self.player.subtitleTracks()[i], i), 1800)

    def subs_off(self) -> None:
        self.sub_track = None
        self.sub_mode = ("off", None)
        self.player.setActiveSubtitleTrack(-1)
        self.surface.set_sub([])
        self.surface.osd("Subtitles off")

    def _popup(self, menu: QMenu, btn: QWidget) -> None:
        menu.exec(btn.mapToGlobal(QPoint(0, -menu.sizeHint().height() - 6)))

    def episodes_menu(self) -> None:
        if not self.entry or not self.entry.episodes:
            return
        m = QMenu(self)
        grp = QActionGroup(m)
        w = self.win.watched(self.entry)
        for ep in self.entry.episodes:
            is_cur = ep == self.ep
            is_w = ep.key in w
            prefix = "▶ " if is_cur else ("✓ " if is_w else "   ")
            label = f"{prefix}{self.win.ep_label(self.entry, ep)}"
            if is_cur:
                label += "  (Playing)"
            elif is_w:
                label += "  (Watched)"
            a = m.addAction(label)
            a.setCheckable(True)
            a.setChecked(is_cur)
            a.triggered.connect(lambda _=False, ep=ep: self.go_episode(ep))
            grp.addAction(a)
        self._popup(m, self.btn_eps)

    def subs_menu(self) -> None:
        m = QMenu(self)
        grp = QActionGroup(m)
        off = m.addAction("Off")
        off.setCheckable(True)
        off.setChecked(self.sub_mode[0] == "off")
        off.triggered.connect(self.subs_off)
        grp.addAction(off)
        if self.ext_subs:
            m.addSeparator()
        for f in self.ext_subs:
            a = m.addAction(f.name if len(f.name) < 46 else f.name[:43] + "…")
            a.setCheckable(True)
            a.setChecked(self.sub_mode == ("ext", str(f)))
            a.triggered.connect(lambda _=False, f=f: self.load_ext_sub(f))
            grp.addAction(a)
        try:
            emb = self.player.subtitleTracks()
        except Exception:
            emb = []
        if emb:
            m.addSeparator()
        for i, md in enumerate(emb):
            a = m.addAction("Embedded: " + self._track_label(md, i))
            a.setCheckable(True)
            a.setChecked(self.sub_mode == ("emb", i))
            a.triggered.connect(lambda _=False, i=i: self.choose_embedded(i))
            grp.addAction(a)
        m.addSeparator()
        sz = m.addMenu("Size")
        sg = QActionGroup(sz)
        for name, val in self.SUB_SCALES.items():
            a = sz.addAction(name)
            a.setCheckable(True)
            a.setChecked(abs(self.sub_scale - val) < 0.01)
            a.triggered.connect(lambda _=False, n=name, v=val: self.set_sub_scale(n, v))
            sg.addAction(a)

        fn = m.addMenu("Font")
        fg = QActionGroup(fn)
        for fname in self.SUB_FONTS:
            a = fn.addAction(fname)
            a.setCheckable(True)
            a.setChecked(self.sub_font_name == fname)
            a.triggered.connect(lambda _=False, n=fname: self.set_sub_font(n))
            fg.addAction(a)

        m.addAction(f"Delay: {self.sub_delay / 1000:+.1f}s   (Z / X)").setEnabled(False)
        self._popup(m, self.btn_cc)

    def set_sub_scale(self, name: str, val: float) -> None:
        self.sub_scale = val
        self.win.cfg["ui"]["sub_scale"] = name
        self.win.save_all()
        self.surface.update()
        self.surface.osd(f"Subtitle size: {name}", 1400)

    def set_sub_font(self, name: str) -> None:
        if name in self.SUB_FONTS:
            self.sub_font_name = name
            self.win.cfg["ui"]["sub_font"] = name
            self.win.save_all()
            self.surface.update()
            self.surface.osd(f"Subtitle font: {name}", 1600)

    def audio_menu(self) -> None:
        m = QMenu(self)
        try:
            auds = self.player.audioTracks()
        except Exception:
            auds = []
        if not auds:
            m.addAction("No alternative audio tracks").setEnabled(False)
        grp = QActionGroup(m)
        cur = self.player.activeAudioTrack()
        for i, md in enumerate(auds):
            a = m.addAction(self._track_label(md, i))
            a.setCheckable(True)
            a.setChecked(i == cur)
            a.triggered.connect(
                lambda _=False, i=i, md=md: (
                    self.player.setActiveAudioTrack(i),
                    self.surface.osd("Audio: " + self._track_label(md, i)),
                )
            )
            grp.addAction(a)
        self._popup(m, self.btn_audio)

    def speed_menu(self) -> None:
        m = QMenu(self)
        grp = QActionGroup(m)
        cur_r = round(self.player.playbackRate(), 2)
        for r in self.RATES:
            label = f"{r:g}×"
            if r == 1.0:
                label += "  (Normal)"
            elif r == 3.0:
                label += "  (Max)"
            a = m.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(cur_r - r) < 0.04)
            a.triggered.connect(lambda _=False, r=r: self.set_rate(r))
            grp.addAction(a)

        m.addSeparator()
        a_minus = m.addAction("Slower (−0.1×)      [")
        a_minus.triggered.connect(lambda: self.adjust_rate(-0.1))

        a_plus = m.addAction("Faster (+0.1×)      ]")
        a_plus.triggered.connect(lambda: self.adjust_rate(0.1))

        a_reset = m.addAction("Reset 1.0×           \\")
        a_reset.triggered.connect(lambda: self.set_rate(1.0))

        self._popup(m, self.btn_speed)

    def adjust_rate(self, delta: float) -> None:
        cur = round(self.player.playbackRate(), 2)
        new_rate = max(0.25, min(3.0, round(cur + delta, 2)))
        self.set_rate(new_rate)

    def set_rate(self, r: float) -> None:
        r = max(0.25, min(3.0, round(r, 2)))
        self.player.setPlaybackRate(r)
        self.btn_speed.text = f"{r:g}×"
        self.btn_speed.update()
        self.surface.osd(f"Speed {r:g}×", 1200)

    def toggle_pause(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek_by(self, ms: int) -> None:
        pos = max(0, min(self._dur or 10**9, self.player.position() + ms))
        self.player.setPosition(int(pos))
        self.surface.osd(f"{'+' if ms > 0 else '−'}{abs(ms) // 1000}s   {fmt_time(pos)}", 900)

    def set_volume(self, v: int | float) -> None:
        v = max(0, min(100, int(v)))
        if self.vol.value() != v:
            self.vol.setValue(v)
        if self.audio is not None:
            self.audio.setVolume(v / 100)
            if v > 0 and self.audio.isMuted():
                self.audio.setMuted(False)
        self.win.cfg["ui"]["volume"] = v
        self.win.cfg["ui"]["muted"] = bool(self.audio and self.audio.isMuted())
        self._sync_vol_icon()

    def change_volume(self, d: int) -> None:
        v = max(0, min(100, self.vol.value() + d))
        self.vol.setValue(v)
        self.set_volume(v)
        self.surface.osd(f"Volume {v}%", 900)
        self.show_ui()

    def toggle_mute(self) -> None:
        if self.audio is None:
            return
        self.audio.setMuted(not self.audio.isMuted())
        self.win.cfg["ui"]["muted"] = self.audio.isMuted()
        self._sync_vol_icon()
        self.surface.osd("Muted" if self.audio.isMuted() else "Sound on", 900)

    def _sync_vol_icon(self) -> None:
        muted = bool(self.audio and self.audio.isMuted()) or self.vol.value() == 0
        self.btn_vol.set_kind("mute" if muted else "vol")

    def _seek_hover(self, frac: float, local_x: int) -> None:
        if frac < 0 or self._dur <= 0:
            self.seek_bubble.hide()
            return
        pos = self.seek.mapTo(self.controls, QPoint(local_x, 0))
        self.seek_bubble.show_time(fmt_time(frac * self._dur), pos.x(), self.seek.y() - 4)

    def show_next_box(self, nxt, entry=None) -> None:
        self._next_ep, self._next_entry, self._countdown = nxt, entry or self.entry, 8
        self._render_next()
        self.next_box.show()
        self.next_box.raise_()
        self.next_timer.start()
        self.show_ui()

    def _render_next(self) -> None:
        target_entry = self._next_entry or self.entry
        if target_entry is not None and target_entry is not self.entry:
            self.lbl_next.setText(
                f"Sequel up next · {target_entry.title} ({self.win.ep_label(target_entry, self._next_ep)})   ({self._countdown})"
            )
        else:
            self.lbl_next.setText(
                f"Up next · {self.win.ep_label(self.entry, self._next_ep)}   ({self._countdown})"
            )
        self.next_box.adjustSize()
        self.next_box.move(
            self.width() - self.next_box.width() - 32,
            self.height() - self.next_box.height() - 150,
        )

    def _tick_next(self) -> None:
        self._countdown -= 1
        if self._countdown <= 0:
            self._play_next_now()
        else:
            self._render_next()

    def _play_next_now(self) -> None:
        nxt = self._next_ep
        target_entry = self._next_entry or self.entry
        self.hide_next_box()
        if nxt is not None and target_entry is not None:
            if target_entry is not self.entry:
                self.win.prog(target_entry)["last"] = time.time()
                self.open(target_entry, nxt, self.win.resume_ms(target_entry, nxt))
            else:
                self.go_episode(nxt)

    def hide_next_box(self) -> None:
        self.next_timer.stop()
        self.next_box.hide()
        self._next_ep = None
        self._next_entry = None

    def keyPressEvent(self, e) -> None:
        k, mod = e.key(), e.modifiers()
        K = Qt.Key
        shift = bool(mod & Qt.KeyboardModifier.ShiftModifier)
        if k in (K.Key_Space, K.Key_K):
            self.toggle_pause()
        elif k == K.Key_Left:
            self.seek_by(-30000 if shift else -5000)
        elif k == K.Key_Right:
            self.seek_by(30000 if shift else 5000)
        elif k == K.Key_J:
            self.seek_by(-10000)
        elif k == K.Key_L:
            self.seek_by(10000)
        elif k == K.Key_Up:
            self.change_volume(5)
        elif k == K.Key_Down:
            self.change_volume(-5)
        elif k == K.Key_M:
            self.toggle_mute()
        elif k in (K.Key_F, K.Key_F11):
            self.win.toggle_fullscreen()
        elif k == K.Key_Escape:
            if self.next_box.isVisible():
                self.hide_next_box()
            elif self.win.isFullScreen():
                self.win.toggle_fullscreen()
            else:
                self.win.exit_player()
        elif k == K.Key_Backspace:
            self.win.exit_player()
        elif k == K.Key_N:
            self.step_episode(1)
        elif k == K.Key_P:
            self.step_episode(-1)
        elif k == K.Key_E:
            self.episodes_menu()
        elif k == K.Key_V:
            self.sub_visible = not self.sub_visible
            self.surface.update()
            self.surface.osd("Subtitles shown" if self.sub_visible else "Subtitles hidden")
        elif k in (K.Key_Z, K.Key_X):
            self.sub_delay += -100 if k == K.Key_Z else 100
            self.surface.osd(f"Subtitle delay {self.sub_delay / 1000:+.1f}s")
            self.on_position(self.player.position())
        elif k == K.Key_BracketLeft:
            self.adjust_rate(-0.25 if shift else -0.1)
        elif k == K.Key_BracketRight:
            self.adjust_rate(0.25 if shift else 0.1)
        elif k == K.Key_Backslash:
            self.set_rate(1.0)
        elif k == K.Key_Home:
            self.player.setPosition(0)
        else:
            e.ignore()
            return
        self.show_ui()
