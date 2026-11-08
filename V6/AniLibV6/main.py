"""Main entry point for AniLibV6 application."""
from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication

from AniLibV6.theme import apply_theme, load_custom_fonts
from AniLibV6.ui.window import MainWindow, app_icon, apply_windows_icon, build_ico_bytes
from AniLibV6.ui.common import draw_app_icon


def export_icon(folder: Path | str) -> tuple[Path, Path]:
    """Write anime_library.ico and anime_library.png."""
    f = Path(folder)
    ico_path = f / "anime_library.ico"
    png_path = f / "anime_library.png"
    ico_path.write_bytes(build_ico_bytes())
    draw_app_icon(512).save(str(png_path), "PNG")
    return ico_path, png_path


def main() -> None:
    """Launch AniLibV6 with visionOS theme, fonts, and maximized window."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "AniLibV6.Player.visionOS"
            )
        except Exception:
            pass

    if "--build-update" in sys.argv:
        from AniLibV6.updater import build_release_bundle
        zp, mp = build_release_bundle()
        print(f"Built OTA update bundle ({zp.stat().st_size / 1024:.1f} KB):\n  {zp}\n  {mp}")
        return

    app = QApplication(sys.argv)
    load_custom_fonts()
    apply_theme(app)
    app.setWindowIcon(app_icon())

    if "--export-icon" in sys.argv:
        ico, png = export_icon(Path(__file__).resolve().parent.parent)
        print(f"Wrote {ico}\nWrote {png}")
        return

    win = MainWindow()
    win.setWindowIcon(app_icon())
    win.showMaximized()
    apply_windows_icon(win)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
