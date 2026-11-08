"""visionOS cards: PosterCard, EpisodeCard, PreviewBanner, and PreviewCard."""
from __future__ import annotations

import math
import shiboken6

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QParallelAnimationGroup,
    QRect,
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
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from AniLibV6.models import Entry
from AniLibV6.theme import D, T, qc, ui_fm, ui_font
from AniLibV6.ui.common import (
    AA,
    bake_poster,
    ep_thumb_size,
    load_pixmap,
    tint_for,
)
from AniLibV6.ui.components import MiniBar
from AniLibV6.utils import shimmer, wrap_lines


class PosterCard(QWidget):
    """Custom-painted poster card featuring tvOS-style focus lift and mouse parallax tilt."""

    def __init__(
        self, win, entry: Entry, subtitle: str = "", loading: bool = False, fade_in: bool = False, delay_ms: int = 40
    ) -> None:
        super().__init__()
        self.win = win
        self.entry = entry
        self.row = None
        n = len(entry.episodes)
        if not subtitle:
            seq = win.sequel_entry(entry)
            preq = win.prequel_entry(entry)
            base_sub = f"{n} episode{'' if n == 1 else 's'}"
            if seq:
                subtitle = f"{base_sub} · Sequel →"
            elif preq:
                subtitle = f"{base_sub} · ← Prequel"
            else:
                subtitle = base_sub
        self.subtitle = subtitle
        self.loading = loading
        self._hover = 0.0
        self._reveal = 0.0 if fade_in else 1.0
        self._kb = False
        self._pressed = False
        self._baked: QPixmap | None = None
        self._more_rect = QRectF()
        self._tilt = QPointF(0.0, 0.0)

        self.setFixedSize(T.SLOT_W, T.SLOT_H)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._ha = QPropertyAnimation(self, b"hover", self)
        self._ha.setEasingCurve(QEasingCurve.Type.OutBack)
        self._ra = QPropertyAnimation(self, b"reveal", self)

        if loading or fade_in:
            shimmer().tick.connect(self._on_tick)
        if fade_in:
            QTimer.singleShot(delay_ms, self._start_reveal)

    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, v: float) -> None:
        self._hover = v
        self.update()

    hover = Property(float, _get_hover, _set_hover)

    def _get_reveal(self) -> float:
        return self._reveal

    def _set_reveal(self, v: float) -> None:
        self._reveal = v
        self.update()

    reveal = Property(float, _get_reveal, _set_reveal)

    def _start_reveal(self) -> None:
        if not shiboken6.isValid(self):
            return
        self._ra.stop()
        self._ra.setDuration(D(520))
        self._ra.setStartValue(0.0)
        self._ra.setEndValue(1.0)
        self._ra.setEasingCurve(QEasingCurve.Type.OutQuart)
        self._ra.start()

    def _on_tick(self) -> None:
        if self.loading or self._reveal < 1.0:
            self.update()

    def _animate_hover(self, target: float) -> None:
        self._ha.stop()
        self._ha.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._ha.setDuration(D(T.HOVER_MS if target > self._hover else int(T.HOVER_MS * 0.85)))
        self._ha.setStartValue(self._hover)
        self._ha.setEndValue(target)
        self._ha.start()

    def enterEvent(self, e) -> None:
        self._animate_hover(1.0)
        self.win.card_entered(self)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._tilt = QPointF(0.0, 0.0)
        self._animate_hover(0.0)
        self.win.card_left(self)
        super().leaveEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if self.width() > 0 and self.height() > 0:
            pos = e.position()
            self._tilt = QPointF(
                max(-1.0, min(1.0, pos.x() / self.width() * 2.0 - 1.0)),
                max(-1.0, min(1.0, pos.y() / self.height() * 2.0 - 1.0)),
            )
            if T.animations:
                self.update()
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            if self._hover > 0.25 and self._more_rect.contains(e.position()):
                self.win.card_menu(self.entry, e.globalPosition().toPoint())
                return
            self._pressed = True
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if (
            e.button() == Qt.MouseButton.LeftButton
            and self._pressed
            and self.rect().contains(e.position().toPoint())
        ):
            self.win.open_entry(self.entry)
        self._pressed = False
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e) -> None:
        self.win.card_menu(self.entry, e.globalPos())

    def keyPressEvent(self, e) -> None:
        k = e.key()
        moves = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if k in moves:
            self.win.nav_move(self, *moves[k])
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.win.open_entry(self.entry)
        elif k == Qt.Key.Key_Space:
            self.win.play_next(self.entry)
        else:
            e.ignore()

    def focusInEvent(self, e) -> None:
        self._kb = e.reason() in (
            Qt.FocusReason.TabFocusReason,
            Qt.FocusReason.BacktabFocusReason,
            Qt.FocusReason.ShortcutFocusReason,
        )
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e) -> None:
        self.update()
        super().focusOutEvent(e)

    def _paint_skeleton(self, p: QPainter, rect: QRectF) -> None:
        path = QPainterPath()
        path.addRoundedRect(rect, T.R_CARD, T.R_CARD)
        p.save()
        p.setClipPath(path)
        p.fillRect(rect, qc("#161822"))
        band = rect.width() * 0.9
        x = rect.left() - band + shimmer().phase * (rect.width() + band * 2)
        g = QLinearGradient(x, 0, x + band, 0)
        g.setColorAt(0, qc("#ffffff", 0))
        g.setColorAt(0.5, qc("#ffffff", 26))
        g.setColorAt(1, qc("#ffffff", 0))
        p.fillRect(rect, g)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qc("#262938"))
        p.drawRoundedRect(
            QRectF(rect.left() + 12, rect.bottom() - 46, rect.width() * 0.7, 10), 5, 5
        )
        p.drawRoundedRect(
            QRectF(rect.left() + 12, rect.bottom() - 28, rect.width() * 0.4, 8), 4, 4
        )
        p.restore()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        hv = max(0.0, min(1.0, self._hover))
        s = 1 + T.HOVER_SCALE * self._hover
        lift = -4.0 * self._hover - (1.0 - self._reveal) * 14.0
        w, h = T.POSTER_W * s, T.POSTER_H * s
        px, py = self._tilt.x() * 2.0 * hv, self._tilt.y() * 1.5 * hv
        rect = QRectF((self.width() - w) / 2 + px, (self.height() - h) / 2 + lift + py, w, h)
        R = T.R_CARD * s

        if hv > 0.02:
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(1, 10):
                p.setBrush(QColor(0, 0, 0, int(32 * hv * (1 - i / 10))))
                p.drawRoundedRect(rect.adjusted(-i, -i + 6, i, i + 6), R + i, R + i)

        if self.loading or self._reveal < 1.0:
            self._paint_skeleton(p, rect)

        if not self.loading:
            if self._baked is None:
                frac = self.win.fraction(self.entry)
                fav = self.win.is_fav(self.entry)
                self._baked = bake_poster(
                    self.entry, self.subtitle, frac, self.devicePixelRatioF(), fav=fav
                )
            p.setOpacity(self._reveal)
            p.drawPixmap(rect, self._baked, QRectF(0, 0, self._baked.width(), self._baked.height()))

            if hv > 0.02:
                cx = rect.center().x() + self._tilt.x() * rect.width() * 0.45
                cy = rect.top() + rect.height() * (0.25 + 0.25 * self._tilt.y())
                spec = QRadialGradient(QPointF(cx, cy), rect.width() * 0.95)
                spec.setColorAt(0.0, QColor(255, 255, 255, int(48 * hv)))
                spec.setColorAt(0.55, QColor(255, 255, 255, int(10 * hv)))
                spec.setColorAt(1.0, QColor(255, 255, 255, 0))
                path = QPainterPath()
                path.addRoundedRect(rect, R, R)
                p.fillPath(path, spec)
            p.setOpacity(1.0)

        if hv > 0.02:
            p.setPen(QPen(QColor(255, 255, 255, int(75 * hv)), 1.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), R, R)

        if self.hasFocus() and self._kb:
            p.setPen(QPen(QColor(255, 255, 255, 235), 3.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), R + 3, R + 3)

        if hv > 0.25 and not self.loading:
            c = QPointF(rect.right() - 20, rect.top() + 20)
            self._more_rect = QRectF(c.x() - 15, c.y() - 15, 30, 30)
            p.setOpacity(hv)
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
            p.setBrush(QColor(20, 22, 30, 180))
            p.drawEllipse(c, 14, 14)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("white"))
            for dx in (-5.5, 0, 5.5):
                p.drawEllipse(QPointF(c.x() + dx, c.y()), 1.7, 1.7)
            p.setOpacity(1.0)


