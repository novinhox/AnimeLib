"""Common UI components, pixmap rendering, scrolling widgets, rows, and responsive grid."""
from __future__ import annotations

from functools import lru_cache
import math
import os
from pathlib import Path
import zlib

import shiboken6

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from AniLibV6.models import Entry
from AniLibV6.theme import D, T, qc, ui_fm, ui_font
from AniLibV6.utils import clear_layout, frame_path, wrap_lines

AA = (
    QPainter.RenderHint.Antialiasing
    | QPainter.RenderHint.SmoothPixmapTransform
    | QPainter.RenderHint.TextAntialiasing
)

# Pixmap caches
_pix_cache: dict[str, QPixmap] = {}
_bake_cache: dict[tuple, QPixmap] = {}
_thumb_cache: dict[tuple, QPixmap] = {}
_thumb_src_cache: dict[tuple, QPixmap] = {}
_frame_thumb_cache: dict[tuple, QPixmap] = {}

_MAX_PIX_CACHE = 400
_MAX_BAKE_CACHE = 600
_MAX_THUMB_CACHE = 400


def load_pixmap(path: str | None) -> QPixmap | None:
    """Load QPixmap with LRU cache."""
    if not path:
        return None
    pm = _pix_cache.get(path)
    if pm is None:
        if len(_pix_cache) >= _MAX_PIX_CACHE:
            _pix_cache.pop(next(iter(_pix_cache)))
        pm = QPixmap(path)
        _pix_cache[path] = pm
    return None if pm.isNull() else pm


