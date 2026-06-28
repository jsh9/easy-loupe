"""
Shared viewer-window shell helpers.

The shell is the shared scaffolding around viewer-style windows: keyboard
shortcuts, progress overlays, transient message overlays, and screen-placement
helpers. Window-specific visual styling stays with the individual windows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QScreen, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

import easy_loupe.ui.progress_overlay as progress_overlay_module

if TYPE_CHECKING:
    from collections.abc import Callable


DEFAULT_EXIF_OVERLAY_MARGIN = 14
VIEWER_KEYBOARD_PAN_STEP = 120
ProgressOverlayController = progress_overlay_module.ProgressOverlayController
ProgressOverlayWidgets = progress_overlay_module.ProgressOverlayWidgets
ProgressStageListWidget = progress_overlay_module.ProgressStageListWidget
ProgressStageRow = progress_overlay_module.ProgressStageRow
build_progress_overlay = progress_overlay_module.build_progress_overlay


@dataclass(frozen=True, slots=True)
class TransientMessageOverlayWidgets:
    """Widget bundle for a centered transient message overlay."""

    overlay: QWidget
    panel: QFrame
    message_label: QLabel
    timer: QTimer


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


def make_lifecycle_shortcut(
        parent: QWidget,
        key: str,
        callback: Callable[[], object],
) -> QShortcut:
    """
    Create an unblocked shortcut for top-level window lifecycle actions.

    Lifecycle shortcuts stay outside busy/help gates so users can close a
    window or consume Ctrl/Cmd+Q even while modal overlays are visible.
    """
    shortcut = QShortcut(QKeySequence(key), parent)
    shortcut.setContext(Qt.WindowShortcut)
    shortcut.activated.connect(callback)
    return shortcut


def ignore_quit_shortcut() -> None:
    """
    Consume Ctrl/Cmd+Q at the window layer.

    The empty body is intentional: the shortcut exists only to stop Qt from
    treating Ctrl/Cmd+Q as close or quit. WindowManager still handles native
    quit events because some platforms bypass QShortcut delivery.
    """


def build_viewer_shortcuts[ShortcutT](
        make_shortcut: Callable[[str | int, Callable[[], None]], ShortcutT],
        *,
        zoom_step: Callable[[float], None],
        keyboard_pan_by: Callable[[int, int], None],
) -> list[ShortcutT]:
    """Create the common viewer zoom and keyboard-pan shortcuts."""
    return [
        make_shortcut('-', lambda: zoom_step(0.8)),
        make_shortcut('=', lambda: zoom_step(1.25)),
        make_shortcut(Qt.Key_Plus, lambda: zoom_step(1.25)),
        make_shortcut('W', lambda: keyboard_pan_by(0, -1)),
        make_shortcut('A', lambda: keyboard_pan_by(-1, 0)),
        make_shortcut('S', lambda: keyboard_pan_by(0, 1)),
        make_shortcut('D', lambda: keyboard_pan_by(1, 0)),
    ]


def confirm_reset_zoom_centers(parent: QWidget) -> bool:
    """Return whether the user confirmed clearing remembered zoom centers."""
    return (
        QMessageBox.question(
            parent,
            'Reset Zoom Centers',
            (
                'Reset all remembered zoom centers to AF points or '
                'image centers?'
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        == QMessageBox.Yes
    )


def build_transient_message_overlay(
        parent: QWidget,
        *,
        timer_parent: QObject | None = None,
) -> TransientMessageOverlayWidgets:
    """Build the common centered transient-message overlay widget bundle."""
    overlay = QWidget(parent)
    overlay.setObjectName('transientMessageOverlay')
    overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    overlay.setFocusPolicy(Qt.NoFocus)
    overlay.hide()
    overlay_layout = QVBoxLayout(overlay)
    overlay_layout.setContentsMargins(0, 0, 0, 0)
    overlay_layout.addStretch(1)
    overlay_center = QHBoxLayout()
    overlay_center.addStretch(1)
    panel = QFrame(overlay)
    panel.setObjectName('transientMessagePanel')
    panel.setFocusPolicy(Qt.NoFocus)
    panel_layout = QVBoxLayout(panel)
    panel_layout.setContentsMargins(22, 16, 22, 16)
    message_label = QLabel('', panel)
    message_label.setAlignment(Qt.AlignCenter)
    message_label.setWordWrap(True)
    message_label.setFocusPolicy(Qt.NoFocus)
    panel_layout.addWidget(message_label)
    overlay_center.addWidget(panel)
    overlay_center.addStretch(1)
    overlay_layout.addLayout(overlay_center)
    overlay_layout.addStretch(1)
    timer = QTimer(timer_parent or parent)
    timer.setSingleShot(True)
    return TransientMessageOverlayWidgets(
        overlay=overlay,
        panel=panel,
        message_label=message_label,
        timer=timer,
    )


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


def resolve_widget_screen(widget: object) -> QScreen | None:
    """Return the screen containing a widget, if Qt can resolve one."""
    window_handle_fn = getattr(widget, 'windowHandle', None)
    window_handle = window_handle_fn() if callable(window_handle_fn) else None
    if window_handle is not None:
        screen_fn = getattr(window_handle, 'screen', None)
        screen = screen_fn() if callable(screen_fn) else None
        if screen is not None:
            return screen

    frame_geometry_fn = getattr(widget, 'frameGeometry', None)
    if not callable(frame_geometry_fn):
        return None

    return QGuiApplication.screenAt(frame_geometry_fn().center())
