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
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from easy_loupe.progress import ProgressSnapshot, ProgressStageSnapshot

DEFAULT_EXIF_OVERLAY_MARGIN = 14
VIEWER_KEYBOARD_PAN_STEP = 120


@dataclass(frozen=True, slots=True)
class ProgressOverlayWidgets:
    """Widget bundle for a centered progress overlay."""

    overlay: QWidget
    panel: QFrame
    message_label: QLabel
    progress_bar: QProgressBar
    stage_list: ProgressStageListWidget


@dataclass(frozen=True, slots=True)
class TransientMessageOverlayWidgets:
    """Widget bundle for a centered transient message overlay."""

    overlay: QWidget
    panel: QFrame
    message_label: QLabel
    timer: QTimer


class ProgressStageRow(QWidget):
    """Single progress row showing one stage label, count, and bar."""

    def __init__(
            self,
            stage: ProgressStageSnapshot,
            parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName('progressStageRow')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        text_row = QHBoxLayout()
        text_row.setContentsMargins(0, 0, 0, 0)
        text_row.setSpacing(12)
        self.label = QLabel('', self)
        self.label.setObjectName('progressStageLabel')
        self.count_label = QLabel('', self)
        self.count_label.setObjectName('progressStageCount')
        self.count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        text_row.addWidget(self.label, 1)
        text_row.addWidget(self.count_label)
        layout.addLayout(text_row)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedWidth(360)
        layout.addWidget(self.progress_bar)
        self.update_stage(stage)

    def update_stage(self, stage: ProgressStageSnapshot) -> None:
        """Refresh row text and progress-bar state from a stage snapshot."""
        self.label.setText(stage.label)
        count_text = _stage_count_text(stage)
        self.count_label.setText(count_text)
        self.count_label.setVisible(bool(count_text))

        if stage.total is None:
            self.progress_bar.setVisible(True)
            if stage.status == 'active':
                self.progress_bar.setRange(0, 0)
            else:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(
                    100 if stage.status == 'complete' else 0
                )

            return

        if stage.total <= 0:
            self.progress_bar.hide()
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, stage.total)
        self.progress_bar.setValue(stage.progress_value())


def _stage_count_text(stage: ProgressStageSnapshot) -> str:
    """Return the count text shown in a rendered progress stage row."""
    count_text = stage.count_text()
    if stage.stage_id == 'metadata' and count_text:
        return f'Batch {count_text}'

    return count_text


class ProgressStageListWidget(QWidget):
    """Reusable ordered stage-list renderer for progress overlays."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName('progressStageList')
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)
        self._rows: dict[str, ProgressStageRow] = {}
        self.hide()

    def update_snapshot(self, snapshot: ProgressSnapshot) -> None:
        """Render the ordered stage rows in ``snapshot``."""
        expected_stage_ids = {stage.stage_id for stage in snapshot.stages}
        for stage_id, row in list(self._rows.items()):
            if stage_id not in expected_stage_ids:
                self._layout.removeWidget(row)
                row.deleteLater()
                del self._rows[stage_id]

        for index, stage in enumerate(snapshot.stages):
            row = self._rows.get(stage.stage_id)
            if row is None:
                row = ProgressStageRow(stage, self)
                self._rows[stage.stage_id] = row
                self._layout.insertWidget(index, row)
            else:
                self._layout.removeWidget(row)
                self._layout.insertWidget(index, row)
                row.update_stage(stage)

        self.setVisible(bool(snapshot.stages))

    def clear_stages(self) -> None:
        """Remove all rendered stage rows and hide the list."""
        for row in self._rows.values():
            self._layout.removeWidget(row)
            row.deleteLater()

        self._rows.clear()
        self.hide()


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


def build_progress_overlay(parent: QWidget) -> ProgressOverlayWidgets:
    """Build the common centered progress overlay widget bundle."""
    overlay = QWidget(parent)
    overlay.setObjectName('progressOverlay')
    overlay.hide()
    overlay_layout = QVBoxLayout(overlay)
    overlay_layout.setContentsMargins(0, 0, 0, 0)
    overlay_layout.addStretch(1)
    overlay_center = QHBoxLayout()
    overlay_center.addStretch(1)
    panel = QFrame(overlay)
    panel.setObjectName('progressPanel')
    panel_layout = QVBoxLayout(panel)
    panel_layout.setContentsMargins(24, 20, 24, 20)
    panel_layout.setSpacing(14)
    message_label = QLabel('', panel)
    message_label.setAlignment(Qt.AlignCenter)
    panel_layout.addWidget(message_label)
    progress_bar = QProgressBar(panel)
    progress_bar.setRange(0, 100)
    progress_bar.setFixedWidth(360)
    panel_layout.addWidget(progress_bar)
    stage_list = ProgressStageListWidget(panel)
    panel_layout.addWidget(stage_list)
    overlay_center.addWidget(panel)
    overlay_center.addStretch(1)
    overlay_layout.addLayout(overlay_center)
    overlay_layout.addStretch(1)
    return ProgressOverlayWidgets(
        overlay=overlay,
        panel=panel,
        message_label=message_label,
        progress_bar=progress_bar,
        stage_list=stage_list,
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
