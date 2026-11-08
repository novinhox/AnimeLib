"""visionOS / Apple TV interactive components: AppleSwitch, SearchEdit, SegmentedTabs, NavBar, MiniBar."""
from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QWidget,
)

from AniLibV6.theme import D, T, ui_font
from AniLibV6.ui.common import AA, draw_app_icon


class AppleSwitch(QAbstractButton):
    """Smooth iOS / visionOS-style animated pill toggle."""

    def __init__(self, parent: QWidget | None = None, checked: bool = False) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(48, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._thumb_pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"thumb_pos", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setDuration(D(220))
        self.toggled.connect(self._on_toggled)

    def sizeHint(self) -> QSize:
        return QSize(48, 28)

    def _get_thumb_pos(self) -> float:
        return self._thumb_pos

    def _set_thumb_pos(self, v: float) -> None:
        self._thumb_pos = v
        self.update()

    thumb_pos = Property(float, _get_thumb_pos, _set_thumb_pos)

    def _on_toggled(self, checked: bool) -> None:
        if not T.animations:
            self._thumb_pos = 1.0 if checked else 0.0
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._thumb_pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        k = max(0.0, min(1.0, self._thumb_pos))

        bg = QColor(
            int(255 * (1 - k) + 48 * k),
            int(255 * (1 - k) + 209 * k),
            int(255 * (1 - k) + 88 * k),
            int(45 * (1 - k) + 235 * k),
        )
        p.setPen(QPen(QColor(255, 255, 255, int(22 + 25 * k)), 1))
        p.setBrush(bg)
        rad = r.height() / 2.0
        p.drawRoundedRect(r, rad, rad)

        diam = r.height() - 6.0
        tx = r.left() + 3.0 + k * (r.width() - 6.0 - diam)
        ty = r.top() + 3.0
        t_rect = QRectF(tx, ty, diam, diam)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, int(45 * (1.0 - 0.2 * k))))
        p.drawEllipse(t_rect.translated(0, 1.5))

        p.setBrush(QColor("white"))
        p.drawEllipse(t_rect)


