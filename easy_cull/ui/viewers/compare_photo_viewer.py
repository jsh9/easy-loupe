"""Multi-photo compare viewer with optional locked zoom."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from easy_cull.ui.theme import NO_METADATA_TEXT, THEMES, ThemePalette
from easy_cull.ui.viewers.photo_viewer import PhotoViewer

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtGui import QMouseEvent

DEFAULT_COMPARE_PHOTO_LIMIT = 8
COMPARE_PHOTO_LIMIT_OPTIONS = (2, 3, 4, 6, 8, 10, 12, 16, 20)
MIN_COMPARE_PHOTO_COUNT = 2
COMPARE_ZOOM_EPSILON = 1.001
COMPARE_PANE_DRAG_THRESHOLD_PX = 4.0
SMALL_GRID_MAX_PHOTOS = 4
MEDIUM_GRID_MAX_PHOTOS = 6
MEDIUM_GRID_COLUMNS = 3
EIGHT_PHOTO_GRID_MAX_PHOTOS = 8
EIGHT_PHOTO_GRID_COLUMNS = 4
TEN_PHOTO_GRID_MAX_PHOTOS = 10
TEN_PHOTO_GRID_COLUMNS = 5
TWELVE_PHOTO_GRID_MAX_PHOTOS = 12
TWELVE_PHOTO_GRID_ROWS = 3
TWELVE_PHOTO_GRID_COLUMNS = 4
SIXTEEN_PHOTO_GRID_MAX_PHOTOS = 16
SIXTEEN_PHOTO_GRID_ROWS = 4
SIXTEEN_PHOTO_GRID_COLUMNS = 4
TWENTY_PHOTO_GRID_ROWS = 4
TWENTY_PHOTO_GRID_COLUMNS = 5
ACTIVE_COMPARE_BORDER_WIDTH = 4
SHORT_ROW_MAX_PHOTOS = 3
VERTICAL_ASPECT_RATIO_MAX = 1.0
VERTICAL_FOUR_PHOTO_ROW_THRESHOLD = 3
COMPARE_HELP_TEXT = (
    'Use ←→↑↓ to navigate. Tag as usual. Use W/A/S/D or mouse to pan. '
    'Esc to exit. G to enter the Browse mode'
)


@dataclass(frozen=True)
class ComparePhoto:
    """Photo payload needed by the compare viewer."""

    photo_id: str
    image_path: Path
    focus_point: tuple[float, float]
    metadata_text: str = ''


class ComparePanePhotoViewer(PhotoViewer):
    """
    Photo viewer variant that emits compare click and drag gestures.

    Compare mode needs left-click to select/recenter panes and left-drag to pan
    locked panes together. Keeping those signals and gesture state in this
    subclass prevents normal single and split viewers from carrying unused
    compare-only behavior.
    """

    normalized_left_clicked = Signal(float, float)
    image_dragged = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._left_press_pos = QPointF()
        self._last_left_drag_pos = QPointF()
        self._left_press_active = False
        self._left_drag_active = False

    def clear_photo(self) -> None:
        """Clear the photo and reset compare gesture state."""
        self._left_press_active = False
        self._left_drag_active = False
        super().clear_photo()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        """
        Arm compare click or drag gestures from a left-button press.

        Compare mode uses left-click to select/recenter a pane and left-drag to
        pan one or more panes, so this subclass consumes that input before the
        generic graphics-view handler sees it.
        """
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._image_size.isEmpty()
        ):
            self._left_press_pos = event.position()
            self._last_left_drag_pos = event.position()
            self._left_press_active = True
            self._left_drag_active = False
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        """
        Emit compare drag deltas after small pointer movement is exceeded.

        Drag deltas are emitted in image-space units so locked compare panes
        can pan together even when each pane has its own widget size or zoom
        factor.
        """
        if self._left_press_active:
            delta_from_press = event.position() - self._left_press_pos
            if (
                not self._left_drag_active
                and delta_from_press.manhattanLength()
                >= COMPARE_PANE_DRAG_THRESHOLD_PX
            ):
                self._left_drag_active = True

            if self._left_drag_active:
                delta = event.position() - self._last_left_drag_pos
                self._last_left_drag_pos = event.position()
                self.image_dragged.emit(
                    -delta.x() / max(self._current_scale, 0.001),
                    -delta.y() / max(self._current_scale, 0.001),
                )
                event.accept()
                return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        """Emit a normalized compare click when the press was not a drag."""
        if (
            self._left_press_active
            and event.button() == Qt.MouseButton.LeftButton
        ):
            if not self._left_drag_active:
                normalized_point = self._normalized_point_from_viewport_pos(
                    event.position().toPoint()
                )
                if normalized_point is not None:
                    self.normalized_left_clicked.emit(*normalized_point)

            self._left_press_active = False
            self._left_drag_active = False
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def _normalized_point_from_viewport_pos(
            self, pos: object
    ) -> tuple[float, float] | None:
        if self._image_size.isEmpty():
            return None

        scene_pos = self.mapToScene(pos)
        width = max(self._image_size.width(), 1)
        height = max(self._image_size.height(), 1)
        return (
            max(0.0, min(1.0, scene_pos.x() / width)),
            max(0.0, min(1.0, scene_pos.y() / height)),
        )


class ComparePhotoViewer(QWidget):
    """Grid of photo viewers for side-by-side comparison."""

    active_photo_changed = Signal(str)

    def __init__(
            self,
            parent: QWidget | None = None,
            *,
            photo_limit: int = DEFAULT_COMPARE_PHOTO_LIMIT,
    ) -> None:
        super().__init__(parent)
        self.photo_limit = DEFAULT_COMPARE_PHOTO_LIMIT
        self.set_photo_limit(photo_limit)
        self._theme = THEMES['light']
        self._locked_zoom = True
        self._focus_point_marker_enabled = True
        self._active_index = 0
        self._rows = 1
        self._columns = 1
        self._photos: list[ComparePhoto] = []
        self._viewers: list[PhotoViewer] = []
        self._frames: list[QFrame] = []
        self._metadata_labels: list[QLabel] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(10)
        self.help_label = QLabel(COMPARE_HELP_TEXT, self)
        self.help_label.setObjectName('compareHelpLabel')
        self.help_label.setTextInteractionFlags(Qt.NoTextInteraction)
        toolbar.addWidget(self.help_label, 1)
        self.lock_zoom_button = QPushButton('🔒')
        self.lock_zoom_button.setCheckable(True)
        self.lock_zoom_button.setChecked(True)
        self.lock_zoom_button.setFixedSize(42, 32)
        self.lock_zoom_button.setToolTip('Locked zoom')
        self.lock_zoom_button.toggled.connect(self._set_locked_zoom)
        toolbar.addWidget(self.lock_zoom_button)
        root.addLayout(toolbar)

        self.grid_widget = QWidget(self)
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(6)
        root.addWidget(self.grid_widget, 1)

        self.set_theme(self._theme)

    def set_photos(
            self,
            photos: list[ComparePhoto],
            *,
            active_photo_id: str | None = None,
    ) -> None:
        """Load the provided photos into the compare grid."""
        self.clear()
        self._photos = list(photos[: self.photo_limit])
        self._active_index = 0
        for index, photo in enumerate(self._photos):
            self._append_photo_pane(index, photo)

        if active_photo_id is not None:
            self._active_index = self._active_index_for_photo_id(
                active_photo_id
            )

        rows, columns = self._grid_shape(
            len(self._photos), self._vertical_photo_count()
        )
        self._rows = rows
        self._columns = columns

        self._place_photo_panes()
        self._finish_photo_layout(rows, columns)
        self._sync_active_frame_styles()
        self._emit_active_photo_changed()

    def set_photo_limit(self, limit: object) -> int:
        """Set the maximum compare count and return the normalized value."""
        self.photo_limit = self.normalized_photo_limit(limit)
        return self.photo_limit

    @staticmethod
    def normalized_photo_limit(limit: object) -> int:
        """Return a supported compare photo limit."""
        if isinstance(limit, int):
            candidate = limit
        elif isinstance(limit, str):
            try:
                candidate = int(limit)
            except ValueError:
                return DEFAULT_COMPARE_PHOTO_LIMIT
        else:
            return DEFAULT_COMPARE_PHOTO_LIMIT

        if candidate in COMPARE_PHOTO_LIMIT_OPTIONS:
            return candidate

        return DEFAULT_COMPARE_PHOTO_LIMIT

    def _append_photo_pane(
            self,
            index: int,
            photo: ComparePhoto,
    ) -> None:
        frame, viewer, metadata_label = self._create_photo_pane(index, photo)
        self._frames.append(frame)
        self._viewers.append(viewer)
        self._metadata_labels.append(metadata_label)

    def _create_photo_pane(
            self, index: int, photo: ComparePhoto
    ) -> tuple[QFrame, PhotoViewer, QLabel]:
        frame = QFrame(self.grid_widget)
        frame.setObjectName('comparePane')
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(4, 4, 4, 4)
        frame_layout.setSpacing(4)

        viewer = ComparePanePhotoViewer(frame)
        viewer.set_focus_point_marker_visible(
            enabled=self._focus_point_marker_enabled
        )
        viewer.set_theme(self._theme)
        viewer.set_photo(photo.image_path, photo.focus_point)
        viewer.normalized_left_clicked.connect(
            lambda x, y, viewer_index=index: self._handle_viewer_click(
                viewer_index, (x, y)
            )
        )
        viewer.image_dragged.connect(
            lambda dx, dy, viewer_index=index: self._handle_viewer_drag(
                viewer_index, dx, dy
            )
        )
        frame_layout.addWidget(viewer)

        metadata_label = QLabel(frame)
        metadata_label.setObjectName('compareMetadataLabel')
        metadata_label.setAlignment(Qt.AlignCenter)
        metadata_label.setTextFormat(Qt.RichText)
        metadata_label.setStyleSheet(self._metadata_label_style())
        metadata_label.setFixedHeight(
            metadata_label.fontMetrics().height() + 4
        )
        metadata_label.setText(self._metadata_label_text(photo.metadata_text))
        frame_layout.addWidget(metadata_label)
        return frame, viewer, metadata_label

    def _place_photo_panes(self) -> None:
        for index, frame in enumerate(self._frames):
            row = index // self._columns
            column = index % self._columns
            self.grid_layout.addWidget(frame, row, column)

    def _finish_photo_layout(
            self,
            rows: int,
            columns: int,
    ) -> None:
        for row in range(rows):
            self.grid_layout.setRowStretch(row, 1)

        for column in range(columns):
            self.grid_layout.setColumnStretch(column, 1)

    def clear(self) -> None:
        """Remove all compare panes."""
        self._reset_grid_stretches()
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._photos = []
        self._viewers = []
        self._frames = []
        self._metadata_labels = []
        self._active_index = 0
        self._rows = 1
        self._columns = 1

    def _reset_grid_stretches(self) -> None:
        for row in range(max(self._rows, MIN_COMPARE_PHOTO_COUNT)):
            self.grid_layout.setRowStretch(row, 0)

        for column in range(max(self._columns, SMALL_GRID_MAX_PHOTOS)):
            self.grid_layout.setColumnStretch(column, 0)

    def photo_ids(self) -> list[str]:
        """Return the photo ids currently shown in compare mode."""
        return [photo.photo_id for photo in self._photos]

    def active_photo_id(self) -> str | None:
        """Return the active compare photo id."""
        if not self._photos:
            return None

        return self._photos[self._active_index].photo_id

    def set_active_photo_id(self, photo_id: str) -> None:
        """Set the active compare photo by id."""
        self._set_active_index(self._active_index_for_photo_id(photo_id))

    def _active_index_for_photo_id(self, photo_id: str) -> int:
        for index, photo in enumerate(self._photos):
            if photo.photo_id == photo_id:
                return index

        return self._active_index

    def update_metadata_texts(
            self, metadata_by_photo_id: dict[str, str]
    ) -> None:
        """Refresh pane metadata labels by photo id."""
        updated_photos: list[ComparePhoto] = []
        for photo, label in zip(
            self._photos, self._metadata_labels, strict=False
        ):
            metadata_text = metadata_by_photo_id.get(
                photo.photo_id, photo.metadata_text
            )
            updated_photos.append(
                ComparePhoto(
                    photo_id=photo.photo_id,
                    image_path=photo.image_path,
                    focus_point=photo.focus_point,
                    metadata_text=metadata_text,
                )
            )
            label.setText(self._metadata_label_text(metadata_text))

        self._photos = updated_photos

    def is_locked_zoom(self) -> bool:
        """Return whether zoom and pan are synchronized."""
        return self._locked_zoom

    def set_focus_point_marker_visible(self, *, enabled: bool) -> None:
        """Set whether compared panes show autofocus point markers."""
        self._focus_point_marker_enabled = enabled
        for viewer in self._viewers:
            viewer.set_focus_point_marker_visible(enabled=enabled)

    def set_theme(self, theme: ThemePalette) -> None:
        """Apply the current app theme."""
        self._theme = theme
        self.setStyleSheet(
            f'QWidget {{ background-color: {theme.viewer_background}; }}'
        )
        button_style = f"""
        QPushButton {{
            color: {theme.button_text_color};
            background-color: {theme.button_background};
            border: 1px solid {theme.button_border};
            border-radius: 6px;
            font-size: 16px;
        }}
        """
        self.lock_zoom_button.setStyleSheet(button_style)
        self.help_label.setStyleSheet(
            f"""
            QLabel#compareHelpLabel {{
                color: {theme.topbar_text_color};
                background: transparent;
                font-weight: 600;
            }}
            """
        )
        for label in self._metadata_labels:
            label.setStyleSheet(self._metadata_label_style())

        for viewer in self._viewers:
            viewer.set_theme(theme)

        self._sync_active_frame_styles()

    def _metadata_label_style(self) -> str:
        return f"""
        QLabel#compareMetadataLabel {{
            color: {self._theme.meta_color};
            background: transparent;
            font-weight: 600;
        }}
        """

    def set_fit_view(self) -> None:
        """Return every compared photo to fit view."""
        for viewer in self._viewers:
            viewer.set_fit_view()

    def toggle_focus_zoom(self) -> None:
        """Toggle every compared photo between fit and AF-centered zoom."""
        if not self._viewers:
            return

        if all(not viewer.should_preserve_zoom() for viewer in self._viewers):
            for viewer in self._viewers:
                viewer.zoom_to_focus_point()

            return

        self.set_fit_view()

    def zoom_step(self, multiplier: float) -> None:
        """Zoom all panes when locked, otherwise the active pane."""
        for viewer in self._target_viewers():
            viewer.zoom_step(multiplier)

    def pan_by(self, dx: float, dy: float) -> None:
        """Pan all panes when locked, or only the active pane when unlocked."""
        for viewer in self._target_viewers():
            viewer.pan_by(dx, dy)

    def keyboard_pan_by(self, base_dx: float, base_dy: float) -> None:
        """Pan target panes by zoom-relative keyboard deltas."""
        for viewer in self._target_viewers():
            viewer.keyboard_pan_by(base_dx, base_dy)

    def move_active_selection(self, row_delta: int, column_delta: int) -> None:
        """Move active selection through the visible compare grid."""
        if not self._photos:
            return

        columns = max(self._columns, 1)
        rows = max((len(self._photos) + columns - 1) // columns, 1)
        row = self._active_index // columns
        column = self._active_index % columns
        target_row = max(0, min(rows - 1, row + row_delta))
        target_column = max(0, min(columns - 1, column + column_delta))
        target_index = min(
            len(self._photos) - 1,
            (target_row * columns) + target_column,
        )
        self._set_active_index(target_index)

    def _set_locked_zoom(self, locked: bool) -> None:  # noqa: FBT001
        self._locked_zoom = locked
        self.lock_zoom_button.setText('🔒' if locked else '🔓')
        self.lock_zoom_button.setToolTip(
            'Locked zoom' if locked else 'Unlocked zoom'
        )
        self._sync_active_frame_styles()

    def _handle_viewer_click(
            self, index: int, center: tuple[float, float]
    ) -> None:
        if index < 0 or index >= len(self._viewers):
            return

        self._set_active_index(index)
        zoom_factor = self._viewers[index].current_zoom_factor()
        if zoom_factor <= COMPARE_ZOOM_EPSILON:
            zoom_factor = None

        if self._locked_zoom:
            targets = self._viewers
        else:
            targets = [self._viewers[index]]

        for viewer in targets:
            viewer.zoom_to_normalized_center(center, zoom_factor=zoom_factor)

    def _handle_viewer_drag(self, index: int, dx: float, dy: float) -> None:
        if index < 0 or index >= len(self._viewers):
            return

        self._set_active_index(index)
        targets = (
            self._viewers if self._locked_zoom else [self._viewers[index]]
        )
        for viewer in targets:
            viewer.pan_by(dx, dy)

    def _target_viewers(self) -> list[PhotoViewer]:
        if self._locked_zoom:
            return list(self._viewers)

        if not self._viewers:
            return []

        return [self._viewers[self._active_index]]

    def _vertical_photo_count(self) -> int:
        return sum(1 for viewer in self._viewers if self._is_vertical(viewer))

    @staticmethod
    def _is_vertical(viewer: PhotoViewer) -> bool:
        aspect_ratio = viewer.image_aspect_ratio()
        return (
            aspect_ratio is not None
            and aspect_ratio < VERTICAL_ASPECT_RATIO_MAX
        )

    def _sync_active_frame_styles(self) -> None:
        for index, frame in enumerate(self._frames):
            is_active = index == self._active_index
            border = (
                self._theme.selected_background
                if is_active
                else self._theme.button_border
            )
            frame.setStyleSheet(
                f"""
                QFrame#comparePane {{
                    background-color: {self._theme.viewer_background};
                    border: {ACTIVE_COMPARE_BORDER_WIDTH}px solid {border};
                    border-radius: 4px;
                }}
                """
            )

    @staticmethod
    def _metadata_label_text(metadata_text: str) -> str:
        if metadata_text:
            return metadata_text

        return f'<span style="color: transparent;">{NO_METADATA_TEXT}</span>'

    def _set_active_index(self, index: int) -> None:
        if not self._photos:
            return

        next_index = max(0, min(len(self._photos) - 1, index))
        if next_index == self._active_index:
            self._sync_active_frame_styles()
            return

        self._active_index = next_index
        self._sync_active_frame_styles()
        self._emit_active_photo_changed()

    def _emit_active_photo_changed(self) -> None:
        active_photo_id = self.active_photo_id()
        if active_photo_id is not None:
            self.active_photo_changed.emit(active_photo_id)

    @staticmethod
    def _grid_shape(count: int, vertical_count: int = 0) -> tuple[int, int]:
        if count <= MIN_COMPARE_PHOTO_COUNT:
            return (1, max(count, 1))

        if count <= SHORT_ROW_MAX_PHOTOS:
            return (1, count)

        if (
            count == SMALL_GRID_MAX_PHOTOS
            and vertical_count >= VERTICAL_FOUR_PHOTO_ROW_THRESHOLD
        ):
            return (1, SMALL_GRID_MAX_PHOTOS)

        if count <= SMALL_GRID_MAX_PHOTOS:
            return (MIN_COMPARE_PHOTO_COUNT, MIN_COMPARE_PHOTO_COUNT)

        if count <= MEDIUM_GRID_MAX_PHOTOS:
            return (MIN_COMPARE_PHOTO_COUNT, MEDIUM_GRID_COLUMNS)

        if count <= EIGHT_PHOTO_GRID_MAX_PHOTOS:
            return (MIN_COMPARE_PHOTO_COUNT, EIGHT_PHOTO_GRID_COLUMNS)

        if count <= TEN_PHOTO_GRID_MAX_PHOTOS:
            return (MIN_COMPARE_PHOTO_COUNT, TEN_PHOTO_GRID_COLUMNS)

        if count <= TWELVE_PHOTO_GRID_MAX_PHOTOS:
            return (TWELVE_PHOTO_GRID_ROWS, TWELVE_PHOTO_GRID_COLUMNS)

        if count <= SIXTEEN_PHOTO_GRID_MAX_PHOTOS:
            return (SIXTEEN_PHOTO_GRID_ROWS, SIXTEEN_PHOTO_GRID_COLUMNS)

        return (TWENTY_PHOTO_GRID_ROWS, TWENTY_PHOTO_GRID_COLUMNS)
