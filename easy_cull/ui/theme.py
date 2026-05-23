"""Theme palette, color helpers, and metadata markup for the desktop UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from easy_cull.core.records import PhotoRecord

from PySide6.QtCore import Qt

PHOTO_ID_ROLE = Qt.UserRole
SCENE_COUNT_ROLE = Qt.UserRole + 1
FLAG_ROLE = Qt.UserRole + 2
NO_METADATA_TEXT = 'No rating, color label, or flag'
LOAD_PROGRESS_MAX = 100
LOAD_AND_PREVIEW_PROGRESS_MAX = 200
SPLIT_VIEW_PANE_COUNT = 2
COLOR_LABEL_SWATCHES = {
    'red': '#d94b4b',
    'yellow': '#d7b53d',
    'green': '#3ea765',
    'blue': '#3978d6',
    'purple': '#8d58d5',
}


@dataclass(frozen=True)
class ThemePalette:
    """Color palette for a UI theme."""

    name: str
    strip_background: str
    viewer_background: str
    selected_background: str
    topbar_text_color: str
    button_text_color: str
    button_background: str
    button_border: str
    name_color: str
    meta_color: str
    selected_name_color: str
    selected_meta_color: str
    current_border_color: str
    badge_background: str
    badge_text_color: str


THEMES = {
    'dark': ThemePalette(
        name='dark',
        strip_background='#1a1f27',
        viewer_background='#101317',
        selected_background='#d0d5db',
        topbar_text_color='#e9eef3',
        button_text_color='#e9eef3',
        button_background='#28303a',
        button_border='#39424d',
        name_color='#e9eef3',
        meta_color='#c7d1db',
        selected_name_color='#101317',
        selected_meta_color='#20262d',
        current_border_color='#8f98a2',
        badge_background='rgba(45, 166, 78, 230)',
        badge_text_color='#ffffff',
    ),
    'light': ThemePalette(
        name='light',
        strip_background='#dde2e7',
        viewer_background='#d8dde2',
        selected_background='#5e6670',
        topbar_text_color='#1c232b',
        button_text_color='#1c232b',
        button_background='#eef2f5',
        button_border='#b6bec7',
        name_color='#1c232b',
        meta_color='#4f5a66',
        selected_name_color='#f5f7f9',
        selected_meta_color='#f0f3f6',
        current_border_color='#343b44',
        badge_background='rgba(45, 166, 78, 230)',
        badge_text_color='#ffffff',
    ),
}


def rating_symbols(rating: int | None) -> str:
    """Return the filled and empty star string for a rating value."""
    if rating is None:
        return ''

    return ('★' * rating) + ('☆' * (5 - rating))


def flag_symbol(flag: str | None) -> str:
    """Return the UI symbol used for the current pick/reject flag."""
    if flag == 'picked':
        return '✅'

    if flag == 'rejected':
        return '❌'

    return ''


def color_label_markup(color_label: str | None) -> str:
    """Return the colored label-dot markup for a photo color label."""
    swatch = COLOR_LABEL_SWATCHES.get(color_label or '')
    if swatch is None:
        return ''

    return f'<span style="color: {swatch};">●</span>'


def metadata_markup(photo: PhotoRecord) -> str:
    """Return the combined rich-text metadata badges for a photo."""
    parts: list[str] = []
    rating_text = rating_symbols(photo.rating)
    color_label_text = color_label_markup(photo.color_label)
    flag_text = flag_symbol(photo.flag)
    if rating_text:
        parts.append(rating_text)

    if color_label_text:
        parts.append(color_label_text)

    if flag_text:
        parts.append(flag_text)

    return ' '.join(parts)
