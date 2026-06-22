"""Shared progress-overlay widgets and state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from easy_loupe.progress import ProgressSnapshot, ProgressStageSnapshot


@dataclass(frozen=True, slots=True)
class ProgressOverlayWidgets:
    """Widget bundle for a centered progress overlay."""

    overlay: QWidget
    panel: QFrame
    message_label: QLabel
    progress_bar: QProgressBar
    stage_list: ProgressStageListWidget


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
        for stage_id in list(self._rows):
            if stage_id not in expected_stage_ids:
                self._remove_stage_row(stage_id)

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
        for stage_id in list(self._rows):
            self._remove_stage_row(stage_id)

        self.hide()

    def _remove_stage_row(self, stage_id: str) -> None:
        """Detach one stale row immediately, then let Qt delete it later."""
        row = self._rows.pop(stage_id)
        self._layout.removeWidget(row)
        # ``deleteLater`` waits for the event loop; hide and detach first so a
        # stale row cannot paint over the next structured progress snapshot.
        row.hide()
        row.setParent(None)
        row.deleteLater()


class ProgressOverlayController:
    """Coordinate scalar and structured progress-overlay states."""

    def __init__(
            self,
            widgets: ProgressOverlayWidgets,
            *,
            update_geometry: Callable[[], None],
    ) -> None:
        self._widgets = widgets
        self._update_geometry = update_geometry

    def show_scalar(
            self,
            message: str,
            progress: int,
            *,
            max_value: int,
            show_bar: bool = True,
    ) -> None:
        """Show a legacy scalar progress bar and clear stage rows."""
        self._widgets.overlay.show()
        self._widgets.overlay.raise_()
        self._widgets.message_label.setText(message)
        self._widgets.stage_list.clear_stages()
        self._widgets.progress_bar.setVisible(show_bar)
        self._widgets.progress_bar.setRange(0, max_value)
        self._widgets.progress_bar.setValue(max(0, min(max_value, progress)))
        self._update_geometry()

    def show_snapshot(self, snapshot: ProgressSnapshot) -> None:
        """Show structured stage rows and hide the legacy aggregate bar."""
        self._widgets.overlay.show()
        self._widgets.overlay.raise_()
        self._widgets.message_label.setText(snapshot.current_message)
        self._widgets.progress_bar.setVisible(False)
        self._widgets.stage_list.update_snapshot(snapshot)
        self._update_geometry()

    def hide(self) -> None:
        """Hide the overlay and reset progress widgets."""
        self._widgets.overlay.hide()
        self._widgets.progress_bar.setVisible(True)
        self._widgets.progress_bar.setRange(0, 100)
        self._widgets.progress_bar.setValue(0)
        self._widgets.message_label.setText('')
        self._widgets.stage_list.clear_stages()

    def set_message_preserving_rows(self, message: str) -> None:
        """Update the overlay message without touching stage rows."""
        self._widgets.message_label.setText(message)
        self._update_geometry()

    def has_structured_rows(self) -> bool:
        """Return whether structured stage rows are currently visible."""
        return self._widgets.stage_list.isVisible()


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


def _stage_count_text(stage: ProgressStageSnapshot) -> str:
    """Return the count text shown in a rendered progress stage row."""
    count_text = stage.count_text()
    if stage.stage_id == 'metadata' and count_text:
        return f'Batch {count_text}'

    return count_text
