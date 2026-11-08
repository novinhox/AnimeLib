"""Cinematic startup splash screen: folded ribbon assembly -> zoom -> prismatic spectrum burst."""
from __future__ import annotations

import math
import os
from pathlib import Path
import random
import sys

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QWidget,
)

try:
    from PySide6.QtMultimedia import (
        QAudioOutput,
        QMediaPlayer,
    )
    HAVE_MM = True
except Exception:
    HAVE_MM = False

from AniLibV6.config import SOUND_DIR
from AniLibV6.theme import T, _runtime_dirs, ui_font
from AniLibV6.ui.common import AA


def ensure_intro_sound() -> Path | None:
    """Return path to custom intro sound or auto-synthesize signature 'Ta-dum' stereo WAV."""
    try:
        SOUND_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    for d in [d for d in reversed(_runtime_dirs("sounds")) if d.is_dir()]:
        for ext in (".wav", ".mp3", ".ogg", ".flac", ".m4a"):
            for name in ("intro", "tadum", "intro_tadum"):
                cand = d / f"{name}{ext}"
                if cand.is_file() and cand.stat().st_size > 1000:
                    return cand
        for p in sorted(d.iterdir()):
            if p.suffix.lower() in (".wav", ".mp3", ".ogg", ".flac", ".m4a") and p.stat().st_size > 1000:
                return p

    out = SOUND_DIR / "intro_tadum.wav"
    try:
        from array import array
        import wave

        sr = 44100
        dur = 2.65
        n = int(sr * dur)
        buf = array("h", [0] * (n * 2))
        two_pi = 2.0 * math.pi
        sin, exp, tanh = math.sin, math.exp, math.tanh
        rng = 1337

        for i in range(n):
            t = i / sr
            L = R = 0.0
            if 0.04 <= t < 0.79:
                dt1 = t - 0.04
                ph1 = two_pi * (44.0 * dt1 + (91.0 / 26.0) * (1.0 - exp(-26.0 * dt1)))
                env1 = exp(-10.5 * dt1) * (1.0 - exp(-220.0 * dt1))
                clk1 = exp(-95.0 * dt1) * sin(two_pi * 320.0 * dt1) * 0.35
                th1 = (sin(ph1) + 0.35 * sin(2.0 * ph1) + clk1) * env1 * 0.78
                L += th1
                R += th1
            if t >= 0.25:
                dt2 = t - 0.25
                if dt2 < 2.2:
                    ph2 = two_pi * (36.71 * dt2 + (81.0 / 22.0) * (1.0 - exp(-22.0 * dt2)))
                    env2 = exp(-3.4 * dt2) * (1.0 - exp(-180.0 * dt2))
                    clk2 = exp(-75.0 * dt2) * sin(two_pi * 240.0 * dt2) * 0.42
                    sub2 = (
                        sin(ph2) + 0.45 * sin(2.0 * ph2) + 0.18 * sin(3.0 * ph2) + clk2
                    ) * env2 * 0.92
                    L += sub2 * 1.02
                    R += sub2 * 0.98
                c_env = (
                    (1.0 - exp(-14.0 * dt2)) * exp(-1.35 * dt2)
                    + 0.32 * exp(-(((t - 1.18) / 0.38) ** 2))
                ) * 0.22
                cL = (
                    0.40 * sin(two_pi * 73.42 * dt2)
                    + 0.34 * sin(two_pi * 110.0 * dt2 + 0.2)
                    + 0.32 * sin(two_pi * 146.83 * dt2 * 1.0015)
                    + 0.24 * sin(two_pi * 185.0 * dt2 * 0.999)
                    + 0.26 * sin(two_pi * 220.0 * dt2 * 1.002)
                    + 0.18 * sin(two_pi * 329.63 * dt2 * 0.9985)
                    + 0.14 * sin(two_pi * 440.0 * dt2 * 1.003)
                    + 0.11 * sin(two_pi * 587.33 * dt2 * 0.998)
                )
                cR = (
                    0.40 * sin(two_pi * 73.42 * dt2)
                    + 0.34 * sin(two_pi * 110.0 * dt2 - 0.2)
                    + 0.32 * sin(two_pi * 146.83 * dt2 * 0.9985)
                    + 0.24 * sin(two_pi * 185.0 * dt2 * 1.001)
                    + 0.26 * sin(two_pi * 220.0 * dt2 * 0.998)
                    + 0.18 * sin(two_pi * 329.63 * dt2 * 1.0015)
                    + 0.14 * sin(two_pi * 440.0 * dt2 * 0.997)
                    + 0.11 * sin(two_pi * 587.33 * dt2 * 1.002)
                )
                L += tanh(cL * 1.35) * c_env
                R += tanh(cR * 1.35) * c_env
            if 0.85 <= t <= 2.25:
                w_env = exp(-(((t - 1.25) / 0.32) ** 2)) * 0.14
                rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
                nz = (rng / 1073741824.0) - 1.0
                L += (nz * 0.35 + 0.65 * sin(two_pi * (880.0 + 220.0 * (t - 0.85)) * t)) * w_env
                R += (-nz * 0.35 + 0.65 * sin(two_pi * (883.0 + 220.0 * (t - 0.85)) * t)) * w_env
            if t > 2.15:
                fade = max(0.0, 1.0 - (t - 2.15) / 0.50) ** 2
                L *= fade
                R *= fade
            idx = i * 2
            buf[idx] = int(max(-32767.0, min(32767.0, tanh(L * 0.95) * 31500.0)))
            buf[idx + 1] = int(max(-32767.0, min(32767.0, tanh(R * 0.95) * 31500.0)))

        with wave.open(str(out), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(buf.tobytes())
        return out
    except Exception:
        return None


class NetflixIntro(QWidget):
    """Cinematic startup splash: ribbon assembly -> zoom -> prismatic spectrum burst."""

    finished = Signal()

    SPECTRUM_HEX = (
        "#e50914", "#ff1744", "#ff5252", "#ff6e40", "#ff9100", "#ffc400",
        "#ffea00", "#c6ff00", "#76ff03", "#00e676", "#1de9b6", "#00e5ff",
        "#00b0ff", "#2979ff", "#3d5afe", "#651fff", "#aa00ff", "#d500f9",
        "#f50057", "#e50914", "#ff3d00", "#ffab00", "#00c853", "#00b8d4",
        "#2962ff", "#6200ea", "#c51162", "#d50000", "#ff1744", "#00e5ff",
        "#ffea00", "#d500f9",
    )

    def __init__(self, parent: QWidget, win=None) -> None:
        super().__init__(parent)
        self.win = win
        self._t = 0.0
        self._snd_player = None
        self._snd_audio = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self._anim = QPropertyAnimation(self, b"t", self)
        self._anim.setDuration(2450)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._anim.finished.connect(self._done)

        rng = random.Random(42)
        self._rays: list[tuple[float, float, QColor, float, float]] = []
        n_rays = 68
        for i in range(n_rays):
            u = (i / (n_rays - 1)) * 2.0 - 1.0
            pos = math.copysign(abs(u) ** 1.18, u) + rng.uniform(-0.025, 0.025)
            w = rng.uniform(0.008, 0.038) * (1.35 - 0.6 * abs(pos))
            col = QColor(self.SPECTRUM_HEX[i % len(self.SPECTRUM_HEX)])
            spd = rng.uniform(0.85, 1.35)
            pk = rng.uniform(0.55, 1.0)
            self._rays.append((pos, w, col, spd, pk))

    def _get_t(self) -> float:
        return self._t

    def _set_t(self, v: float) -> None:
        self._t = v
        self.update()

    t = Property(float, _get_t, _set_t)

    def _play_sound(self) -> None:
        if os.environ.get("ANIME_LIBRARY_NO_AUDIO"):
            return
        if self.win and not self.win.cfg["ui"].get("intro_sound", True):
            return
        snd = ensure_intro_sound()
        if not snd or not snd.exists():
            return
        if HAVE_MM:
            try:
                self._snd_player = QMediaPlayer(self)
                self._snd_audio = QAudioOutput(self)
                vol = (self.win.cfg["ui"].get("volume", 80) / 100.0) if self.win else 0.85
                self._snd_audio.setVolume(min(1.0, max(0.15, vol)))
                self._snd_player.setAudioOutput(self._snd_audio)
                self._snd_player.setSource(QUrl.fromLocalFile(str(snd)))
                self._snd_player.play()
                return
            except Exception:
                pass
        if sys.platform.startswith("win") and snd.suffix.lower() == ".wav":
            try:
                import winsound
                winsound.PlaySound(
                    str(snd), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
                )
            except Exception:
                pass

    def _stop_sound(self) -> None:
        if self._snd_player is not None:
            try:
                self._snd_player.stop()
            except Exception:
                pass
            self._snd_player = None
            self._snd_audio = None
        elif sys.platform.startswith("win"):
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass

    def start(self) -> None:
        if not T.animations:
            self._done()
            return
        p = self.parentWidget()
        if p is not None:
            self.setGeometry(0, 0, p.width(), p.height())
        self.show()
        self.raise_()
        self._play_sound()
        self._anim.start()

    def mousePressEvent(self, e) -> None:
        self._skip()

    def keyPressEvent(self, e) -> None:
        self._skip()

    def _skip(self) -> None:
        if self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()
        self._stop_sound()
        self._done()

    def _done(self) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.hide()
        if self.win and getattr(self.win, "intro", None) is self:
            self.win.intro = None
        pw = self.parentWidget()
        if pw and getattr(pw, "intro", None) is self:
            pw.intro = None
        self.finished.emit()
        self.deleteLater()

    @staticmethod
    def _smoothstep(a: float, b: float, x: float) -> float:
        if x <= a:
            return 0.0
        if x >= b:
            return 1.0
        u = (x - a) / (b - a)
        return u * u * (3.0 - 2.0 * u)

    @staticmethod
    def _ease_out_cubic(u: float) -> float:
        u = max(0.0, min(1.0, u))
        return 1.0 - (1.0 - u) ** 3

    @staticmethod
    def _ease_in_expo(u: float) -> float:
        u = max(0.0, min(1.0, u))
        return 0.0 if u == 0.0 else math.pow(2.0, 10.0 * (u - 1.0))

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(AA)
        W, H = float(self.width()), float(self.height())
        if W <= 0 or H <= 0:
            return
        t = self._t

        bg_fade = 1.0 - self._smoothstep(0.76, 1.0, t)
        if bg_fade <= 0.002:
            return

        p.fillRect(self.rect(), QColor(6, 6, 9, int(255 * bg_fade)))
        cx, cy = W * 0.5, H * 0.5

        glow_env = self._smoothstep(0.04, 0.36, t) * (1.0 - self._smoothstep(0.58, 0.82, t))
        if glow_env > 0.01:
            rad = min(W, H) * (0.38 + 0.25 * self._smoothstep(0.30, 0.65, t))
            rg = QRadialGradient(QPointF(cx, cy), rad)
            rg.setColorAt(0.0, QColor(229, 9, 20, int(95 * glow_env * bg_fade)))
            rg.setColorAt(0.45, QColor(140, 6, 18, int(38 * glow_env * bg_fade)))
            rg.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.fillRect(self.rect(), rg)

        zoom_u = (t - 0.44) / 0.24 if t > 0.44 else 0.0
        zoom_e = self._ease_in_expo(zoom_u)
        scale = (0.86 + 0.16 * self._ease_out_cubic(t / 0.40)) * (1.0 + zoom_e * 22.0)
        emblem_alpha = (1.0 - self._smoothstep(0.54, 0.67, t)) * bg_fade

        if emblem_alpha > 0.01:
            p.save()
            p.setOpacity(emblem_alpha)
            p.translate(cx, cy - H * 0.02 * (1.0 - min(1.0, zoom_u)))
            p.scale(scale, scale)

            eh = min(W, H) * 0.21
            ew = eh * 0.66
            sw = ew * 0.27
            top_y, bot_y = -eh * 0.5, eh * 0.5
            lx, rx = -ew * 0.5, ew * 0.5

            p1 = self._ease_out_cubic((t - 0.02) / 0.16)
            p2 = self._ease_out_cubic((t - 0.12) / 0.16)
            p3 = self._ease_out_cubic((t - 0.20) / 0.18)

            p.setPen(Qt.PenStyle.NoPen)

            if p1 > 0.005:
                h1 = (bot_y - top_y) * p1
                r1 = QRectF(lx, bot_y - h1, sw, h1)
                g1 = QLinearGradient(lx, top_y, lx, bot_y)
                g1.setColorAt(0.0, QColor("#b80610"))
                g1.setColorAt(1.0, QColor("#7a0309"))
                p.setBrush(g1)
                p.drawRoundedRect(r1, 3.0, 3.0)

            if p2 > 0.005:
                h2 = (bot_y - top_y) * p2
                r2 = QRectF(rx - sw, top_y, sw, h2)
                g2 = QLinearGradient(rx, top_y, rx, bot_y)
                g2.setColorAt(0.0, QColor("#7a0309"))
                g2.setColorAt(1.0, QColor("#b80610"))
                p.setBrush(g2)
                p.drawRoundedRect(r2, 3.0, 3.0)

            if p3 > 0.005:
                tl_a = QPointF(lx, top_y)
                tl_b = QPointF(lx + sw, top_y)
                br_b = QPointF(rx, bot_y)
                br_a = QPointF(rx - sw, bot_y)
                cur_b = tl_b + (br_b - tl_b) * p3
                cur_a = tl_a + (br_a - tl_a) * p3

                sh_path = QPainterPath()
                sh_path.moveTo(tl_a + QPointF(0, 4))
                sh_path.lineTo(tl_b + QPointF(4, 4))
                sh_path.lineTo(cur_b + QPointF(4, 4))
                sh_path.lineTo(cur_a + QPointF(0, 4))
                sh_path.closeSubpath()
                p.setBrush(QColor(0, 0, 0, 130))
                p.drawPath(sh_path)

                diag = QPainterPath()
                diag.moveTo(tl_a)
                diag.lineTo(tl_b)
                diag.lineTo(cur_b)
                diag.lineTo(cur_a)
                diag.closeSubpath()
                g3 = QLinearGradient(tl_a, br_b)
                g3.setColorAt(0.0, QColor("#ff1f2d"))
                g3.setColorAt(0.5, QColor("#e50914"))
                g3.setColorAt(1.0, QColor("#c10711"))
                p.setBrush(g3)
                p.drawPath(diag)

            txt_env = self._smoothstep(0.24, 0.40, t) * (1.0 - self._smoothstep(0.45, 0.56, t))
            if txt_env > 0.01:
                p.setOpacity(emblem_alpha * txt_env)
                f = ui_font(int(max(22, eh * 0.21)), False, logo=True, tracking=7.5)
                p.setFont(f)
                p.setPen(QColor(255, 255, 255, 230))
                p.drawText(
                    QRectF(-ew * 1.8, bot_y + eh * 0.16, ew * 3.6, eh * 0.35),
                    int(Qt.AlignmentFlag.AlignCenter),
                    "ANIME",
                )
            p.restore()

        spec_in = self._smoothstep(0.45, 0.56, t)
        spec_out = 1.0 - self._smoothstep(0.68, 0.90, t)
        spec_env = spec_in * spec_out * bg_fade
        if spec_env > 0.005:
            p.save()
            burst_p = max(0.0, (t - 0.45) / 0.43)
            spread = 0.18 + 1.45 * self._ease_out_cubic(burst_p)
            p.setPen(Qt.PenStyle.NoPen)
            for pos, wf, col, spd, pk in self._rays:
                rx = cx + pos * (W * 0.55) * spread * spd
                rw = max(2.0, wf * W * (0.65 + 0.9 * burst_p))
                if rx + rw < 0 or rx - rw > W:
                    continue
                ray_a = int(215 * spec_env * pk * max(0.0, 1.0 - 0.35 * abs(pos)))
                if ray_a <= 2:
                    continue
                vg = QLinearGradient(rx, 0, rx + rw, 0)
                c0 = QColor(col)
                c0.setAlpha(0)
                c1 = QColor(col)
                c1.setAlpha(ray_a)
                c_core = QColor(col).lighter(145)
                c_core.setAlpha(min(255, int(ray_a * 1.15)))
                vg.setColorAt(0.0, c0)
                vg.setColorAt(0.3, c1)
                vg.setColorAt(0.5, c_core)
                vg.setColorAt(0.7, c1)
                vg.setColorAt(1.0, c0)
                p.fillRect(QRectF(rx - rw * 0.5, 0, rw, H), vg)

            for top_v in (True, False):
                vy = 0.0 if top_v else H * 0.72
                vg2 = QLinearGradient(0, vy, 0, vy + H * 0.28)
                vg2.setColorAt(0.0 if top_v else 1.0, QColor(6, 6, 9, int(220 * spec_env)))
                vg2.setColorAt(1.0 if top_v else 0.0, QColor(6, 6, 9, 0))
                p.fillRect(QRectF(0, vy, W, H * 0.28), vg2)
            p.restore()
