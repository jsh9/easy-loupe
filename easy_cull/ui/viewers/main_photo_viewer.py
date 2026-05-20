"""High-level viewer container for single-pane and split-view modes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QStackedLayout, QWidget

from easy_cull.ui.theme import (
    SPLIT_VIEW_PANE_COUNT,
    THEMES,
    ThemePalette,
)
from easy_cull.ui.viewers.photo_viewer import PhotoViewer

if TYPE_CHECKING:
    from pathlib import Path


class MainPhotoViewer(QWidget):
    """Photo viewer container for single-pane and split-view modes."""

    visible_region_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manual_views: dict[str, tuple[float, tuple[float, float]]] = {}
        self._current_image_path: Path | None = None
        self._current_focus_point = (0.5, 0.5)
        self._focus_point_marker_enabled = True
        self._mode = 'single-fit'

        self.single_viewer = PhotoViewer(
            self, manual_views=self._manual_views, hold_zoom_enabled=True
        )
        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setObjectName('splitModeSplitter')
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(3)

        self.split_fit_viewer = PhotoViewer(
            self.splitter, hold_zoom_enabled=True
        )
        self.split_zoom_viewer = PhotoViewer(
            self.splitter, manual_views=self._manual_views
        )
        self.single_viewer.set_focus_point_marker_visible(
            enabled=self._focus_point_marker_enabled
        )
        self.split_fit_viewer.set_focus_point_marker_visible(
            enabled=self._focus_point_marker_enabled
        )
        self.split_zoom_viewer.set_focus_point_marker_visible(
            enabled=self._focus_point_marker_enabled
        )
        self.split_fit_viewer.setMinimumWidth(180)
        self.split_zoom_viewer.setMinimumWidth(180)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)

        self._layout = QStackedLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self.single_viewer)
        self._layout.addWidget(self.splitter)
        self._layout.setCurrentWidget(self.single_viewer)
        self.single_viewer.visible_region_changed.connect(
            self._forward_visible_region_changed
        )
        self.split_zoom_viewer.visible_region_changed.connect(
            self._forward_visible_region_changed
        )

        self.set_theme(THEMES['light'])

    @property
    def _current_scale(self) -> float:
        return self._active_zoom_viewer().current_zoom_factor()

    def is_split_view(self) -> bool:
        """Return whether the split-view widget is currently active."""
        return self._layout.currentWidget() is self.splitter

    def set_photo(
            self,
            image_path: Path,
            focus_point: tuple[float, float],
            *,
            preserve_zoom: bool = False,
            preserved_center: tuple[float, float] | None = None,
    ) -> None:
        """Display a photo in the active single-pane or split-view mode."""
        self._current_image_path = image_path
        self._current_focus_point = focus_point
        if self.is_split_view():
            self._show_split_photo()
        else:
            self.single_viewer.set_photo(
                image_path,
                focus_point,
                preserve_zoom=preserve_zoom,
                preserved_center=preserved_center,
            )

        self._sync_mode()

    def clear_photo(self) -> None:
        """Clear both viewer layouts and reset to single fit view."""
        self._current_image_path = None
        self._current_focus_point = (0.5, 0.5)
        self.single_viewer.clear_photo()
        self.split_fit_viewer.clear_photo()
        self.split_zoom_viewer.clear_photo()
        self._layout.setCurrentWidget(self.single_viewer)
        self._mode = 'single-fit'

    def set_theme(self, theme: ThemePalette) -> None:
        """Apply the theme to all embedded viewers and splitter chrome."""
        self.single_viewer.set_theme(theme)
        self.split_fit_viewer.set_theme(theme)
        self.split_zoom_viewer.set_theme(theme)
        self.splitter.setStyleSheet(
            f"""
            QSplitter#splitModeSplitter::handle {{
                background-color: {theme.button_border};
            }}
            """
        )

    def should_preserve_zoom(self) -> bool:
        """Return whether the active zoom viewer is in manual zoom."""
        return self._active_zoom_viewer().should_preserve_zoom()

    def normalized_viewport_center(self) -> tuple[float, float] | None:
        """Return the active zoom viewer's normalized viewport center."""
        return self._active_zoom_viewer().normalized_viewport_center()

    def visible_region_rect(self) -> tuple[float, float, float, float] | None:
        """Return the active zoom viewer's normalized visible rectangle."""
        return self._active_zoom_viewer().visible_region_rect()

    def set_focus_point_marker_visible(self, *, enabled: bool) -> None:
        """Set whether manual zoom panes show the autofocus point marker."""
        self._focus_point_marker_enabled = enabled
        self.single_viewer.set_focus_point_marker_visible(enabled=enabled)
        self.split_fit_viewer.set_focus_point_marker_visible(enabled=enabled)
        self.split_zoom_viewer.set_focus_point_marker_visible(enabled=enabled)

    def set_fit_view(self) -> None:
        """Switch the visible viewer back to single-pane fit mode."""
        if self._current_image_path is None:
            self._layout.setCurrentWidget(self.single_viewer)
            self._mode = 'single-fit'
            self.visible_region_changed.emit()
            return

        self._layout.setCurrentWidget(self.single_viewer)
        self.single_viewer.set_photo(
            self._current_image_path,
            self._current_focus_point,
            preserve_zoom=False,
        )
        self._mode = 'single-fit'
        self.visible_region_changed.emit()

    def toggle_focus_zoom(self) -> None:
        """Toggle focus zoom while preserving split-view manual state."""
        if self._current_image_path is None:
            return

        if self.is_split_view():
            manual_view = self.split_zoom_viewer.current_manual_view()
            self._layout.setCurrentWidget(self.single_viewer)
            self.single_viewer.set_photo(
                self._current_image_path,
                self._current_focus_point,
                preserve_zoom=False,
            )
            if manual_view is not None:
                self.single_viewer.set_manual_view(*manual_view)

            self._sync_mode()
            self.visible_region_changed.emit()
            return

        self.single_viewer.toggle_focus_zoom()
        self._sync_mode()
        self.visible_region_changed.emit()

    def toggle_split_view(self) -> None:
        """Switch between single-pane and split-view presentation."""
        if self._current_image_path is None:
            return

        if self.is_split_view():
            manual_view = self.split_zoom_viewer.current_manual_view()
            self._layout.setCurrentWidget(self.single_viewer)
            self.single_viewer.set_photo(
                self._current_image_path,
                self._current_focus_point,
                preserve_zoom=False,
            )
            if manual_view is not None:
                self.single_viewer.set_manual_view(*manual_view)

            self._sync_mode()
            self.visible_region_changed.emit()
            return

        self._layout.setCurrentWidget(self.splitter)
        self._show_split_photo()
        self._sync_mode()
        self.visible_region_changed.emit()

    def zoom_step(self, multiplier: float) -> None:
        """Adjust zoom on the currently active zoom viewer."""
        self._active_zoom_viewer().zoom_step(multiplier)
        self._sync_mode()

    def pan_by(self, dx: float, dy: float) -> None:
        """Pan the currently active zoom viewer by the given delta."""
        self._active_zoom_viewer().pan_by(dx, dy)
        self._sync_mode()

    def _active_zoom_viewer(self) -> PhotoViewer:
        return (
            self.split_zoom_viewer
            if self.is_split_view()
            else self.single_viewer
        )

    def _show_split_photo(self) -> None:
        if self._current_image_path is None:
            return

        self.split_fit_viewer.set_photo(
            self._current_image_path,
            self._current_focus_point,
            preserve_zoom=False,
        )
        self.split_zoom_viewer.set_photo(
            self._current_image_path,
            self._current_focus_point,
            preserve_zoom=False,
        )
        self.split_zoom_viewer.restore_or_focus_manual_view()
        self._ensure_split_sizes()

    def _ensure_split_sizes(self) -> None:
        sizes = self.splitter.sizes()
        if len(sizes) != SPLIT_VIEW_PANE_COUNT or min(sizes) <= 0:
            self.splitter.setSizes([1, 1])

    def _sync_mode(self) -> None:
        if self.is_split_view():
            self._mode = 'split'
        elif self.single_viewer.should_preserve_zoom():
            self._mode = 'single-manual'
        else:
            self._mode = 'single-fit'

    def _forward_visible_region_changed(self) -> None:
        if self.sender() is self._active_zoom_viewer():
            self.visible_region_changed.emit()
