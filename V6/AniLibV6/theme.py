"""Design system tokens, typography, glass styling, and global QSS for AniLibV6."""
from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import re
from string import Template
import sys
import urllib.request

from PySide6.QtCore import QEasingCurve
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QPalette,
)

from AniLibV6.config import APP_DIR, FONT_DIR


class T:
    """Design tokens. VisionOS / Apple TV aesthetic."""

    # Colors
    BG = "#07080c"         # Deep OLED space black
    SURFACE = "#11131a"
    SURFACE2 = "#171924"
    SURFACE3 = "#222534"
    BORDER = "#2a2d3d"
    TEXT = "#f5f5f7"
    MUTED = "#8e8e99"
    MUTED_DIM = "#50505a"
    ACCENT = "#e50914"      # Cinematic Crimson
    ACCENT_HI = "#ff3b30"   # Apple Vibrant Red
    GREEN = "#30d158"       # Apple TV Emerald Green
    GOLD = "#ffd60a"        # Apple TV Gold Star

    FONT_LOGO = "Bebas Neue"
    FONT = "Outfit"
    FONT_BODY = "Outfit"
    FONT_MONO = "JetBrains Mono"

    # visionOS-style glass + system colours (RGBA tuples)
    GLASS = (255, 255, 255, 18)     # Translucent fill for glass surfaces
    GLASS_HI = (255, 255, 255, 34)  # Hovered glass
    GLASS_RIM = (255, 255, 255, 42) # Hairline specular rim on glass
    GLASS_SHADOW = (0, 0, 0, 110)
    SYS_GREEN = "#30d158"
    SYS_BLUE = "#0a84ff"

    # Radii
    R_CARD = 18
    R_HERO = 30
    R_SHEET = 28
    R_PILL = 999
    R_THUMB = 12

    # Dimensions
    POSTER_W, POSTER_H, PAD = 166, 244, 14  # PAD = room for tvOS focus lift + glow
    SLOT_W = POSTER_W + 2 * PAD
    SLOT_H = POSTER_H + 2 * PAD
    NAV_H = 72
    MARGIN = 56
    HOVER_SCALE = 0.06  # ~1.06x focus lift

    # Animation timings (ms)
    HOVER_MS = 260
    PAGE_MS = 340
    SCROLL_MS = 380
    animations = True


def D(ms: int) -> int:
    """Return animation duration scaled by the animation setting."""
    return ms if T.animations else 0


@lru_cache(maxsize=256)
def qc(hex_: str, alpha: int = 255) -> QColor:
    """Cached QColor generator with alpha support."""
    c = QColor(hex_)
    c.setAlpha(alpha)
    return c


@lru_cache(maxsize=128)
def ui_font(px: int, bold: bool = False, display: bool = False, tracking: float = 0.0, mono: bool = False, logo: bool = False) -> QFont:
    """Generate crisp, high-legibility UI fonts with fallbacks."""
    f = QFont()
    if logo:
        f.setFamilies([T.FONT_LOGO, T.FONT, "Segoe UI Variable Display", "Segoe UI", "Impact", "Arial"])
        f.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
    elif mono:
        f.setFamilies([T.FONT_MONO, "Cascadia Mono", "Consolas", "monospace"])
        f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    elif display or px >= 20:
        f.setFamilies([T.FONT, "Segoe UI Variable Display", "Segoe UI", "Inter", "Montserrat", "Helvetica Neue", "Arial"])
        f.setWeight(QFont.Weight.ExtraBold if bold else QFont.Weight.DemiBold)
    else:
        f.setFamilies([T.FONT_BODY, "Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", "Arial"])
        f.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
    f.setPixelSize(px)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferQuality)
    if tracking:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, tracking)
    return f


@lru_cache(maxsize=128)
def ui_fm(px: int, bold: bool = False, display: bool = False, tracking: float = 0.0, mono: bool = False, logo: bool = False) -> QFontMetrics:
    """Font metrics cache helper."""
    return QFontMetrics(ui_font(px, bold, display, tracking, mono, logo))


def _runtime_dirs(sub: str) -> list[Path]:
    """Return candidate asset directories."""
    out = [APP_DIR / sub]
    if getattr(sys, "frozen", False):
        out.append(Path(sys.executable).resolve().parent / sub)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            out.append(Path(meipass) / sub)
    else:
        out.append(Path(__file__).resolve().parent / sub)
        out.append(Path(__file__).resolve().parent.parent / sub)
    return [d for i, d in enumerate(out) if d not in out[:i]]