def cover_pixmap(path: str | None, w: int, h: int) -> QPixmap | None:
    """Scale and center-crop image to exactly cover w x h."""
    pm = load_pixmap(path)
    if not pm:
        return None
    s = pm.scaled(
        w,
        h,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    return s.copy((s.width() - w) // 2, (s.height() - h) // 2, w, h)


def rounded_pixmap(pm: QPixmap, radius: float) -> QPixmap:
    """Clip a QPixmap to rounded corners."""
    out = QPixmap(pm.size())
    out.setDevicePixelRatio(pm.devicePixelRatio())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHints(AA)
    path = QPainterPath()
    path.addRoundedRect(
        QRectF(0, 0, pm.width() / pm.devicePixelRatio(), pm.height() / pm.devicePixelRatio()),
        radius,
        radius,
    )
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out


@lru_cache(maxsize=512)
def tint_for(text: str) -> QColor:
    """Generate consistent aesthetic pastel hue based on string hash."""
    return QColor.fromHsv(zlib.crc32((text or "?").encode()) % 360, 110, 120)


def bake_poster(entry: Entry, subtitle: str, frac: float, dpr: float, fav: bool = False) -> QPixmap:
    """Pre-render a poster card with image, gradient, title, badges, and progress bar."""
    media = entry.media or {}
    cover = media.get("_cover")
    score = media.get("averageScore")
    key = (
        cover,
        entry.title,
        subtitle,
        round(frac * 50),
        dpr,
        bool(entry.media),
        score,
        fav,
    )
    pm = _bake_cache.get(key)
    if pm is not None:
        return pm
    if len(_bake_cache) >= _MAX_BAKE_CACHE:
        _bake_cache.pop(next(iter(_bake_cache)))

    w, h = T.POSTER_W, T.POSTER_H
    pm = QPixmap(int(w * dpr), int(h * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHints(AA)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, w, h), T.R_CARD, T.R_CARD)
    p.setClipPath(clip)

    img = cover_pixmap(cover, int(w * dpr), int(h * dpr)) if cover else None
    if img:
        img.setDevicePixelRatio(dpr)
        p.drawPixmap(0, 0, img)
    else:
        base = tint_for(entry.title)
        g = QLinearGradient(0, 0, w, h)
        g.setColorAt(0, base.lighter(135))
        g.setColorAt(1, base.darker(230))
        p.fillRect(QRectF(0, 0, w, h), g)
        p.setPen(qc("#ffffff", 70))
        p.setFont(ui_font(84, True, display=True))
        p.drawText(
            QRectF(0, 0, w, h * 0.7),
            int(Qt.AlignmentFlag.AlignCenter),
            (entry.title or "?")[:1].upper(),
        )

    # Ambient bottom vignette gradient
    g = QLinearGradient(0, h * 0.36, 0, h)
    g.setColorAt(0.0, QColor(0, 0, 0, 0))
    g.setColorAt(0.55, QColor(6, 6, 10, 145))
    g.setColorAt(1.0, QColor(6, 6, 10, 240))
    p.fillRect(QRectF(0, h * 0.36, w, h * 0.64), g)

    # Top-left badge: Score pill or NOT MATCHED
    if not entry.media:
        p.setBrush(qc("#08080c", 185))
        p.setPen(QPen(qc("#ffcc66", 90), 1))
        p.drawRoundedRect(QRectF(8, 8, 88, 20), 10, 10)
        p.setPen(qc("#ffcc66"))
        p.setFont(ui_font(9, True, tracking=0.4))
        p.drawText(QRectF(8, 8, 88, 20), int(Qt.AlignmentFlag.AlignCenter), "NOT MATCHED")
    elif score:
        stxt = f"★ {score / 10:.1f}"
        sf = ui_font(10, True)
        sw = ui_fm(10, True).horizontalAdvance(stxt) + 14
        srect = QRectF(8, 8, sw, 20)
        p.setBrush(qc("#08080c", 185))
        p.setPen(QPen(QColor(255, 255, 255, 38), 1))
        p.drawRoundedRect(srect, 10, 10)
        p.setPen(QColor(T.GOLD))
        p.setFont(sf)
        p.drawText(srect, int(Qt.AlignmentFlag.AlignCenter), stxt)

    # Favorite badge (heart)
    if fav:
        fx = 8 + (
            ui_fm(10, True).horizontalAdvance(f"★ {score / 10:.1f}") + 18
            if (entry.media and score)
            else (92 if not entry.media else 0)
        )
        frect = QRectF(fx, 8, 22, 20)
        p.setBrush(qc(T.ACCENT, 215))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(frect, 10, 10)
        p.setPen(QColor("white"))
        p.setFont(ui_font(10, True))
        p.drawText(frect, int(Qt.AlignmentFlag.AlignCenter), "♥")

    pad = 12
    bottom = h - pad - (10 if frac > 0 else 0)
    if subtitle:
        p.setFont(ui_font(11))
        p.setPen(qc("#b8b8ca"))
        p.drawText(
            QRectF(pad, bottom - 15, w - 2 * pad, 15),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            ui_fm(11).elidedText(subtitle, Qt.TextElideMode.ElideRight, int(w - 2 * pad)),
        )
        bottom -= 18

    tf = ui_font(13, True)
    fm = ui_fm(13, True)
    lines = wrap_lines(entry.title, fm, int(w - 2 * pad), 2)
    p.setFont(tf)
    p.setPen(QColor("white"))
    lh = 17
    y = bottom - lh * len(lines)
    for line in lines:
        p.drawText(
            QRectF(pad, y, w - 2 * pad, lh),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            line,
        )
        y += lh

    if frac > 0:
        track = QRectF(pad, h - pad - 4, w - 2 * pad, 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawRoundedRect(track, 2, 2)
        p.setBrush(QColor("white"))
        p.drawRoundedRect(
            QRectF(track.left(), track.top(), max(4.0, track.width() * frac), 4), 2, 2
        )

    # visionOS specular rim highlight
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(255, 255, 255, 34), 1))
    p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), T.R_CARD, T.R_CARD)
    p.end()
    _bake_cache[key] = pm
    return pm


def ep_thumb_size(big: bool) -> tuple[int, int]:
    """Calculate 16:9 thumbnail dimensions."""
    th = (124 if big else 92) - 28
    return round(th * 16 / 9), th