class EpisodeCard(QWidget):
    """visionOS frosted glass episode card with thumbnail, tags, and watched toggle."""

    clicked = Signal()
    toggled = Signal()

    def __init__(
        self,
        label: str,
        filename: str,
        number: int | None,
        watched: bool,
        is_next: bool,
        has_sub: bool,
        tint: str,
        big: bool = False,
        thumb: QPixmap | None = None,
        frac: float = 0.0,
    ) -> None:
        super().__init__()
        self.label, self.filename, self.number = label, filename, number
        self.thumb = thumb
        self.frac = frac
        self.watched = watched
        self.is_next = is_next
        self.has_sub = has_sub
        self.tint = tint
        self.big = big

        self._hover = 0.0
        self._appear = 1.0
        self._check = QRectF()
        self.setFixedHeight(124 if big else 94)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._ha = QPropertyAnimation(self, b"hover", self)
        self._aa = QPropertyAnimation(self, b"appear", self)

    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, v: float) -> None:
        self._hover = v
        self.update()

    hover = Property(float, _get_hover, _set_hover)

    def _get_appear(self) -> float:
        return self._appear

    def _set_appear(self, v: float) -> None:
        self._appear = v
        self.update()

    appear = Property(float, _get_appear, _set_appear)

    def start_appear(self, delay: int) -> None:
        self._appear = 0.0
        QTimer.singleShot(delay, self._run_appear)

    def _run_appear(self) -> None:
        if not shiboken6.isValid(self):
            return
        self._aa.stop()
        self._aa.setDuration(D(420))
        self._aa.setStartValue(0.0)
        self._aa.setEndValue(1.0)
        self._aa.setEasingCurve(QEasingCurve.Type.OutQuart)
        self._aa.start()

    def _hover_to(self, t: float) -> None:
        self._ha.stop()
        self._ha.setDuration(D(190))
        self._ha.setEasingCurve(QEasingCurve.Type.OutQuart)
        self._ha.setStartValue(self._hover)
        self._ha.setEndValue(t)
        self._ha.start()

    def enterEvent(self, e) -> None:
        self._hover_to(1.0)

    def leaveEvent(self, e) -> None:
        self._hover_to(0.0)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or not self.rect().contains(e.position().toPoint()):
            return
        if self._check.adjusted(-8, -8, 8, 8).contains(e.position()):
            self.toggled.emit()
        else:
            self.clicked.emit()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        p.setOpacity(self._appear)
        p.translate(self._hover * 3.0, (1 - self._appear) * 16)
        W, H = self.width(), self.height()
        r = QRectF(0.5, 0.5, W - 4, H - 1)

        # visionOS frosted glass background
        alpha_base = int(14 + 18 * self._hover)
        p.setBrush(QColor(255, 255, 255, alpha_base))
        if self.is_next:
            p.setPen(QPen(QColor(T.ACCENT), 1.8))
        else:
            p.setPen(QPen(QColor(255, 255, 255, int(22 + 36 * self._hover)), 1))
        p.drawRoundedRect(r, 16, 16)

        # Specular top rim
        if self._hover > 0.01:
            g_rim = QLinearGradient(r.topLeft(), r.topRight())
            g_rim.setColorAt(0.0, QColor(255, 255, 255, 0))
            g_rim.setColorAt(0.5, QColor(255, 255, 255, int(50 * self._hover)))
            g_rim.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setPen(QPen(g_rim, 1.2))
            p.drawLine(QPointF(r.left() + 16, r.top()), QPointF(r.right() - 16, r.top()))

        # Video thumbnail
        tw, th = ep_thumb_size(self.big)
        thumb = QRectF(14, (H - th) / 2, tw, th)
        path = QPainterPath()
        path.addRoundedRect(thumb, 10, 10)
        p.save()
        p.setClipPath(path)

        if self.thumb is not None:
            p.drawPixmap(thumb.topLeft(), self.thumb)
        else:
            g = QLinearGradient(thumb.topLeft(), thumb.bottomRight())
            t = QColor(self.tint)
            g.setColorAt(0, t.lighter(125))
            g.setColorAt(1, t.darker(230))
            p.fillRect(thumb, g)

        # Soft dark gradient over thumbnail
        p.fillRect(thumb, QColor(0, 0, 0, 125 if self.watched else 70))
        g = QLinearGradient(0, thumb.top(), 0, thumb.bottom())
        g.setColorAt(0.55, QColor(0, 0, 0, 0))
        g.setColorAt(1.0, QColor(0, 0, 0, 120))
        p.fillRect(thumb, g)

        # Episode-number badge (top-left)
        if self.number is not None:
            bf = ui_font(11, True)
            bt = str(self.number)
            bw = ui_fm(11, True).horizontalAdvance(bt) + 14
            badge = QRectF(thumb.left() + 7, thumb.top() + 7, max(24, bw), 19)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 175))
            p.drawRoundedRect(badge, 9.5, 9.5)
            p.setPen(QColor("white"))
            p.setFont(bf)
            p.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), bt)

        # Status icon in the center: check = watched, play = up next; hover shows play
        c = thumb.center()
        status_op = (1.0 - self._hover) if (self.watched or self.is_next) else 0.0
        if status_op > 0.01:
            p.setOpacity(self._appear * status_op)
            p.setPen(Qt.PenStyle.NoPen)
            if self.watched:
                p.setBrush(QColor(T.GREEN))
                p.drawEllipse(c, 17, 17)
                pen = QPen(QColor("#08090d"), 3)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                p.drawPolyline(
                    [
                        QPointF(c.x() - 6.5, c.y()),
                        QPointF(c.x() - 2, c.y() + 5),
                        QPointF(c.x() + 7, c.y() - 5),
                    ]
                )
            else:
                p.setBrush(QColor(255, 255, 255, 235))
                p.drawEllipse(c, 17, 17)
                tri = QPainterPath()
                tri.moveTo(c.x() - 4.5, c.y() - 8)
                tri.lineTo(c.x() + 9, c.y())
                tri.lineTo(c.x() - 4.5, c.y() + 8)
                tri.closeSubpath()
                p.setBrush(QColor(17, 17, 17))
                p.drawPath(tri)
            p.setOpacity(self._appear)

        if self._hover > 0.01:
            p.fillRect(thumb, QColor(0, 0, 0, int(70 * self._hover)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, int(240 * self._hover)))
            p.drawEllipse(c, 19, 19)
            tri = QPainterPath()
            tri.moveTo(c.x() - 5, c.y() - 9)
            tri.lineTo(c.x() + 10, c.y())
            tri.lineTo(c.x() - 5, c.y() + 9)
            tri.closeSubpath()
            p.setBrush(QColor(17, 17, 17, int(255 * self._hover)))
            p.drawPath(tri)

        # Progress bar capsule inside thumbnail bottom
        bar = QRectF(thumb.left(), thumb.bottom() - 4, thumb.width(), 4)
        p.fillRect(bar, QColor(0, 0, 0, 150))
        if self.watched:
            p.fillRect(bar, QColor(T.ACCENT))
        elif self.frac > 0:
            p.fillRect(
                QRectF(bar.left(), bar.top(), bar.width() * min(1.0, self.frac), bar.height()),
                QColor(T.ACCENT),
            )
        p.restore()

        # Episode metadata & title
        x = thumb.right() + 20
        right = W - 70
        p.setPen(QColor("white"))
        tpx = 16 if self.big else 15
        p.setFont(ui_font(tpx, True))
        fm = ui_fm(tpx, True)
        ty = 18 if not self.big else 26
        p.drawText(
            QRectF(x, ty, right - x, 22),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            fm.elidedText(self.label, Qt.TextElideMode.ElideRight, int(right - x)),
        )

        p.setPen(QColor(T.MUTED))
        p.setFont(ui_font(12))
        fm = ui_fm(12)
        p.drawText(
            QRectF(x, ty + 24, right - x, 18),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            fm.elidedText(self.filename, Qt.TextElideMode.ElideMiddle, int(right - x)),
        )

        # Tags
        tags = (
            ([("UP NEXT", T.ACCENT, "white")] if self.is_next else [])
            + ([("IN PROGRESS", "#3a2e1d", "#ffcc66")] if (self.frac > 0 and not self.watched) else [])
            + ([("SUBS", "#262838", "#c8c8e0")] if self.has_sub else [])
            + ([("WATCHED", "#173624", T.GREEN)] if self.watched else [])
        )
        p.setFont(ui_font(10, True))
        fm = ui_fm(10, True)
        tx, tyy = x, ty + 48
        for text, bgc, fgc in tags:
            cw = fm.horizontalAdvance(text) + 16
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(bgc))
            p.drawRoundedRect(QRectF(tx, tyy, cw, 20), 10, 10)
            p.setPen(QColor(fgc))
            p.drawText(QRectF(tx, tyy, cw, 20), int(Qt.AlignmentFlag.AlignCenter), text)
            tx += cw + 6

        # Circular checkmark toggle button
        c = QPointF(W - 36, H / 2)
        self._check = QRectF(c.x() - 15, c.y() - 15, 30, 30)
        if self.watched:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T.GREEN))
            p.drawEllipse(c, 14, 14)
            pen = QPen(QColor("#08090d"), 2.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPolyline(
                [
                    QPointF(c.x() - 5.5, c.y()),
                    QPointF(c.x() - 1.5, c.y() + 4),
                    QPointF(c.x() + 6, c.y() - 4.5),
                ]
            )
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 80 + int(110 * self._hover)), 1.8))
            p.drawEllipse(c, 13, 13)


