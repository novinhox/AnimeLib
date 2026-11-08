"""VisionOS floating Hero banner and Detail page dynamic header banner."""
from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
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
    QPixmap,
)
from PySide6.QtWidgets import (
    QPushButton,
    QWidget,
)

from AniLibV6.theme import D, T, ui_fm, ui_font
from AniLibV6.ui.common import AA, tint_for
from AniLibV6.utils import wrap_lines


class BannerWidget(QWidget):
    """Banner image with gradients; supports a zoom-out intro animation."""

    def __init__(self, height: int) -> None:
        super().__init__()
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)
        self.pm: QPixmap | None = None
        self.tint = QColor("#262626")
        self._scaled: QPixmap | None = None
        self._key: tuple | None = None
        self._zoom = 1.0
        self._za = QPropertyAnimation(self, b"zoom", self)

    def _get_zoom(self) -> float:
        return self._zoom

    def _set_zoom(self, v: float) -> None:
        self._zoom = v
        self.update()

    zoom = Property(float, _get_zoom, _set_zoom)

    def zoom_in(self) -> None:
        self._za.stop()
        self._za.setDuration(D(900))
        self._za.setStartValue(1.12)
        self._za.setEndValue(1.0)
        self._za.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._za.start()

    def set_content(self, pixmap: QPixmap | None, tint: str | None = None) -> None:
        self.pm = pixmap
        self.tint = QColor(tint) if tint else QColor("#262626")
        self._scaled, self._key = None, None
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        r = self.rect()
        if self.pm:
            key = (self.width(), self.height(), self.pm.cacheKey())
            if key != self._key:
                self._scaled = self.pm.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._key = key
            s = self._scaled
            p.save()
            c = QPointF(r.center())
            p.translate(c)
            p.scale(self._zoom, self._zoom)
            p.translate(-c)
            p.drawPixmap(QPointF((r.width() - s.width()) / 2, (r.height() - s.height()) / 2), s)
            p.restore()
        else:
            g = QLinearGradient(0, 0, 0, r.height())
            g.setColorAt(0, self.tint.darker(150))
            g.setColorAt(1, QColor(T.BG))
            p.fillRect(r, g)

        # Scrim gradients for readable header typography
        g1 = QLinearGradient(0, 0, 0, r.height())
        g1.setColorAt(0.3, QColor(7, 8, 12, 0))
        g1.setColorAt(0.85, QColor(7, 8, 12, 210))
        g1.setColorAt(1.0, QColor(T.BG))
        p.fillRect(r, g1)

        g2 = QLinearGradient(0, 0, r.width() * 0.7, 0)
        g2.setColorAt(0, QColor(7, 8, 12, 195))
        g2.setColorAt(0.6, QColor(7, 8, 12, 90))
        g2.setColorAt(1, QColor(7, 8, 12, 0))
        p.fillRect(r, g2)

        g3 = QLinearGradient(0, 0, 0, 110)
        g3.setColorAt(0, QColor(7, 8, 12, 180))
        g3.setColorAt(1, QColor(7, 8, 12, 0))
        p.fillRect(QRectF(0, 0, r.width(), 110), g3)