class SearchEdit(QLineEdit):
    """visionOS glass capsule search box that smoothly widens on focus."""

    W_IDLE, W_FOCUS = 210, 340

    def __init__(self) -> None:
        super().__init__()
        self.setPlaceholderText("Search   /")
        self.setFixedWidth(self.W_IDLE)
        self.setFixedHeight(36)
        self.setClearButtonEnabled(True)
        self.setStyleSheet(
            "QLineEdit { background: rgba(255, 255, 255, 0.09); border: 1px solid rgba(255, 255, 255, 0.12);"
            " border-radius: 18px; padding: 0 16px; color: white; font-size: 13px; }"
            "QLineEdit:hover { background: rgba(255, 255, 255, 0.14); border-color: rgba(255, 255, 255, 0.22); }"
            "QLineEdit:focus { background: rgba(20, 22, 32, 0.94); border: 1.5px solid rgba(255, 255, 255, 0.45); }"
        )
        self._anim = QPropertyAnimation(self, b"fw", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_fw(self) -> int:
        return self.width()

    def _set_fw(self, v: int) -> None:
        self.setFixedWidth(int(v))

    fw = Property(int, _get_fw, _set_fw)

    def _to(self, w: int) -> None:
        self._anim.stop()
        self._anim.setDuration(D(240))
        self._anim.setStartValue(self.width())
        self._anim.setEndValue(w)
        self._anim.start()

    def focusInEvent(self, e) -> None:
        self._to(self.W_FOCUS)
        super().focusInEvent(e)

    def focusOutEvent(self, e) -> None:
        if not self.text():
            self._to(self.W_IDLE)
        super().focusOutEvent(e)


class SegmentedTabs(QWidget):
    """visionOS-style glass capsule holding the page tabs with a sliding selection pill."""

    def __init__(self, buttons: list[QPushButton]) -> None:
        super().__init__()
        self.buttons = buttons
        self._t = 1.0
        self._from: QRectF | None = None
        self._last: QRectF | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        for b in buttons:
            b.setFixedHeight(34)
            lay.addWidget(b)
        self._anim = QPropertyAnimation(self, b"t", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_t(self) -> float:
        return self._t

    def _set_t(self, v: float) -> None:
        self._t = v
        self.update()

    t = Property(float, _get_t, _set_t)

    def _target(self) -> QRectF | None:
        for b in self.buttons:
            if b.isChecked() and b.width() > 0:
                return QRectF(b.geometry())
        return None

    def selection_changed(self) -> None:
        if self._target() is None or self._last is None or not T.animations:
            self._t = 1.0
            self._from = None
            self._last = self._target()
            self.update()
            return
        self._from = QRectF(self._last)
        self._anim.stop()
        self._anim.setDuration(D(300))
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(QColor(255, 255, 255, 16))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        tgt = self._target()
        if tgt is None:
            self._last = None
            return
        if self._from is not None and self._t < 1.0:
            k = self._t
            cur = QRectF(
                self._from.x() + (tgt.x() - self._from.x()) * k,
                self._from.y() + (tgt.y() - self._from.y()) * k,
                self._from.width() + (tgt.width() - self._from.width()) * k,
                self._from.height() + (tgt.height() - self._from.height()) * k,
            )
        else:
            cur = tgt
        self._last = QRectF(cur)
        p.setPen(QPen(QColor(255, 255, 255, 42), 1))
        p.setBrush(QColor(255, 255, 255, 38))
        p.drawRoundedRect(cur, cur.height() / 2, cur.height() / 2)


class NavBar(QWidget):
    """Floating visionOS glass navigation bar that dynamically frosts on scroll."""

    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self._solid = 0.0
        self._target = 0.0
        self.setFixedHeight(T.NAV_H)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(T.MARGIN, 0, T.MARGIN, 0)
        lay.setSpacing(8)

        mark = QLabel()
        mark.setFixedSize(30, 30)
        mark.setPixmap(
            draw_app_icon(60).scaled(
                30, 30, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        )
        lay.addWidget(mark)

        logo = QLabel("Anime")
        logo.setFont(ui_font(21, True, display=True, tracking=0.2))
        logo.setStyleSheet("color: white;")
        lay.addWidget(logo)
        lay.addSpacing(26)

        self.btn_home = QPushButton("Home")
        self.btn_browse = QPushButton("Browse")
        self.btn_mylist = QPushButton("My List")
        for b in (self.btn_home, self.btn_browse, self.btn_mylist):
            b.setObjectName("navlink")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)

        self.tabs = SegmentedTabs([self.btn_home, self.btn_browse, self.btn_mylist])
        lay.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignVCenter)
        self.btn_home.clicked.connect(win.show_home)
        self.btn_browse.clicked.connect(lambda: win.show_browse(fav_only=False))
        self.btn_mylist.clicked.connect(lambda: win.show_browse(fav_only=True))

        lay.addStretch(1)

        self.btn_update = QPushButton("↻  Restart to Update")
        self.btn_update.setObjectName("navUpdate")
        self.btn_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_update.setFixedHeight(36)
        self.btn_update.setStyleSheet(
            "QPushButton#navUpdate {"
            "  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(48, 209, 88, 0.92), stop:1 rgba(40, 180, 75, 0.92));"
            "  color: #061109;"
            "  border: 1px solid rgba(255, 255, 255, 0.35);"
            "  border-radius: 18px;"
            "  padding: 0 16px;"
            "  font-weight: 800;"
            "  font-size: 13px;"
            "}"
            "QPushButton#navUpdate:hover {"
            "  background: #3ce368;"
            "}"
        )
        self.btn_update.clicked.connect(win.restart_app)
        self.btn_update.hide()
        lay.addWidget(self.btn_update)

        self.btn_resume = QPushButton("▶  Resume")
        self.btn_resume.setObjectName("navResume")
        self.btn_resume.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_resume.setFixedHeight(36)
        self.btn_resume.setStyleSheet(
            "QPushButton#navResume {"
            "  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(229, 9, 20, 0.90), stop:1 rgba(255, 59, 48, 0.90));"
            "  color: white;"
            "  border: 1px solid rgba(255, 255, 255, 0.25);"
            "  border-radius: 18px;"
            "  padding: 0 16px;"
            "  font-weight: 700;"
            "  font-size: 13px;"
            "}"
            "QPushButton#navResume:hover {"
            "  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f6121d, stop:1 #ff4b58);"
            "  border-color: rgba(255, 255, 255, 0.40);"
            "}"
            "QPushButton#navResume:pressed {"
            "  background: #c10711;"
            "}"
        )
        self.btn_resume.clicked.connect(win.resume_last_watched)
        self.btn_resume.hide()
        lay.addWidget(self.btn_resume)

        self.btn_random = QPushButton("Surprise Me")
        self.btn_random.setObjectName("glassPill")
        self.btn_random.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_random.setFixedHeight(36)
        self.btn_random.setToolTip("Pick a random anime from your library (R)")
        self.btn_random.clicked.connect(win.pick_random)
        lay.addWidget(self.btn_random)

        self.search = SearchEdit()
        lay.addWidget(self.search)

        self.gear = QToolButton()
        self.gear.setObjectName("glassIcon")
        self.gear.setText("⚙")
        self.gear.setToolTip("Settings  (Ctrl+,)")
        self.gear.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self.gear)

        self._anim = QPropertyAnimation(self, b"solid", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_solid(self) -> float:
        return self._solid

    def _set_solid(self, v: float) -> None:
        self._solid = v
        self.update()

    solid = Property(float, _get_solid, _set_solid)

    def set_scrolled(self, on: bool) -> None:
        target = 1.0 if on else 0.0
        if target == self._target:
            return
        self._target = target
        self._anim.stop()
        self._anim.setDuration(D(240))
        self._anim.setStartValue(self._solid)
        self._anim.setEndValue(target)
        self._anim.start()

    def set_page(self, page: int, fav_only: bool = False) -> None:
        self.btn_home.setChecked(page == 0)
        self.btn_browse.setChecked(page == 1 and not fav_only)
        self.btn_mylist.setChecked(page == 1 and fav_only)
        self.tabs.selection_changed()
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        r = self.rect()
        # Frosted glass background once scrolled
        p.fillRect(r, QColor(14, 16, 24, int(222 * self._solid)))
        g = QLinearGradient(0, 0, 0, r.height())
        g.setColorAt(0, QColor(7, 8, 12, int(170 * (1 - self._solid))))
        g.setColorAt(1, QColor(7, 8, 12, 0))
        p.fillRect(r, g)
        p.fillRect(
            QRectF(0, r.height() - 1, r.width(), 1),
            QColor(255, 255, 255, int(22 * self._solid)),
        )


class MiniBar(QWidget):
    """Compact progress bar capsule."""

    def __init__(self) -> None:
        super().__init__()
        self.frac = 0.0
        self.setFixedHeight(5)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 36))
        p.drawRoundedRect(self.rect(), 2.5, 2.5)
        if self.frac > 0:
            p.setBrush(QColor(T.ACCENT))
            p.drawRoundedRect(QRectF(0, 0, self.width() * self.frac, self.height()), 2.5, 2.5)
