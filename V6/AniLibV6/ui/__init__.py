"""AniLibV6 UI package."""
from AniLibV6.ui.cards import EpisodeCard, PosterCard, PreviewCard
from AniLibV6.ui.common import (
    AA,
    CardGrid,
    FadeStack,
    HScroll,
    Row,
    RowHeader,
    SmoothScrollArea,
    Toast,
    bake_poster,
    draw_app_icon,
    load_pixmap,
)
from AniLibV6.ui.components import AppleSwitch, NavBar, SearchEdit, SegmentedTabs
from AniLibV6.ui.dialogs import MatchDialog, SettingsDialog
from AniLibV6.ui.hero import BannerWidget, HeroBanner
from AniLibV6.ui.intro import NetflixIntro
from AniLibV6.ui.player import PlayerPage
from AniLibV6.ui.window import MainWindow, Root, app_icon, apply_windows_icon

__all__ = [
    "AA",
    "AppleSwitch",
    "BannerWidget",
    "CardGrid",
    "EpisodeCard",
    "FadeStack",
    "HScroll",
    "HeroBanner",
    "MainWindow",
    "MatchDialog",
    "NavBar",
    "NetflixIntro",
    "PlayerPage",
    "PosterCard",
    "PreviewCard",
    "Root",
    "Row",
    "RowHeader",
    "SearchEdit",
    "SegmentedTabs",
    "SettingsDialog",
    "SmoothScrollArea",
    "Toast",
    "app_icon",
    "apply_windows_icon",
    "bake_poster",
    "draw_app_icon",
    "load_pixmap",
]