def load_custom_fonts() -> None:
    """Load custom fonts (Outfit, Bebas Neue, JetBrains Mono) with automatic fallback download."""
    try:
        FONT_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    dirs = [d for d in _runtime_dirs("fonts") if d.is_dir()]
    files = [
        p
        for d in dirs
        for p in d.iterdir()
        if p.suffix.lower() in (".ttf", ".otf") and p.stat().st_size > 1000
    ]
    if not files:
        try:
            css_url = (
                "https://fonts.googleapis.com/css2?family=Bebas+Neue&"
                "family=Outfit:wght@400;600;700;800&family=JetBrains+Mono:wght@600&display=swap"
            )
            req = urllib.request.Request(css_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as r:
                css = r.read().decode("utf-8")
            for fam, wt, url in re.findall(
                r"font-family:\s*'([^']+)'.*?font-weight:\s*(\d+).*?src:\s*url\((https://[^)]+\.ttf)\)",
                css,
                re.DOTALL,
            ):
                dest = FONT_DIR / f"{fam.replace(' ', '')}-{wt}.ttf"
                if not dest.exists():
                    with urllib.request.urlopen(
                        urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                        timeout=5,
                    ) as fr:
                        dest.write_bytes(fr.read())
            files = [
                p
                for p in FONT_DIR.iterdir()
                if p.suffix.lower() in (".ttf", ".otf") and p.stat().st_size > 1000
            ]
        except Exception:
            pass
    for p in files:
        try:
            QFontDatabase.addApplicationFont(str(p))
        except Exception:
            pass


QSS = Template("""
QToolTip {
    background: rgba(28, 30, 40, 0.96);
    color: $TEXT;
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 12px;
    padding: 8px 14px;
    font-size: 12px;
}
QLabel {
    background: transparent;
    color: $TEXT;
}
QPushButton {
    background: $SURFACE3;
    color: $TEXT;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 10px 20px;
    font-weight: 600;
}
QPushButton:hover {
    background: #323548;
    border-color: rgba(255, 255, 255, 0.22);
}
QPushButton:pressed {
    background: #1b1d28;
    padding-top: 11px;
}
QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e50914, stop:1 #ff3342);
    color: #ffffff;
    border: none;
    border-radius: 14px;
}
QPushButton#primary:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f6121d, stop:1 #ff4b58);
}
QPushButton#primary:pressed {
    background: #c10711;
}
QPushButton#ghost {
    background: rgba(255, 255, 255, 0.09);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 14px;
    color: #f0f0f5;
}
QPushButton#ghost:hover {
    background: rgba(255, 255, 255, 0.17);
    border-color: rgba(255, 255, 255, 0.28);
    color: #ffffff;
}
QPushButton#ghost:pressed {
    background: rgba(255, 255, 255, 0.06);
}
QPushButton#flat {
    background: transparent;
    border: none;
    padding: 8px 14px;
}
QPushButton#flat:hover {
    background: rgba(255, 255, 255, 0.10);
    border-radius: 10px;
}
QPushButton#navlink {
    background: transparent;
    border: none;
    color: rgba(255, 255, 255, 0.60);
    padding: 8px 18px;
    font-size: 14px;
    font-weight: 600;
    border-radius: 18px;
}
QPushButton#navlink:hover {
    color: white;
}
QPushButton#navlink:checked {
    color: white;
}
QPushButton#heroPrimary {
    background: #ffffff;
    color: #08080d;
    border: none;
    border-radius: 24px;
    padding: 0 28px;
    font-weight: 700;
}
QPushButton#heroPrimary:hover {
    background: #ebebf2;
}
QPushButton#heroPrimary:pressed {
    background: #d4d4dc;
}
QPushButton#heroGlass {
    background: rgba(255, 255, 255, 0.14);
    color: white;
    border: 1px solid rgba(255, 255, 255, 0.22);
    border-radius: 24px;
    padding: 0 24px;
    font-weight: 600;
}
QPushButton#heroGlass:hover {
    background: rgba(255, 255, 255, 0.24);
    border-color: rgba(255, 255, 255, 0.36);
}
QPushButton#heroGlass:pressed {
    background: rgba(255, 255, 255, 0.10);
}
QPushButton#glassPill {
    background: rgba(255, 255, 255, 0.08);
    color: white;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 17px;
    padding: 0 16px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#glassPill:hover {
    background: rgba(255, 255, 255, 0.16);
    border-color: rgba(255, 255, 255, 0.26);
}
QPushButton#glassPill:pressed {
    background: rgba(255, 255, 255, 0.05);
}
QPushButton#glassPill:disabled {
    color: rgba(255, 255, 255, 0.35);
}
QToolButton#glassIcon {
    background: rgba(255, 255, 255, 0.08);
    color: white;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 18px;
    padding: 0;
    font-size: 17px;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
}
QToolButton#glassIcon:hover {
    background: rgba(255, 255, 255, 0.18);
    border-color: rgba(255, 255, 255, 0.28);
}
QPushButton#chip {
    background: rgba(24, 26, 36, 0.82);
    color: #c4c4d6;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 16px;
    padding: 7px 18px;
    font-weight: 600;
}
QPushButton#chip:hover {
    background: rgba(36, 39, 54, 0.95);
    color: white;
    border-color: rgba(255, 255, 255, 0.20);
}
QPushButton#chip:checked {
    background: $ACCENT;
    color: #ffffff;
    border-color: $ACCENT;
}
QPushButton#circle {
    background: rgba(22, 24, 34, 0.92);
    color: white;
    border: 1.5px solid rgba(255, 255, 255, 0.35);
    border-radius: 20px;
    min-width: 40px;
    max-width: 40px;
    min-height: 40px;
    max-height: 40px;
    padding: 0;
    font-size: 15px;
}
QPushButton#circle:hover {
    border-color: white;
    background: rgba(44, 48, 66, 0.96);
}
QPushButton#circle_primary {
    background: $ACCENT;
    color: #ffffff;
    border: none;
    border-radius: 20px;
    min-width: 40px;
    max-width: 40px;
    min-height: 40px;
    max-height: 40px;
    padding: 0;
    font-size: 15px;
}
QPushButton#circle_primary:hover {
    background: #ff2b38;
}
QToolButton {
    background: transparent;
    color: white;
    border: none;
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 18px;
}
QToolButton:hover {
    background: rgba(255, 255, 255, 0.12);
}
QToolButton::menu-indicator {
    image: none;
}
QLineEdit {
    background: rgba(255, 255, 255, 0.07);
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 16px;
    padding: 7px 16px;
    color: white;
    selection-background-color: $ACCENT;
}
QLineEdit:hover {
    background: rgba(255, 255, 255, 0.11);
    border-color: rgba(255, 255, 255, 0.28);
}
QLineEdit:focus {
    background: rgba(12, 14, 22, 0.88);
    border: 1.5px solid $ACCENT;
}
QComboBox {
    background: rgba(24, 26, 36, 0.90);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 12px;
    padding: 8px 16px;
    color: $TEXT;
    min-width: 140px;
    font-weight: 500;
}
QComboBox:hover {
    border-color: rgba(255, 255, 255, 0.25);
    background: $SURFACE3;
}
QComboBox QAbstractItemView {
    background: #191b26;
    color: $TEXT;
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 12px;
    selection-background-color: $ACCENT;
    outline: 0;
    padding: 6px;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 0.18);
    border-radius: 4px;
    min-height: 36px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(255, 255, 255, 0.38);
}
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
}
QScrollBar::handle:horizontal {
    background: rgba(255, 255, 255, 0.18);
    border-radius: 4px;
    min-width: 36px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}
QMenu {
    background: rgba(24, 26, 36, 0.97);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 16px;
    padding: 6px;
    color: $TEXT;
}
QMenu::item {
    padding: 9px 22px;
    border-radius: 10px;
}
QMenu::item:selected {
    background: rgba(255, 255, 255, 0.13);
    color: white;
}
QMenu::separator {
    height: 1px;
    background: rgba(255, 255, 255, 0.08);
    margin: 5px 10px;
}
QDialog {
    background: $SURFACE;
}
QListWidget {
    background: $SURFACE2;
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 12px;
    color: $TEXT;
    outline: 0;
}
QListWidget::item {
    padding: 9px 12px;
    border-radius: 8px;
}
QListWidget::item:selected {
    background: $ACCENT;
    color: white;
}
QStatusBar {
    background: transparent;
    color: $MUTED;
}
QStatusBar::item {
    border: none;
}
""")


def apply_theme(app) -> None:
    """Apply modern Apple TV / visionOS theme palette and global QSS to QApplication."""
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(T.BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(T.TEXT))
    pal.setColor(QPalette.ColorRole.Base, QColor(T.SURFACE2))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(T.SURFACE))
    pal.setColor(QPalette.ColorRole.Text, QColor(T.TEXT))
    pal.setColor(QPalette.ColorRole.Button, QColor(T.SURFACE3))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(T.TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(T.ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8a8a9a"))
    app.setPalette(pal)
    app.setFont(ui_font(13))
    app.setStyleSheet(QSS.substitute({k: v for k, v in vars(T).items() if k.isupper()}))