def episode_thumb(media: dict | None, index: int, total: int, big: bool) -> QPixmap | None:
    """Episode thumbnail cropped dynamically from banner or cover."""
    src = (media or {}).get("_banner") or (media or {}).get("_cover")
    pm = load_pixmap(src) if src else None
    if not pm:
        return None
    key = (src, index, total, big)
    out = _thumb_cache.get(key)
    if out is not None:
        return out
    if len(_thumb_cache) >= _MAX_THUMB_CACHE:
        _thumb_cache.pop(next(iter(_thumb_cache)))
    tw, th = ep_thumb_size(big)
    skey = (src, big)
    sc = _thumb_src_cache.get(skey)
    if sc is None:
        if len(_thumb_src_cache) >= 100:
            _thumb_src_cache.pop(next(iter(_thumb_src_cache)))
        sc = pm.scaled(
            int(tw * 1.7),
            int(th * 1.7),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        _thumb_src_cache[skey] = sc
    f = index / (total - 1) if total > 1 else 0.5
    wobble = 0.5 + 0.35 * math.sin(index * 1.9)
    rx, ry = max(0, sc.width() - tw), max(0, sc.height() - th)
    if rx >= ry:
        x, y = int(rx * (0.05 + 0.9 * f)), int(ry * wobble)
    else:
        x, y = int(rx * wobble), int(ry * (0.05 + 0.9 * f))
    out = sc.copy(x, y, tw, th)
    _thumb_cache[key] = out
    return out


def frame_thumb(video: str, big: bool) -> QPixmap | None:
    """Cropped 16:9 thumbnail from the extracted frame, or None if not ready."""
    out = frame_path(video)
    if not out.exists():
        return None
    key = (str(out), big)
    pm = _frame_thumb_cache.get(key)
    if pm is None:
        tw, th = ep_thumb_size(big)
        pm = cover_pixmap(str(out), tw, th)
        if pm is None:
            return None
        if len(_frame_thumb_cache) >= 400:
            _frame_thumb_cache.pop(next(iter(_frame_thumb_cache)))
        _frame_thumb_cache[key] = pm
    return pm


# --------------------------------------------------------------------------- #
# Scroll areas
# --------------------------------------------------------------------------- #
class SmoothScrollArea(QScrollArea):
    """Vertical scroll area with fluid animated momentum scrolling."""

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
        self._target = 0
        self._anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuart)

    def smooth_to(self, value: int | float) -> None:
        sb = self.verticalScrollBar()
        value = max(sb.minimum(), min(sb.maximum(), int(value)))
        self._target = value
        if not T.animations:
            sb.setValue(value)
            return
        self._anim.stop()
        self._anim.setDuration(D(T.SCROLL_MS))
        self._anim.setStartValue(sb.value())
        self._anim.setEndValue(value)
        self._anim.start()

    def smooth_by(self, delta: int | float) -> None:
        sb = self.verticalScrollBar()
        base = (
            self._target
            if self._anim.state() == QPropertyAnimation.State.Running
            else sb.value()
        )
        self.smooth_to(base + delta)

    def wheelEvent(self, e) -> None:
        d = e.pixelDelta().y() or e.angleDelta().y() * 0.9
        if d:
            self.smooth_by(-d)
        e.accept()


class HScroll(QScrollArea):
    """Horizontal scroll area inside a Row forwarding vertical scroll to page."""

    def __init__(self, row) -> None:
        super().__init__()
        self.row = row
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)

    def wheelEvent(self, e) -> None:
        dx, dy = e.angleDelta().x(), e.angleDelta().y()
        if abs(dx) > abs(dy) or e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.row.scroll_by(-(dx or dy))
        else:
            self.row.win.page_wheel(e)
        e.accept()


class ChipStrip(QScrollArea):
    """Horizontal chip strip where mouse wheel scrolls sideways."""

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(44)
        self.viewport().setAutoFillBackground(False)

    def wheelEvent(self, e) -> None:
        sb = self.horizontalScrollBar()
        sb.setValue(sb.value() - (e.angleDelta().x() or e.angleDelta().y()))
        e.accept()


