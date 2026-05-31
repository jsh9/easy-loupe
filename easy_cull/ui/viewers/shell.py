"""Shared shell helpers for EasyCull viewer windows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QWidget

DEFAULT_EXIF_OVERLAY_MARGIN = 14


def make_window_shortcut(
        parent: QWidget,
        key: str | int,
        callback: Callable[[], None],
        *,
        blocked: Callable[[], bool],
) -> QShortcut:
    """Create a window-scoped shortcut guarded by a caller-owned busy state."""
    shortcut = QShortcut(QKeySequence(key), parent)
    shortcut.setContext(Qt.WindowShortcut)
    shortcut.activated.connect(lambda: None if blocked() else callback())
    return shortcut


def exif_overlay_geometry_ready(
        parent: QWidget,
        overlay: QWidget,
        *,
        margin: int = DEFAULT_EXIF_OVERLAY_MARGIN,
) -> bool:
    """Return whether a parent can fit the EXIF overlay with margins."""
    parent_rect = parent.rect()
    return parent_rect.width() >= overlay.width() + (
        margin * 2
    ) and parent_rect.height() >= overlay.minimumHeight() + (margin * 2)


def update_exif_overlay_geometry(
        parent: QWidget,
        overlay: QWidget,
        *,
        margin: int = DEFAULT_EXIF_OVERLAY_MARGIN,
) -> None:
    """Anchor an EXIF overlay at the top right of a viewer parent."""
    parent_rect = parent.rect()
    size_hint = overlay.sizeHint()
    width = overlay.width()
    minimum_height = overlay.minimumSizeHint().height()
    height = min(
        max(size_hint.height(), minimum_height),
        max(parent_rect.height() - (margin * 2), 0),
    )
    if height < minimum_height:
        return

    x = max(margin, parent_rect.width() - width - margin)
    overlay.setGeometry(x, margin, width, height)