class PreviewBanner(QWidget):
    """Banner widget inside the hover preview card."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(168)
        self.pm: QPixmap | None = None
        self.title = ""
        self.tint = QColor("#333")
        self._scaled: QPixmap | None = None
        self._key: tuple | None = None

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h + 20), 16, 16)
        p.setClipPath(path)

        if self.pm:
            key = (w, h, self.pm.cacheKey())
            if key != self._key or self._scaled is None:
                self._scaled = self.pm.scaled(
                    w,
                    h,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._key = key
            s = self._scaled
            p.drawPixmap((w - s.width()) // 2, (h - s.height()) // 2, s)
        else:
            g = QLinearGradient(0, 0, w, h)
            g.setColorAt(0, self.tint.lighter(120))
            g.setColorAt(1, self.tint.darker(220))
            p.fillRect(self.rect(), g)

        g = QLinearGradient(0, h * 0.35, 0, h)
        g.setColorAt(0, QColor(20, 22, 30, 0))
        g.setColorAt(1, QColor(20, 22, 30, 255))
        p.fillRect(self.rect(), g)

        f = ui_font(19, True)
        lines = wrap_lines(self.title, ui_fm(19, True), w - 32, 2)
        p.setFont(f)
        p.setPen(QColor("white"))
        y = h - 12 - 24 * len(lines)
        for line in lines:
            p.drawText(
                QRectF(16, y, w - 32, 24),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                line,
            )
            y += 24


class PreviewCard(QFrame):
    """visionOS expanded hover card with backdrop shadow, quick actions and watch progress."""

    W, H, SH = 330, 312, 14

    def __init__(self, win, parent: QWidget) -> None:
        super().__init__(parent)
        self.win = win
        self.entry: Entry | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(self.SH, self.SH, self.SH, self.SH)
        lay.setSpacing(0)

        self.banner = PreviewBanner()
        lay.addWidget(self.banner)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 8, 16, 14)
        bl.setSpacing(9)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.play = QPushButton("▶")
        self.play.setObjectName("circle_primary")
        self.fav = QPushButton("♡")
        self.fav.setObjectName("circle")
        self.fav.setToolTip("Add to / Remove from My List")
        self.info = QPushButton("ⓘ")
        self.info.setObjectName("circle")
        self.more = QPushButton("⋯")
        self.more.setObjectName("circle")

        for b in (self.play, self.fav, self.info, self.more):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self.play)
        row.addWidget(self.fav)
        row.addWidget(self.info)
        row.addWidget(self.more)
        row.addStretch(1)

        self.meta = QLabel()
        self.meta.setStyleSheet(f"color: {T.GREEN}; font-weight: 700;")
        row.addWidget(self.meta)
        bl.addLayout(row)

        self.genres = QLabel()
        self.genres.setStyleSheet(f"color: {T.MUTED}; font-size: 12px;")
        bl.addWidget(self.genres)

        self.prog_label = QLabel()
        self.prog_label.setStyleSheet("color: #cfcfda; font-size: 12px;")
        bl.addWidget(self.prog_label)

        self.bar = MiniBar()
        bl.addWidget(self.bar)

        self.rel_btn = QPushButton()
        self.rel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rel_btn.setFixedHeight(28)
        self.rel_btn.setStyleSheet(
            "QPushButton {"
            "  background: rgba(229, 9, 20, 0.18);"
            "  color: #ff6b72;"
            "  border: 1px solid rgba(229, 9, 20, 0.45);"
            "  border-radius: 10px;"
            "  padding: 0 10px;"
            "  font-size: 11px;"
            "  font-weight: 700;"
            "  text-align: left;"
            "}"
            "QPushButton:hover {"
            "  background: rgba(229, 9, 20, 0.32);"
            "  color: #ffffff;"
            "  border-color: #e50914;"
            "}"
        )
        self.rel_btn.hide()
        self._rel_target: Entry | None = None
        self.rel_btn.clicked.connect(
            lambda: self._rel_target
            and (self.win.hide_preview(now=True), self.win.open_entry(self._rel_target))
        )
        bl.addWidget(self.rel_btn)

        lay.addWidget(body)

        self.play.clicked.connect(
            lambda: self.entry and (self.win.hide_preview(now=True), self.win.play_next(self.entry))
        )
        self.fav.clicked.connect(self._toggle_fav)
        self.info.clicked.connect(
            lambda: self.entry and (self.win.hide_preview(now=True), self.win.open_entry(self.entry))
        )
        self.more.clicked.connect(
            lambda: self.entry and self.win.card_menu(self.entry, self.mapToGlobal(QPoint(100, 100)))
        )

        self._eff = QGraphicsOpacityEffect(self)
        self._eff.setOpacity(0.0)
        self.setGraphicsEffect(self._eff)
        self._grp: QParallelAnimationGroup | None = None
        self.hide()

    def _toggle_fav(self) -> None:
        if not self.entry:
            return
        self.win.toggle_fav(self.entry)
        self._sync_fav()

    def _sync_fav(self) -> None:
        is_f = self.entry and self.win.is_fav(self.entry)
        self.fav.setText("♥" if is_f else "♡")
        self.fav.setStyleSheet(f"color: {T.ACCENT}; border-color: {T.ACCENT};" if is_f else "")

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        r = QRectF(self.rect()).adjusted(self.SH, self.SH, -self.SH, -self.SH)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(1, self.SH):
            p.setBrush(QColor(0, 0, 0, int(46 * (1 - i / self.SH) ** 1.6)))
            p.drawRoundedRect(r.adjusted(-i, -i + 5, i, i + 5), 16 + i, 16 + i)
        p.setBrush(QColor(T.SURFACE))
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.drawRoundedRect(r, 16, 16)

    def mousePressEvent(self, e) -> None:
        if self.entry and e.button() == Qt.MouseButton.LeftButton:
            self.win.hide_preview(now=True)
            self.win.open_entry(self.entry)

    def enterEvent(self, e) -> None:
        self.win.preview_hide_timer.stop()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.win.preview_hide_timer.start(220)
        super().leaveEvent(e)

    def fill(self, e: Entry) -> None:
        self.entry = e
        m = e.media or {}
        self.banner.pm = load_pixmap(m.get("_banner")) or load_pixmap(m.get("_cover"))
        self.banner.tint = QColor(
            (m.get("coverImage") or {}).get("color") or tint_for(e.title).name()
        )
        self.banner.title = e.title
        self.banner.update()

        bits = []
        if m.get("averageScore"):
            bits.append(f"★ {m['averageScore'] / 10:.1f}")
        if m.get("seasonYear"):
            bits.append(str(m["seasonYear"]))
        self.meta.setText("   ".join(bits))
        self.genres.setText(
            "  •  ".join((m.get("genres") or [])[:3]) or "Not matched on AniList"
        )
        n = len(e.episodes)
        w = len(self.win.watched(e) & e._ep_keys)
        self.prog_label.setText(
            f"{w} of {n} episodes watched" if w else f"{n} episode{'' if n == 1 else 's'}"
        )
        self.bar.frac = w / n if n else 0
        self.bar.update()
        self._sync_fav()

        seq = self.win.sequel_entry(e)
        preq = self.win.prequel_entry(e)
        if seq:
            self._rel_target = seq
            st = seq.title if len(seq.title) <= 28 else seq.title[:26].rstrip() + "…"
            self.rel_btn.setText(f"⏭  Sequel in Library: {st}  →")
            self.rel_btn.show()
            self.H = 346
        elif preq:
            self._rel_target = preq
            pt = preq.title if len(preq.title) <= 28 else preq.title[:26].rstrip() + "…"
            self.rel_btn.setText(f"⏮  Prequel in Library: {pt}  →")
            self.rel_btn.show()
            self.H = 346
        else:
            self._rel_target = None
            self.rel_btn.hide()
            self.H = 312

    def show_for(self, card: PosterCard) -> None:
        root = self.parentWidget()
        self.fill(card.entry)
        fw, fh = self.W + 2 * self.SH, self.H + 2 * self.SH
        c = card.mapTo(root, QPoint(card.width() // 2, card.height() // 2))
        x = max(4, min(root.width() - fw - 4, c.x() - fw // 2))
        y = max(T.NAV_H - 6, min(root.height() - fh - 4, c.y() - fh // 2 - 14))
        end = QRect(x, y, fw, fh)
        k = 0.78
        sw, sh = int(fw * k), int(fh * k)
        start = QRect(c.x() - sw // 2, c.y() - sh // 2, sw, sh)

        if self._grp is not None:
            self._grp.stop()
        self.setGeometry(end if not T.animations else start)
        self.show()
        self.raise_()

        if not T.animations:
            self._eff.setOpacity(1.0)
            return

        a = QPropertyAnimation(self, b"geometry", self)
        a.setDuration(D(280))
        a.setStartValue(start)
        a.setEndValue(end)
        a.setEasingCurve(QEasingCurve.Type.OutBack)

        b = QPropertyAnimation(self._eff, b"opacity", self)
        b.setDuration(D(220))
        b.setStartValue(self._eff.opacity())
        b.setEndValue(1.0)
        b.setEasingCurve(QEasingCurve.Type.OutQuart)

        g = QParallelAnimationGroup(self)
        g.addAnimation(a)
        g.addAnimation(b)
        self._grp = g
        g.start()

    def hide_animated(self, now: bool = False) -> None:
        if self._grp is not None:
            self._grp.stop()
        if now or not T.animations or not self.isVisible():
            self._eff.setOpacity(0.0)
            self.hide()
            return
        b = QPropertyAnimation(self._eff, b"opacity", self)
        b.setDuration(D(140))
        b.setStartValue(self._eff.opacity())
        b.setEndValue(0.0)
        b.finished.connect(lambda: self._eff.opacity() < 0.05 and self.hide())
        self._grp = b
        b.start()