class FadeStack(QStackedWidget):
    """Stacked widget whose transitions feature smooth visionOS cross-fade + slide."""

    def __init__(self) -> None:
        super().__init__()
        self._grp = None
        self._widget = None

    def _finish(self, w: QWidget, base: QPoint) -> None:
        if shiboken6.isValid(w):
            w.setGraphicsEffect(None)
            w.move(base)

    def go(self, index: int, animate: bool = True) -> None:
        if index == self.currentIndex():
            return
        if self._grp is not None and self._grp.state() == QPropertyAnimation.State.Running:
            self._grp.stop()
            if self._widget is not None:
                self._finish(self._widget, QPoint(0, 0))
        w = self.widget(index)
        self.setCurrentIndex(index)
        if not T.animations or not animate:
            return
        self.layout().activate()
        eff = QGraphicsOpacityEffect(w)
        eff.setOpacity(0.0)
        w.setGraphicsEffect(eff)
        base = QPoint(0, 0)
        a = QPropertyAnimation(eff, b"opacity", w)
        a.setDuration(D(T.PAGE_MS))
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.Type.OutQuart)
        b = QPropertyAnimation(w, b"pos", w)
        b.setDuration(D(T.PAGE_MS + 50))
        b.setStartValue(QPoint(0, 24))
        b.setEndValue(base)
        b.setEasingCurve(QEasingCurve.Type.OutExpo)
        g = QParallelAnimationGroup(w)
        g.addAnimation(a)
        g.addAnimation(b)
        g.finished.connect(lambda w=w: self._finish(w, base))
        self._grp, self._widget = g, w
        g.start()