class HeroBanner(QWidget):
    """Home hero (visionOS style): a floating rounded glass card with auto-rotating
    featured anime, cross-fade + Ken Burns zoom, tinted ambient glow, and progress pager."""

    BTN_H = 48
    INNER = 44
    TOP_PAD = T.NAV_H + 12
    BOTTOM_PAD = 44  # Dedicated padding to prevent ambient glow clipping

    def __init__(self, win, slides: list[dict], start: int = 0) -> None:
        super().__init__()
        self.win = win
        self.slides = slides
        self.index = start % len(slides) if slides else 0
        self.prev = -1
        self._fade = 1.0
        self._kb_zoom = 1.0
        self._dots: list[QRectF] = []
        self.setMouseTracking(True)

        self.play_btn = QPushButton(self)
        self.play_btn.setObjectName("heroPrimary")
        self.play_btn.setFont(ui_font(15, True))
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.info_btn = QPushButton("More Info", self)
        self.info_btn.setObjectName("heroGlass")
        self.info_btn.setFont(ui_font(15, True))
        self.info_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.play_btn.clicked.connect(lambda: self.win.play_next(self.cur_entry()))
        self.info_btn.clicked.connect(lambda: self.win.open_entry(self.cur_entry()))

        self._anim = QPropertyAnimation(self, b"fade", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuart)
        self._kb_anim = QPropertyAnimation(self, b"kb_zoom", self)
        self._kb_anim.setEasingCurve(QEasingCurve.Type.OutSine)

        self.timer = QTimer(self)
        self.timer.setInterval(8000)
        self.timer.timeout.connect(self._auto)
        if len(slides) > 1:
            self.timer.start()

        if slides:
            self._apply_buttons()
            self._start_kb()

    def cur_entry(self):
        return self.slides[self.index]["entry"] if self.slides else None

    def _get_fade(self) -> float:
        return self._fade

    def _set_fade(self, v: float) -> None:
        self._fade = v
        self.update()

    fade = Property(float, _get_fade, _set_fade)

    def _get_kb_zoom(self) -> float:
        return self._kb_zoom

    def _set_kb_zoom(self, v: float) -> None:
        self._kb_zoom = v
        self.update()

    kb_zoom = Property(float, _get_kb_zoom, _set_kb_zoom)

    def _start_kb(self) -> None:
        self._kb_anim.stop()
        if not T.animations:
            self._kb_zoom = 1.0
            return
        self._kb_anim.setDuration(D(8000))
        self._kb_anim.setStartValue(1.06)
        self._kb_anim.setEndValue(1.0)
        self._kb_anim.start()

    def _card(self) -> QRectF:
        """Rect of the floating hero card inside this widget."""
        return QRectF(
            T.MARGIN,
            self.TOP_PAD,
            max(10.0, self.width() - 2 * T.MARGIN),
            max(10.0, self.height() - self.TOP_PAD - self.BOTTOM_PAD),
        )

    def _apply_buttons(self) -> None:
        if not self.slides:
            return
        entry = self.cur_entry()
        self.play_btn.setText("▶   " + self.win.play_label(entry).lstrip("▶ "))
        self._place_buttons()

    def _place_buttons(self) -> None:
        c = self._card()
        by = int(c.bottom() - self.INNER - self.BTN_H)
        x = int(c.left() + self.INNER)
        pw = self.play_btn.sizeHint().width() + 20
        iw = self.info_btn.sizeHint().width() + 20
        self.play_btn.setGeometry(x, by, pw, self.BTN_H)
        self.info_btn.setGeometry(x + pw + 12, by, iw, self.BTN_H)

    def go(self, i: int, user: bool = False) -> None:
        if i == self.index or not self.slides:
            return
        self.prev, self.index = self.index, i % len(self.slides)
        self.win.hero_index = self.index
        self.win.root.set_ambient(self.slides[self.index].get("tint") or T.ACCENT)
        self._apply_buttons()
        self._anim.stop()
        self._anim.setDuration(D(820))
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._start_kb()
        if user:
            self.timer.start()

    def _auto(self) -> None:
        if self.underMouse() or not self.isVisible() or not self.slides:
            return
        self.go((self.index + 1) % len(self.slides))

    def hasHeightForWidth(self) -> bool:
        return False

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        card_w = max(10, self.width() - 2 * T.MARGIN)
        card_h = int(max(460, min(680, card_w * 0.44)))
        h = self.TOP_PAD + card_h + self.BOTTOM_PAD
        if h != self.height():
            self.setFixedHeight(h)
        self._place_buttons()

    def mousePressEvent(self, e) -> None:
        pos = e.position()
        for i, r in enumerate(self._dots):
            if r.adjusted(-6, -10, 6, 10).contains(pos):
                self.go(i, user=True)
                return
        super().mousePressEvent(e)

    def _paint_bg(self, p: QPainter, s: dict, card: QRectF, zoom: float = 1.0) -> None:
        pm = s.get("pm")
        if pm:
            key = (int(card.width()), int(card.height()))
            if s.get("key") != key or s.get("scaled") is None:
                s["scaled"] = pm.scaled(
                    key[0],
                    key[1],
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                s["key"] = key
            sc = s["scaled"]
            p.save()
            if abs(zoom - 1.0) > 0.001:
                c = card.center()
                p.translate(c)
                p.scale(zoom, zoom)
                p.translate(-c)
            p.drawPixmap(
                QPointF(
                    card.left() + (card.width() - sc.width()) / 2,
                    card.top() + (card.height() - sc.height()) / 2,
                ),
                sc,
            )
            p.restore()
        else:
            base = QColor(s["tint"]) if s.get("tint") else tint_for(s["title"])
            g = QLinearGradient(card.topLeft(), card.bottomRight())
            g.setColorAt(0, base.darker(140))
            g.setColorAt(1, QColor(T.BG))
            p.fillRect(card, g)

    def _eyebrow(self, s: dict) -> str:
        f = self.win.fraction(s["entry"])
        if 0 < f < 1:
            return "CONTINUE WATCHING"
        if f >= 1:
            return "WATCH AGAIN"
        return "FEATURED"

    def _paint_text(self, p: QPainter, s: dict, card: QRectF, alpha: float, dx: float) -> None:
        if alpha <= 0.01:
            return
        M = card.left() + self.INNER
        text_w = int(min(card.width() * 0.52, 640))
        p.save()
        p.setOpacity(alpha)
        p.translate(dx, 0)
        by = card.bottom() - self.INNER - self.BTN_H
        dfont = ui_font(15)
        dlines = wrap_lines(s["desc"], ui_fm(15), text_w, 2) if s.get("desc") else []
        d_top = by - 22 - len(dlines) * 22
        chips_top = d_top - 14 - 26
        tpx = int(max(34, min(60, card.width() / 22)))
        tfont = ui_font(tpx, True, display=True)
        tlines = wrap_lines(s["title"], ui_fm(tpx, True, display=True), text_w, 2)
        lh = int(tpx * 1.12)
        y = chips_top - 12 - lh * len(tlines)

        # Eyebrow tag
        p.setFont(ui_font(11, True, tracking=1.6))
        p.setPen(QColor(255, 255, 255, 170))
        p.drawText(
            QRectF(M, y - 24, text_w, 18),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._eyebrow(s),
        )

        p.setFont(tfont)
        for line in tlines:
            rect = QRectF(M, y, text_w + 40, lh)
            p.setPen(QColor(0, 0, 0, 90))
            p.drawText(
                rect.translated(0, 2),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                line,
            )
            p.setPen(QColor("white"))
            p.drawText(
                rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                line,
            )
            y += lh

        # Genre & Score pills
        cf = ui_font(12, True)
        cfm = ui_fm(12, True)
        x = M
        p.setFont(cf)
        for text, hot in s.get("chips", []):
            cw = cfm.horizontalAdvance(text) + 24
            if x + cw > M + text_w + 40:
                break
            rect = QRectF(x, chips_top, cw, 26)
            p.setPen(QPen(QColor(255, 255, 255, 34), 1))
            p.setBrush(QColor(255, 255, 255, 30))
            p.drawRoundedRect(rect, 13, 13)
            p.setPen(QColor(T.GOLD) if hot else QColor(255, 255, 255, 225))
            p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)
            x += cw + 8

        p.setFont(dfont)
        p.setPen(QColor(255, 255, 255, 200))
        yy = d_top
        for line in dlines:
            p.drawText(
                QRectF(M, yy, text_w + 40, 22),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                line,
            )
            yy += 22
        p.restore()

    def _paint_pager(self, p: QPainter, card: QRectF) -> None:
        n = len(self.slides)
        self._dots = []
        if n <= 1:
            return
        gap, dot, active = 8, 8, 30
        inner_w = active + (n - 1) * dot + gap * (n - 1)
        pill = QRectF(
            card.right() - self.INNER - inner_w - 28,
            card.bottom() - self.INNER - self.BTN_H / 2 - 15,
            inner_w + 28,
            30,
        )
        p.setPen(QPen(QColor(255, 255, 255, 36), 1))
        p.setBrush(QColor(20, 22, 30, 140))
        p.drawRoundedRect(pill, 15, 15)
        x = pill.left() + 14
        y = pill.center().y() - dot / 2
        prog = 0.0
        if self.timer.isActive() and self.timer.interval() > 0:
            prog = 1.0 - self.timer.remainingTime() / self.timer.interval()
            prog = max(0.0, min(1.0, prog))
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            w = active if i == self.index else dot
            rect = QRectF(x, y, w, dot)
            p.setBrush(QColor(255, 255, 255, 90))
            p.drawRoundedRect(rect, dot / 2, dot / 2)
            if i == self.index:
                running = self.timer.isActive() and T.animations
                fill = max(dot, w * prog) if running else w
                p.setBrush(QColor("white"))
                p.drawRoundedRect(QRectF(x, y, fill, dot), dot / 2, dot / 2)
            self._dots.append(rect)
            x += w + gap

    def paintEvent(self, _) -> None:
        if not self.slides:
            return
        p = QPainter(self)
        p.setRenderHints(AA)
        card = self._card()
        R = T.R_HERO
        cur = self.slides[self.index]

        # Tinted ambient glow under the floating visionOS card
        tint = QColor(cur.get("tint") or tint_for(cur["title"]).name())
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(1, 15):
            c = QColor(tint)
            c.setAlpha(int(8 * (1 - i / 15)))
            p.setBrush(c)
            p.drawRoundedRect(
                card.adjusted(-i * 2, -i + 6, i * 2, i * 2 + 6), R + i * 2, R + i * 2
            )
        for i in range(1, 8):
            p.setBrush(QColor(0, 0, 0, int(24 * (1 - i / 8))))
            p.drawRoundedRect(card.adjusted(-i, -i + 6, i, i + 6), R + i, R + i)

        clip = QPainterPath()
        clip.addRoundedRect(card, R, R)
        p.save()
        p.setClipPath(clip)
        p.fillRect(card, QColor(T.SURFACE))

        fading = self._fade < 1.0 and self.prev >= 0
        if fading:
            self._paint_bg(p, self.slides[self.prev], card, 1.0)
            p.setOpacity(self._fade)
            self._paint_bg(p, cur, card, self._kb_zoom)
            p.setOpacity(1.0)
        else:
            self._paint_bg(p, cur, card, self._kb_zoom)

        # Scrim gradients
        g = QLinearGradient(card.left(), 0, card.right(), 0)
        g.setColorAt(0.0, QColor(6, 7, 10, 225))
        g.setColorAt(0.45, QColor(6, 7, 10, 120))
        g.setColorAt(0.8, QColor(6, 7, 10, 0))
        p.fillRect(card, g)

        g2 = QLinearGradient(0, card.top(), 0, card.bottom())
        g2.setColorAt(0.45, QColor(6, 7, 10, 0))
        g2.setColorAt(1.0, QColor(6, 7, 10, 200))
        p.fillRect(card, g2)

        # Specular top sheen
        g3 = QLinearGradient(0, card.top(), 0, card.top() + card.height() * 0.35)
        g3.setColorAt(0.0, QColor(255, 255, 255, 18))
        g3.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(card, g3)

        if fading:
            self._paint_text(p, self.slides[self.prev], card, 1 - self._fade, -26 * self._fade)
            self._paint_text(p, cur, card, self._fade, 26 * (1 - self._fade))
        else:
            self._paint_text(p, cur, card, 1.0, 0)

        self._paint_pager(p, card)
        p.restore()

        # Hairline glass specular rim
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 34), 1))
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), R, R)
