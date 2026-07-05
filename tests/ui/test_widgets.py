from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QPixmap, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication

import easy_loupe.ui.theme as theme_module
import easy_loupe.ui.widgets as widgets_module
from tests.ui._helpers import (
    create_jpeg,
    image_pixel_rgb,
    render_widget_image,
)

if TYPE_CHECKING:
    from pathlib import Path


def _label_top(label: Any) -> int:
    parent = label.parentWidget()
    assert parent is not None
    return parent.y() + label.geometry().top()


def _label_bottom(label: Any) -> int:
    parent = label.parentWidget()
    assert parent is not None
    return parent.y() + label.geometry().bottom()


class _ThumbnailListOwner:
    @staticmethod
    def extend_thumbnail_selection(_direction: int) -> bool:
        return False


def _wheel_event(*, pixel_delta: int = 0, angle_delta: int = 0) -> QWheelEvent:
    return QWheelEvent(
        QPointF(10, 10),
        QPointF(10, 10),
        QPoint(0, pixel_delta),
        QPoint(0, angle_delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def test_thumbnail_list_wheel_event_scrolls_at_half_speed() -> None:
    """
    Verify wheel input scrolls the left thumbnail strip at reduced speed.

    The main culling view uses ``ThumbnailListWidget`` for its vertical strip;
    this keeps the UX tuning local to that widget and protects against falling
    back to Qt's faster default wheel handling.
    """
    app = QApplication.instance() or QApplication([])
    widget = widgets_module.ThumbnailListWidget(_ThumbnailListOwner())
    widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    widget.verticalScrollBar().setSingleStep(20)
    widget.resize(160, 120)
    for row in range(40):
        widget.addItem(f'IMG_{row:04d}')

    widget.show()
    app.processEvents()

    scroll_bar = widget.verticalScrollBar()
    assert scroll_bar.maximum() > 0

    full_speed_delta = (
        QApplication.wheelScrollLines() * scroll_bar.singleStep()
    )
    widget.wheelEvent(_wheel_event(angle_delta=-120))

    assert scroll_bar.value() == int(full_speed_delta / 2)

    scroll_bar.setValue(0)
    widget.wheelEvent(_wheel_event(pixel_delta=-7))
    first_pixel_scroll = scroll_bar.value()
    widget.wheelEvent(_wheel_event(pixel_delta=-7))

    assert first_pixel_scroll == 3
    assert scroll_bar.value() == 7

    widget.close()


def test_thumbnail_preview_widget_masks_outside_visible_region_and_draws_red_edge() -> (
    None
):
    app = QApplication.instance() or QApplication([])
    widget = widgets_module.ThumbnailPreviewWidget(QSize(120, 90))
    pixmap = QPixmap(120, 90)
    pixmap.fill(QColor('#f4f4f4'))
    widget.set_pixmap(pixmap)
    widget.show()
    app.processEvents()

    baseline_image = render_widget_image(widget)
    baseline_outside = image_pixel_rgb(baseline_image, 15, 15)
    baseline_inside = image_pixel_rgb(baseline_image, 60, 45)

    assert baseline_outside == baseline_inside

    widget.set_visible_region_overlay((0.25, 0.25, 0.5, 0.5))
    app.processEvents()

    image = render_widget_image(widget)
    target = widget.displayed_image_rect()
    overlay = widget.visible_region_overlay()

    assert overlay is not None

    inside_x = int(target.left() + target.width() * 0.5)
    inside_y = int(target.top() + target.height() * 0.5)
    outside_x = int(target.left() + target.width() * 0.1)
    outside_y = int(target.top() + target.height() * 0.1)
    edge_x = int(target.left() + target.width() * overlay[0])
    edge_y = int(
        target.top() + target.height() * (overlay[1] + (overlay[3] / 2))
    )

    inside = image_pixel_rgb(image, inside_x, inside_y)
    outside = image_pixel_rgb(image, outside_x, outside_y)
    edge = image_pixel_rgb(image, edge_x, edge_y)

    assert sum(outside) < sum(inside)
    assert edge[0] > edge[1] + 40
    assert edge[0] > edge[2] + 40

    widget.set_visible_region_overlay(None)
    app.processEvents()

    cleared_image = render_widget_image(widget)
    cleared_outside = image_pixel_rgb(cleared_image, outside_x, outside_y)

    assert cleared_outside == baseline_outside

    widget.close()


def test_thumbnail_preview_widget_emits_normalized_minimap_click() -> None:
    """
    Verify minimap clicks emit image-normalized center coordinates.

    The widget is reused by strip thumbnails and the standalone floating
    minimap, so this guards the shared signal contract independently of either
    host window's routing policy.
    """
    app = QApplication.instance() or QApplication([])
    widget = widgets_module.ThumbnailPreviewWidget(QSize(100, 100))
    pixmap = QPixmap(100, 50)
    pixmap.fill(QColor('#f4f4f4'))
    widget.set_pixmap(pixmap)
    widget.set_visible_region_overlay((0.2, 0.2, 0.5, 0.5))
    widget.show()
    app.processEvents()

    centers: list[tuple[float, float]] = []
    widget.visible_region_center_requested.connect(
        lambda x, y: centers.append((x, y))
    )

    QTest.mousePress(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(75, 50),
    )
    app.processEvents()

    assert centers == pytest.approx([(0.75, 0.5)])

    QTest.mouseRelease(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(75, 50),
    )
    widget.close()


def test_thumbnail_preview_widget_drags_and_clamps_minimap_edges() -> None:
    """
    Verify held-button minimap drags clamp to the displayed image edges.

    Letterboxed thumbnails have widget area outside the photo; dragging beyond
    the minimap should pin to the image boundary instead of producing invalid
    centers or continuing past the red-box travel range.
    """
    app = QApplication.instance() or QApplication([])
    widget = widgets_module.ThumbnailPreviewWidget(QSize(100, 100))
    pixmap = QPixmap(100, 50)
    pixmap.fill(QColor('#f4f4f4'))
    widget.set_pixmap(pixmap)
    widget.set_visible_region_overlay((0.2, 0.2, 0.5, 0.5))
    widget.show()
    app.processEvents()

    centers: list[tuple[float, float]] = []
    widget.visible_region_center_requested.connect(
        lambda x, y: centers.append((x, y))
    )

    QTest.mousePress(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(50, 50),
    )
    QTest.mouseMove(widget, QPoint(-20, 130))
    QTest.mouseRelease(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(-20, 130),
    )
    app.processEvents()

    assert centers[0] == pytest.approx((0.5, 0.5))
    assert centers[-1] == pytest.approx((0.0, 1.0))

    widget.close()


def test_thumbnail_preview_widget_without_overlay_emits_no_minimap_signal() -> (
    None
):
    """
    Verify thumbnails without a red-box overlay do not consume minimap input.

    Normal strip thumbnails still need ordinary list selection behavior, so the
    preview widget should emit and track drags only while an overlay is active.
    """
    app = QApplication.instance() or QApplication([])
    widget = widgets_module.ThumbnailPreviewWidget(QSize(100, 100))
    pixmap = QPixmap(100, 50)
    pixmap.fill(QColor('#f4f4f4'))
    widget.set_pixmap(pixmap)
    widget.show()
    app.processEvents()

    centers: list[tuple[float, float]] = []
    widget.visible_region_center_requested.connect(
        lambda x, y: centers.append((x, y))
    )

    QTest.mousePress(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(50, 50),
    )
    QTest.mouseMove(widget, QPoint(75, 50))
    QTest.mouseRelease(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(75, 50),
    )
    app.processEvents()

    assert centers == []
    assert widget._visible_region_drag_active is False

    widget.close()


def test_thumbnail_preview_widget_emits_passive_image_click_position() -> None:
    """
    Verify plain image-area thumbnail clicks emit normalized positions.

    Non-overlay thumbnails need to pass selection through to their host list,
    but MainWindow also needs the clicked image point for spatial zoom handoff.
    """
    app = QApplication.instance() or QApplication([])
    widget = widgets_module.ThumbnailPreviewWidget(QSize(100, 100))
    pixmap = QPixmap(100, 50)
    pixmap.fill(QColor('#f4f4f4'))
    widget.set_pixmap(pixmap)
    widget.show()
    app.processEvents()

    clicked: list[tuple[float, float]] = []
    dragged: list[tuple[float, float]] = []
    widget.image_position_clicked.connect(lambda x, y: clicked.append((x, y)))
    widget.image_position_dragged.connect(lambda x, y: dragged.append((x, y)))

    QTest.mousePress(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(75, 50),
    )
    app.processEvents()

    assert clicked == pytest.approx([(0.75, 0.5)])
    assert dragged == []
    assert widget._image_position_drag_active is True
    assert widget._visible_region_drag_active is False

    QTest.mouseRelease(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(75, 50),
    )
    assert widget._image_position_drag_active is False
    widget.close()


def test_thumbnail_preview_widget_passive_image_drag_clamps_edges() -> None:
    """
    Verify held passive thumbnail drags emit clamped image positions.

    This protects the click-and-hold spatial zoom path used when selecting a
    different thumbnail and immediately dragging the red box without release.
    """
    app = QApplication.instance() or QApplication([])
    widget = widgets_module.ThumbnailPreviewWidget(QSize(100, 100))
    pixmap = QPixmap(100, 50)
    pixmap.fill(QColor('#f4f4f4'))
    widget.set_pixmap(pixmap)
    widget.show()
    app.processEvents()

    dragged: list[tuple[float, float]] = []
    widget.image_position_dragged.connect(lambda x, y: dragged.append((x, y)))

    QTest.mousePress(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(50, 50),
    )
    QTest.mouseMove(widget, QPoint(-20, 130))
    app.processEvents()

    assert dragged[-1] == pytest.approx((0.0, 1.0))

    QTest.mouseRelease(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(-20, 130),
    )
    assert widget._image_position_drag_active is False
    widget.close()


def test_thumbnail_preview_widget_ignores_outside_passive_image_click() -> (
    None
):
    """
    Verify passive spatial clicks are limited to the displayed image.

    Thumbnail cards include margins and letterboxing; those areas should keep
    ordinary selection behavior without carrying an unrelated zoom center.
    """
    app = QApplication.instance() or QApplication([])
    widget = widgets_module.ThumbnailPreviewWidget(QSize(100, 100))
    pixmap = QPixmap(100, 50)
    pixmap.fill(QColor('#f4f4f4'))
    widget.set_pixmap(pixmap)
    widget.show()
    app.processEvents()

    clicked: list[tuple[float, float]] = []
    dragged: list[tuple[float, float]] = []
    widget.image_position_clicked.connect(lambda x, y: clicked.append((x, y)))
    widget.image_position_dragged.connect(lambda x, y: dragged.append((x, y)))

    QTest.mousePress(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(50, 10),
    )
    app.processEvents()

    assert clicked == []
    assert dragged == []
    assert widget._image_position_drag_active is False

    QTest.mouseRelease(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(50, 10),
    )
    widget.close()


def test_thumbnail_preview_widget_ignores_modified_passive_image_click() -> (
    None
):
    """
    Verify modifier-assisted thumbnail clicks do not emit spatial centers.

    Shift/Control/Command selection gestures should remain pure selection
    actions instead of also rewriting remembered zoom centers.
    """
    app = QApplication.instance() or QApplication([])
    widget = widgets_module.ThumbnailPreviewWidget(QSize(100, 100))
    pixmap = QPixmap(100, 50)
    pixmap.fill(QColor('#f4f4f4'))
    widget.set_pixmap(pixmap)
    widget.show()
    app.processEvents()

    clicked: list[tuple[float, float]] = []
    dragged: list[tuple[float, float]] = []
    widget.image_position_clicked.connect(lambda x, y: clicked.append((x, y)))
    widget.image_position_dragged.connect(lambda x, y: dragged.append((x, y)))

    QTest.mousePress(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        QPoint(75, 50),
    )
    app.processEvents()

    assert clicked == []
    assert dragged == []
    assert widget._image_position_drag_active is False

    QTest.mouseRelease(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        QPoint(75, 50),
    )
    widget.close()


def test_thumbnail_item_widget_reserves_metadata_row_height(
        tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    thumb_path = tmp_path / 'IMG_1000.JPG'
    create_jpeg(thumb_path, 'dimgray')
    theme = theme_module.THEMES['dark']

    empty_widget = widgets_module.ThumbnailItemWidget(
        thumb_path=thumb_path,
        stem='IMG_1000',
        metadata_text='',
        frame_size=QSize(220, 165),
        theme=theme,
    )
    tagged_widget = widgets_module.ThumbnailItemWidget(
        thumb_path=thumb_path,
        stem='IMG_1000',
        metadata_text='★★★★★ ✅',
        frame_size=QSize(220, 165),
        theme=theme,
    )
    for widget in (empty_widget, tagged_widget):
        widget.resize(widget.sizeHint())
        widget.show()

    app.processEvents()

    image_bottom = max(
        frame.geometry().bottom() for frame in tagged_widget._frames
    )
    empty_name_top = _label_top(empty_widget.name_label)
    name_top = _label_top(tagged_widget.name_label)
    meta_top = _label_top(tagged_widget.meta_label)

    assert (
        empty_widget.sizeHint().height() == tagged_widget.sizeHint().height()
    )
    assert empty_widget.meta_label.isVisible() is False
    assert tagged_widget.meta_label.isVisible() is True
    assert empty_name_top == name_top
    assert name_top > image_bottom
    assert name_top - image_bottom < tagged_widget.name_label.height()
    assert meta_top > _label_bottom(tagged_widget.name_label)

    empty_widget.close()
    tagged_widget.close()


def test_thumbnail_item_widget_reserves_metadata_row_height_for_scene_cards(
        tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    thumb_path = tmp_path / 'IMG_2000.JPG'
    create_jpeg(thumb_path, 'green')
    theme = theme_module.THEMES['dark']

    scene_empty_widget = widgets_module.ThumbnailItemWidget(
        thumb_path=thumb_path,
        stem='IMG_2000',
        metadata_text='',
        frame_size=QSize(160, 120),
        theme=theme,
    )
    scene_tagged_widget = widgets_module.ThumbnailItemWidget(
        thumb_path=thumb_path,
        stem='IMG_2000',
        metadata_text='★★★☆☆',
        frame_size=QSize(160, 120),
        theme=theme,
    )
    stacked_widget = widgets_module.ThumbnailItemWidget(
        thumb_path=thumb_path,
        stem='IMG_2000...IMG_2001',
        metadata_text='',
        frame_size=QSize(160, 120),
        theme=theme,
        scene_count=2,
        stacked=True,
    )
    app.processEvents()

    empty_text_height = scene_empty_widget.name_label.parentWidget().height()
    stacked_text_height = stacked_widget.name_label.parentWidget().height()
    empty_name_top = _label_top(scene_empty_widget.name_label)
    tagged_name_top = _label_top(scene_tagged_widget.name_label)

    assert (
        scene_empty_widget.sizeHint().height()
        == scene_tagged_widget.sizeHint().height()
    )
    assert empty_name_top == tagged_name_top
    assert stacked_widget.meta_label.isVisible() is False
    assert stacked_text_height == empty_text_height

    scene_empty_widget.close()
    scene_tagged_widget.close()
    stacked_widget.close()