class Toast(QLabel):
    """visionOS floating glass notification pill."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFont(ui_font(14, True))
        self.setStyleSheet(
            "background: rgba(26, 28, 38, 0.94); color: white; "
            "border: 1px solid rgba(255, 255, 255, 0.18); "
            "border-radius: 22px; padding: 12px 26px;"
        )
        self._eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._eff)
        self._eff.setOpacity(0.0)
        self._anim = QPropertyAnimation(self._eff, b"opacity", self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self._fade(0.0))
        self.hide()

    def _fade(self, to: float) -> None:
        self._anim.stop()
        self._anim.setDuration(D(200))
        self._anim.setStartValue(self._eff.opacity())
        self._anim.setEndValue(to)
        self._anim.start()
        if to == 0.0:
            self._anim.finished.connect(self._maybe_hide)

    def _maybe_hide(self) -> None:
        try:
            self._anim.finished.disconnect(self._maybe_hide)
        except (TypeError, RuntimeError):
            pass
        if self._eff.opacity() < 0.05:
            self.hide()

    def reposition(self) -> None:
        par = self.parentWidget()
        if par:
            self.adjustSize()
            self.move((par.width() - self.width()) // 2, par.height() - self.height() - 56)

    def show_message(self, text: str, ms: int = 2800) -> None:
        self.setText(text)
        self.reposition()
        self.show()
        self.raise_()
        self._fade(1.0)
        self._timer.start(ms)


class ArrowButton(QWidget):
    """Frosted circular navigation arrow for scrolling rows."""
    clicked = Signal()

    def __init__(self, parent: QWidget, direction: int) -> None:
        super().__init__(parent)
        self.dir = direction
        self._op = 0.0
        self._over = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._anim = QPropertyAnimation(self, b"op", self)
        self.hide()

    def _get_op(self) -> float:
        return self._op

    def _set_op(self, v: float) -> None:
        self._op = v
        if v <= 0.01 and self.isVisible():
            self.hide()
        elif v > 0.01 and not self.isVisible():
            self.show()
        self.update()

    op = Property(float, _get_op, _set_op)

    def fade_to(self, target: float) -> None:
        if abs(self._op - target) < 0.01:
            return
        self._anim.stop()
        self._anim.setDuration(D(180))
        self._anim.setStartValue(self._op)
        self._anim.setEndValue(target)
        self._anim.start()

    def enterEvent(self, e) -> None:
        self._over = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._over = False
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        p.setOpacity(self._op)
        r = self.rect()
        g = QLinearGradient(r.left(), 0, r.right(), 0)
        if self.dir < 0:
            g.setColorAt(0, QColor(7, 8, 12, 160))
            g.setColorAt(1, QColor(7, 8, 12, 0))
        else:
            g.setColorAt(0, QColor(7, 8, 12, 0))
            g.setColorAt(1, QColor(7, 8, 12, 160))
        p.fillRect(r, g)

        rad = 24 if self._over else 21
        c = QPointF(r.center().x() + (-4 if self.dir < 0 else 4), r.center().y())
        p.setPen(QPen(QColor(255, 255, 255, 75 if self._over else 45), 1))
        p.setBrush(QColor(40, 43, 56, 235 if self._over else 195))
        p.drawEllipse(c, rad, rad)
        pen = QPen(QColor("white"), 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        d = -1 if self.dir < 0 else 1
        k = 6.5
        cx, cy = c.x() + d * 1.5, c.y()
        p.drawLine(QPointF(cx - d * k * 0.55, cy - k), QPointF(cx + d * k * 0.45, cy))
        p.drawLine(QPointF(cx + d * k * 0.45, cy), QPointF(cx - d * k * 0.55, cy + k))


class RowHeader(QWidget):
    """Section title with Apple TV typographic hierarchy and item counter."""

    def __init__(self, title: str, count: int = 0) -> None:
        super().__init__()
        self.title = title
        self.count = count
        self.setFixedHeight(50)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        x = T.MARGIN
        tf = ui_font(21, True, display=True, tracking=0.1)
        fm = ui_fm(21, True, display=True, tracking=0.1)
        tw = fm.horizontalAdvance(self.title)
        p.setFont(tf)
        p.setPen(QColor("white"))
        p.drawText(
            QRectF(x, 12, tw + 10, 30),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.title,
        )
        if self.count > 0:
            cf = ui_font(14, True)
            p.setFont(cf)
            p.setPen(QColor(255, 255, 255, 110))
            p.drawText(
                QRectF(x + tw + 10, 12, 80, 30),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                str(self.count),
            )


class Row(QWidget):
    """Horizontally scrolling poster row with animated arrows and momentum."""

    def __init__(self, win, title: str, cards: list[QWidget]) -> None:
        super().__init__()
        self.win = win
        self._hovered = False
        self._target = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.head = RowHeader(title, len(cards))
        lay.addWidget(self.head)
        self.scroll = HScroll(self)
        inner = QWidget()
        il = QHBoxLayout(inner)
        il.setContentsMargins(T.MARGIN - T.PAD, 0, T.MARGIN, 0)
        il.setSpacing(0)
        for c in cards:
            c.row = self
            il.addWidget(c)
        il.addStretch(1)
        self.scroll.setWidget(inner)
        self.scroll.setFixedHeight(T.SLOT_H + 4)
        lay.addWidget(self.scroll)
        self.left = ArrowButton(self, -1)
        self.right = ArrowButton(self, 1)
        self.left.clicked.connect(lambda: self.scroll_by(-self.scroll.viewport().width() * 0.85))
        self.right.clicked.connect(lambda: self.scroll_by(self.scroll.viewport().width() * 0.85))
        sb = self.scroll.horizontalScrollBar()
        sb.valueChanged.connect(self._update_arrows)
        sb.rangeChanged.connect(lambda *_: self._update_arrows())
        sb.valueChanged.connect(lambda _: self.win.hide_preview(now=True))
        self._anim = QPropertyAnimation(sb, b"value", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def scroll_to(self, value: int | float) -> None:
        sb = self.scroll.horizontalScrollBar()
        value = max(sb.minimum(), min(sb.maximum(), int(value)))
        self._target = value
        if not T.animations:
            sb.setValue(value)
            return
        self._anim.stop()
        self._anim.setDuration(D(T.SCROLL_MS + 100))
        self._anim.setStartValue(sb.value())
        self._anim.setEndValue(value)
        self._anim.start()

    def scroll_by(self, dx: int | float) -> None:
        sb = self.scroll.horizontalScrollBar()
        base = (
            self._target
            if self._anim.state() == QPropertyAnimation.State.Running
            else sb.value()
        )
        self.scroll_to(base + dx)

    def ensure_visible(self, card: QWidget) -> None:
        sb = self.scroll.horizontalScrollBar()
        vw = self.scroll.viewport().width()
        left, right = card.x() - T.PAD - 8, card.x() + card.width() + 8
        if left < sb.value():
            self.scroll_to(left - 30)
        elif right > sb.value() + vw:
            self.scroll_to(right - vw + 30)

    def _update_arrows(self, *_) -> None:
        sb = self.scroll.horizontalScrollBar()
        self.left.fade_to(1.0 if self._hovered and sb.value() > 2 else 0.0)
        self.right.fade_to(1.0 if self._hovered and sb.value() < sb.maximum() - 2 else 0.0)

    def enterEvent(self, e) -> None:
        self._hovered = True
        self._update_arrows()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hovered = False
        self._update_arrows()
        super().leaveEvent(e)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        y, h = self.head.height(), self.scroll.height()
        aw = 58
        self.left.setGeometry(0, y, aw, h)
        self.right.setGeometry(self.width() - aw, y, aw, h)
        self.left.raise_()
        self.right.raise_()


class CardGrid(QWidget):
    """Responsive card grid with fluid reflow and keyboard navigation groups."""

    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self.cards: list[QWidget] = []
        self.groups: list[list[QWidget]] = []

    def set_cards(self, cards: list[QWidget]) -> None:
        for c in self.cards:
            c.hide()
            c.deleteLater()
        self.cards = cards
        for c in cards:
            c.setParent(self)
            c.show()
        self.relayout()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.relayout()

    def relayout(self) -> None:
        x0 = T.MARGIN - T.PAD
        cols = max(1, (self.width() - x0 - (T.MARGIN - T.PAD)) // T.SLOT_W)
        for i, c in enumerate(self.cards):
            r, col = divmod(i, cols)
            c.move(x0 + col * T.SLOT_W, r * T.SLOT_H)
        rows = -(-len(self.cards) // cols) if self.cards else 0
        self.setMinimumHeight(rows * T.SLOT_H + 8)
        self.groups = [self.cards[i : i + cols] for i in range(0, len(self.cards), cols)]


def draw_app_icon(size: int) -> QPixmap:
    """Render modern visionOS squircle app icon with gradient, play glyph, and sparkle."""
    s = float(size)
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHints(AA)
    body = QPainterPath()
    body.addRoundedRect(QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92), s * 0.225, s * 0.225)
    g = QLinearGradient(0, 0, 0, s)
    g.setColorAt(0, QColor("#ff4f6d"))
    g.setColorAt(0.55, QColor("#d02a6e"))
    g.setColorAt(1, QColor("#6d1fb4"))
    p.fillPath(body, g)
    p.save()
    p.setClipPath(body)
    hl = QLinearGradient(0, 0, 0, s * 0.62)
    hl.setColorAt(0, QColor(255, 255, 255, 80))
    hl.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillRect(QRectF(0, 0, s, s * 0.62), hl)
    p.restore()

    cx, cy, h, w = s * 0.535, s * 0.53, s * 0.235, s * 0.40
    tri = QPainterPath()
    tri.moveTo(cx - w * 0.42, cy - h)
    tri.lineTo(cx + w * 0.58, cy)
    tri.lineTo(cx - w * 0.42, cy + h)
    tri.closeSubpath()
    pen = QPen(QColor(0, 0, 0, 70), s * 0.07)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(QColor(0, 0, 0, 70))
    p.drawPath(tri.translated(0, s * 0.02))
    pen = QPen(QColor("white"), s * 0.07)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(QColor("white"))
    p.drawPath(tri)

    if size >= 40:
        sx, sy, R, k = s * 0.755, s * 0.27, s * 0.105, s * 0.022
        star = QPainterPath()
        star.moveTo(sx, sy - R)
        star.quadTo(sx + k, sy - k, sx + R, sy)
        star.quadTo(sx + k, sy + k, sx, sy + R)
        star.quadTo(sx - k, sy + k, sx - R, sy)
        star.quadTo(sx - k, sy - k, sx, sy - R)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("white"))
        p.drawPath(star)
    p.end()
    return pm
