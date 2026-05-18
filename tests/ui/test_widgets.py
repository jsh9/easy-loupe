from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

import easy_photo_culling.ui.theme as theme_module
import easy_photo_culling.ui.widgets as widgets_module
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
