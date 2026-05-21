"""Low-level photo viewing widget with zoom, pan, and region tracking."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QMouseEvent, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)

from easy_cull.ui.theme import THEMES, ThemePalette

MAX_ZOOM_FACTOR = 10.0
"""Upper limit on how far the user can zoom into a photo, expressed as a
multiple of the "fit-to-window" scale.

The fit-to-window scale (``_fit_scale``) is the scale factor at which the
entire photo just fits inside the viewer widget without any cropping.  For
example, if the photo is 4000 * 3000 pixels and the viewer widget is
2000 * 1500 pixels, the fit-to-window scale is 0.5 (every photo pixel is
drawn as half a screen pixel).

This constant caps the absolute pixel scale at ``MAX_ZOOM_FACTOR *
_fit_scale``.  With a value of 10.0 and the example above, the maximum
absolute scale would be ``10.0 * 0.5 = 5.0``, meaning each photo pixel
can be enlarged to at most 5 screen pixels.

The value is set to 10.0 (rather than a smaller number like 4.0) to
provide enough headroom on platforms where the viewer widget can be much
wider than the photo (e.g. Qt's offscreen rendering backend on Windows).
In those situations, helper methods like ``_minimum_scale_for_center``
may need a higher scale to keep an off-center viewport fully within the
photo bounds, and a tight cap would silently clip the zoom level.
"""
FOCUS_POINT_MARKER_SIZE = 28.0
FOCUS_POINT_MARKER_PEN_WIDTH = 2
FOCUS_POINT_MARKER_COLOR = '#ff3b30'
LEFT_DRAG_THRESHOLD_PX = 4.0

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtGui import QResizeEvent


class PhotoViewer(QGraphicsView):
    """Photo viewing widget with fit, zoom, pan, and region tracking."""

    visible_region_changed = Signal()
    normalized_left_clicked = Signal(float, float)
    image_dragged = Signal(float, float)

    def __init__(
            self,
            parent: QWidget | None = None,
            *,
            manual_views: dict[str, tuple[float, tuple[float, float]]]
            | None = None,
            hold_zoom_enabled: bool = False,
    ) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self._focus_point_marker = QGraphicsRectItem(
            -FOCUS_POINT_MARKER_SIZE / 2,
            -FOCUS_POINT_MARKER_SIZE / 2,
            FOCUS_POINT_MARKER_SIZE,
            FOCUS_POINT_MARKER_SIZE,
        )
        self._focus_point_marker.setPen(
            QPen(
                QColor(FOCUS_POINT_MARKER_COLOR),
                FOCUS_POINT_MARKER_PEN_WIDTH,
            )
        )
        self._focus_point_marker.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self._focus_point_marker.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True
        )
        self._focus_point_marker.setZValue(10)
        self._focus_point_marker.setVisible(False)
        self._scene.addItem(self._focus_point_marker)
        self.setScene(self._scene)
        self.setAlignment(Qt.AlignCenter)
        self.setRenderHints(self.renderHints())
        self.setBackgroundBrush(Qt.black)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.NoFocus)

        self._image_size = QSize()
        self._fit_scale = 1.0
        self._current_scale = 1.0
        self._focus_point = QPointF(0.5, 0.5)
        self._center_point = QPointF(0.0, 0.0)
        self._current_image_key: str | None = None
        self._manual_views = {} if manual_views is None else manual_views
        self._mode = 'fit'
        self._focus_point_marker_enabled = False
        self._hold_zoom_enabled = hold_zoom_enabled
        self._hold_zoom_active = False
        self._last_hold_zoom_pos = QPointF()
        self._left_press_pos = QPointF()
        self._last_left_drag_pos = QPointF()
        self._left_press_active = False
        self._left_drag_active = False
        self.set_theme(THEMES['light'])

    def set_photo(
            self,
            image_path: Path,
            focus_point: tuple[float, float],
            *,
            preserve_zoom: bool = False,
            preserved_center: tuple[float, float] | None = None,
    ) -> None:
        """Load a photo and optionally restore a preserved manual zoom view."""
        zoom_factor = self.current_zoom_factor()
        pixmap = QPixmap(str(image_path))
        self._hold_zoom_active = False
        self._current_image_key = str(image_path)
        self._pixmap_item.setPixmap(pixmap)
        self._scene.setSceneRect(pixmap.rect())
        self._image_size = pixmap.size()
        self._focus_point = QPointF(focus_point[0], focus_point[1])
        self._position_focus_point_marker()
        if preserve_zoom and not self._image_size.isEmpty():
            self._fit_scale = self._compute_fit_scale()
            self._mode = 'manual'
            if preserved_center is None:
                preserved_center = (
                    self._focus_point.x(),
                    self._focus_point.y(),
                )

            min_scale = self._minimum_scale_for_center(preserved_center)
            self._current_scale = min(
                self._max_scale(),
                max(min_scale, self._fit_scale * zoom_factor),
            )
            self._center_point = QPointF(
                preserved_center[0] * self._image_size.width(),
                preserved_center[1] * self._image_size.height(),
            )
            self._apply_transform()
            return

        self.set_fit_view()

    def clear_photo(self) -> None:
        """Clear the current photo and reset viewer state to fit mode."""
        self._pixmap_item.setPixmap(QPixmap())
        self._scene.setSceneRect(0, 0, 0, 0)
        self._image_size = QSize()
        self._fit_scale = 1.0
        self._current_scale = 1.0
        self._center_point = QPointF(0.0, 0.0)
        self._current_image_key = None
        self._mode = 'fit'
        self._hold_zoom_active = False
        self._left_press_active = False
        self._left_drag_active = False
        self.resetTransform()
        self._update_focus_point_marker()
        self.visible_region_changed.emit()

    def set_theme(self, theme: ThemePalette) -> None:
        """Apply the theme background color to the viewer."""
        self.setBackgroundBrush(QColor(theme.viewer_background))

    def should_preserve_zoom(self) -> bool:
        """Return whether the current state represents a manual zoom view."""
        return (
            not self._image_size.isEmpty()
            and not self._hold_zoom_active
            and self._mode == 'manual'
            and self._current_scale > self._fit_scale + 0.001
        )

    def set_focus_point_marker_visible(self, *, enabled: bool) -> None:
        """Set whether loaded photos show the current focus point marker."""
        self._focus_point_marker_enabled = enabled
        self._update_focus_point_marker()

    def normalized_viewport_center(self) -> tuple[float, float] | None:
        """Return the viewport center as normalized image coordinates."""
        if self._image_size.isEmpty():
            return None

        width = max(self._image_size.width(), 1)
        height = max(self._image_size.height(), 1)
        return (
            max(0.0, min(1.0, self._center_point.x() / width)),
            max(0.0, min(1.0, self._center_point.y() / height)),
        )

    def visible_region_rect(self) -> tuple[float, float, float, float] | None:
        """Return the normalized rectangle currently visible in manual zoom."""
        if (
            not self._hold_zoom_active and not self.should_preserve_zoom()
        ) or self._image_size.isEmpty():
            return None

        viewport = self.viewport().size()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return None

        image_width = max(self._image_size.width(), 1)
        image_height = max(self._image_size.height(), 1)
        visible_width = min(
            viewport.width() / max(self._current_scale, 0.001), image_width
        )
        visible_height = min(
            viewport.height() / max(self._current_scale, 0.001), image_height
        )
        left = max(
            0.0,
            min(
                self._center_point.x() - (visible_width / 2),
                image_width - visible_width,
            ),
        )
        top = max(
            0.0,
            min(
                self._center_point.y() - (visible_height / 2),
                image_height - visible_height,
            ),
        )
        return (
            max(0.0, min(1.0, left / image_width)),
            max(0.0, min(1.0, top / image_height)),
            max(0.0, min(1.0, visible_width / image_width)),
            max(0.0, min(1.0, visible_height / image_height)),
        )

    def set_fit_view(self) -> None:
        """Reset the viewer to fit the whole image within the viewport."""
        if self._image_size.isEmpty():
            return

        self._hold_zoom_active = False
        self._mode = 'fit'
        self._current_scale = self._compute_fit_scale()
        self._center_point = QPointF(
            self._image_size.width() / 2, self._image_size.height() / 2
        )
        self._apply_transform()

    def toggle_focus_zoom(self) -> None:
        """Toggle between fit view and the stored focus zoom view."""
        if self._image_size.isEmpty():
            return

        self._hold_zoom_active = False
        if (
            self._mode == 'fit'
            or self._current_scale <= self._fit_scale + 0.001
        ):
            self.restore_or_focus_manual_view()
            return

        self._store_manual_view()
        self.set_fit_view()

    def zoom_step(self, multiplier: float) -> None:
        """Adjust the zoom level by the provided multiplier."""
        if self._image_size.isEmpty():
            return

        self._hold_zoom_active = False
        next_scale = max(
            self._fit_scale,
            min(self._max_scale(), self._current_scale * multiplier),
        )
        if next_scale <= self._fit_scale + 0.001:
            self._store_manual_view()
            self.set_fit_view()
            return

        self._mode = 'manual'
        self._current_scale = next_scale
        self._apply_transform()
        self._store_manual_view()

    def pan_by(self, dx: float, dy: float) -> None:
        """Pan the manual-zoom viewport by the given image-space delta."""
        if (
            self._image_size.isEmpty()
            or self._current_scale <= self._fit_scale + 0.001
        ):
            return

        self._hold_zoom_active = False
        self._mode = 'manual'
        self._center_point += QPointF(dx, dy)
        self._apply_transform()
        self._store_manual_view()

    def keyboard_pan_by(self, base_dx: float, base_dy: float) -> None:
        """Pan by a zoom-relative keyboard delta."""
        zoom_factor = max(self.current_zoom_factor(), 0.001)
        self.pan_by(base_dx / zoom_factor, base_dy / zoom_factor)

    def restore_or_focus_manual_view(self) -> None:
        """Restore the stored manual view or zoom to the focus point."""
        if self._image_size.isEmpty():
            return

        self._hold_zoom_active = False
        if self._restore_manual_view():
            return

        self._mode = 'manual'
        focus_center = (self._focus_point.x(), self._focus_point.y())
        self._current_scale = min(
            self._max_scale(),
            max(1.0, self._minimum_scale_for_center(focus_center)),
        )
        self._center_point = QPointF(
            focus_center[0] * self._image_size.width(),
            focus_center[1] * self._image_size.height(),
        )
        self._apply_transform()
        self._store_manual_view()

    def zoom_to_focus_point(self) -> None:
        """Zoom explicitly to the photo's autofocus point."""
        self.zoom_to_normalized_center((
            self._focus_point.x(),
            self._focus_point.y(),
        ))

    def zoom_to_normalized_center(
            self,
            center: tuple[float, float],
            *,
            zoom_factor: float | None = None,
    ) -> None:
        """Zoom to a normalized image center without using stored views."""
        if self._image_size.isEmpty():
            return

        self._hold_zoom_active = False
        self._fit_scale = self._compute_fit_scale()
        self._mode = 'manual'
        normalized_center = (
            max(0.0, min(1.0, center[0])),
            max(0.0, min(1.0, center[1])),
        )
        target_scale = (
            max(1.0, self._minimum_scale_for_center(normalized_center))
            if zoom_factor is None
            else max(
                self._minimum_scale_for_center(normalized_center),
                self._fit_scale * zoom_factor,
            )
        )
        self._current_scale = min(self._max_scale(), target_scale)
        self._center_point = QPointF(
            normalized_center[0] * self._image_size.width(),
            normalized_center[1] * self._image_size.height(),
        )
        self._apply_transform()
        self._store_manual_view()

    def set_manual_view(
            self, zoom_factor: float, center: tuple[float, float]
    ) -> None:
        """Apply an explicit manual zoom factor and normalized center point."""
        if self._image_size.isEmpty():
            return

        self._hold_zoom_active = False
        self._fit_scale = self._compute_fit_scale()
        self._mode = 'manual'
        self._current_scale = min(
            self._max_scale(),
            max(self._fit_scale, self._fit_scale * zoom_factor),
        )
        self._center_point = QPointF(
            center[0] * self._image_size.width(),
            center[1] * self._image_size.height(),
        )
        self._apply_transform_unclamped()
        self._store_manual_view()

    def current_manual_view(self) -> tuple[float, tuple[float, float]] | None:
        """Return the current manual zoom factor and normalized center."""
        if self._hold_zoom_active or not self.should_preserve_zoom():
            return None

        center = self.normalized_viewport_center()
        if center is None:
            return None

        return (self.current_zoom_factor(), center)

    def current_zoom_factor(self) -> float:
        """Return the zoom level relative to fit-to-window scale."""
        return self._current_scale / max(self._fit_scale, 0.001)

    def image_aspect_ratio(self) -> float | None:
        """Return the loaded image width/height ratio."""
        if self._image_size.isEmpty() or self._image_size.height() <= 0:
            return None

        return self._image_size.width() / self._image_size.height()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        """Recompute fit or manual zoom state after a viewport resize."""
        super().resizeEvent(event)
        if self._image_size.isEmpty():
            return

        viewport = self.viewport().size()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return

        self._fit_scale = self._compute_fit_scale()
        if self._hold_zoom_active:
            self._current_scale = min(
                self._max_scale(), max(1.0, self._fit_scale)
            )
            self._apply_transform()
        elif self._mode == 'fit':
            self.set_fit_view()
        elif not self._restore_manual_view():
            self._apply_transform()
            self._store_manual_view()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        """Temporarily zoom fit-to-window views while left button is held."""
        if (
            self._hold_zoom_enabled
            and event.button() == Qt.MouseButton.LeftButton
            and self._mode == 'fit'
            and not self._image_size.isEmpty()
        ):
            scene_pos = self.mapToScene(event.position().toPoint())
            self._hold_zoom_active = True
            self._last_hold_zoom_pos = event.position()
            self._mode = 'fit'
            self._current_scale = min(
                self._max_scale(), max(1.0, self._fit_scale)
            )
            self._center_point = QPointF(scene_pos.x(), scene_pos.y())
            self._apply_transform()
            event.accept()
            return

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
        """Pan the temporary hold-zoom viewport without storing manual zoom."""
        if self._hold_zoom_active:
            delta = event.position() - self._last_hold_zoom_pos
            self._last_hold_zoom_pos = event.position()
            self._center_point -= QPointF(
                delta.x() / max(self._current_scale, 0.001),
                delta.y() / max(self._current_scale, 0.001),
            )
            self._apply_transform()
            event.accept()
            return

        if self._left_press_active:
            delta_from_press = event.position() - self._left_press_pos
            if (
                not self._left_drag_active
                and delta_from_press.manhattanLength()
                >= LEFT_DRAG_THRESHOLD_PX
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
        """Restore fit-to-window view when temporary hold-zoom finishes."""
        if (
            self._hold_zoom_active
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.set_fit_view()
            event.accept()
            return

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

    def _store_manual_view(self) -> None:
        if self._current_image_key is None or self._image_size.isEmpty():
            return

        center = self.normalized_viewport_center()
        if center is None:
            return

        self._manual_views[self._current_image_key] = (
            self.current_zoom_factor(),
            center,
        )

    def _restore_manual_view(self) -> bool:
        if self._current_image_key is None or self._image_size.isEmpty():
            return False

        manual_view = self._manual_views.get(self._current_image_key)
        if manual_view is None:
            return False

        zoom_factor, center = manual_view
        self._fit_scale = self._compute_fit_scale()
        self._mode = 'manual'
        self._current_scale = min(
            self._max_scale(),
            max(self._fit_scale, self._fit_scale * zoom_factor),
        )
        self._center_point = QPointF(
            center[0] * self._image_size.width(),
            center[1] * self._image_size.height(),
        )
        self._apply_transform_unclamped()
        return True

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

    def _position_focus_point_marker(self) -> None:
        if self._image_size.isEmpty():
            self._focus_point_marker.setPos(0, 0)
            return

        self._focus_point_marker.setPos(
            self._focus_point.x() * self._image_size.width(),
            self._focus_point.y() * self._image_size.height(),
        )

    def _update_focus_point_marker(self) -> None:
        self._position_focus_point_marker()
        self._focus_point_marker.setVisible(
            self._focus_point_marker_enabled and not self._image_size.isEmpty()
        )

    def _max_scale(self) -> float:
        """Return the maximum allowed absolute pixel scale."""
        # The temporary hold-zoom should always be able to inspect at 100%.
        hold_zoom_scale = 1.0
        # Keyboard/manual zoom remains capped relative to fit-to-window scale.
        manual_zoom_cap = MAX_ZOOM_FACTOR * self._fit_scale
        # When fit-to-window is already near 100%, keep one usable manual step.
        minimum_manual_step_scale = self._fit_scale + 0.01

        # Use the largest requirement so every zoom mode has enough headroom.
        return max(hold_zoom_scale, manual_zoom_cap, minimum_manual_step_scale)

    def _compute_fit_scale(self) -> float:
        if self._image_size.isEmpty():
            return 1.0

        viewport = self.viewport().size()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return 1.0

        return min(
            viewport.width() / max(self._image_size.width(), 1),
            viewport.height() / max(self._image_size.height(), 1),
            1.0,
        )

    def _minimum_scale_for_center(self, center: tuple[float, float]) -> float:
        if self._image_size.isEmpty():
            return 1.0

        viewport = self.viewport().size()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return self._fit_scale

        width = max(self._image_size.width(), 1)
        height = max(self._image_size.height(), 1)
        target_x = max(0.0, min(1.0, center[0])) * width
        target_y = max(0.0, min(1.0, center[1])) * height
        half_available_width = max(min(target_x, width - target_x), 0.0)
        half_available_height = max(min(target_y, height - target_y), 0.0)
        min_scale_x = (
            0.0
            if half_available_width <= 0
            else viewport.width() / max(half_available_width * 2, 0.001)
        )
        min_scale_y = (
            0.0
            if half_available_height <= 0
            else viewport.height() / max(half_available_height * 2, 0.001)
        )
        return max(self._fit_scale, min_scale_x, min_scale_y)

    def _apply_transform(self) -> None:
        self._fit_scale = self._compute_fit_scale()
        if self._image_size.isEmpty():
            return

        self._clamp_center()
        self.resetTransform()
        self.scale(self._current_scale, self._current_scale)
        self.centerOn(self._center_point)
        self._update_focus_point_marker()
        self.visible_region_changed.emit()

    def _apply_transform_unclamped(self) -> None:
        """Apply the current transform without clamping the center point."""
        self._fit_scale = self._compute_fit_scale()
        if self._image_size.isEmpty():
            return

        self.resetTransform()
        self.scale(self._current_scale, self._current_scale)
        self.centerOn(self._center_point)
        self._update_focus_point_marker()
        self.visible_region_changed.emit()

    def _clamp_center(self) -> None:
        if self._image_size.isEmpty():
            return

        viewport = self.viewport().size()
        visible_width = viewport.width() / max(self._current_scale, 0.001)
        visible_height = viewport.height() / max(self._current_scale, 0.001)
        half_visible_width = min(
            visible_width / 2, self._image_size.width() / 2
        )
        half_visible_height = min(
            visible_height / 2, self._image_size.height() / 2
        )

        min_x = half_visible_width
        max_x = self._image_size.width() - half_visible_width
        min_y = half_visible_height
        max_y = self._image_size.height() - half_visible_height

        if min_x > max_x:
            center_x = self._image_size.width() / 2
        else:
            center_x = max(min_x, min(self._center_point.x(), max_x))

        if min_y > max_y:
            center_y = self._image_size.height() / 2
        else:
            center_y = max(min_y, min(self._center_point.y(), max_y))

        self._center_point = QPointF(center_x, center_y)
