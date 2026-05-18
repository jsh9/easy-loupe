from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtWidgets import QApplication, QGraphicsItem

import easy_cull.ui.viewers.photo_viewer as photo_viewer_module
from tests.ui._helpers import create_jpeg

if TYPE_CHECKING:
    from pathlib import Path


def test_photo_viewer_restores_last_manual_view_for_same_photo_and_not_other_photo(
        tmp_path: Path,
) -> None:
    create_jpeg(tmp_path / 'IMG_7001.JPG', 'dimgray')
    create_jpeg(tmp_path / 'IMG_7002.JPG', 'blue')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7001.JPG', (0.25, 0.75))
    viewer.toggle_focus_zoom()
    viewer.zoom_step(1.25)
    viewer.pan_by(40, -30)
    remembered_scale = viewer._current_scale
    remembered_center = viewer.normalized_viewport_center()

    viewer.set_fit_view()
    assert viewer._mode == 'fit'

    viewer.toggle_focus_zoom()

    assert viewer._mode == 'manual'
    assert viewer._current_scale == pytest.approx(remembered_scale)
    assert viewer.normalized_viewport_center() == pytest.approx(
        remembered_center
    )

    viewer.set_fit_view()
    viewer.set_photo(tmp_path / 'IMG_7002.JPG', (0.8, 0.2))
    viewer.toggle_focus_zoom()

    assert viewer._mode == 'manual'
    assert viewer.normalized_viewport_center()[0] > 0.6
    assert viewer.normalized_viewport_center()[1] < 0.4
    assert viewer.normalized_viewport_center() != pytest.approx(
        remembered_center, abs=0.02
    )

    viewer.close()


def test_photo_viewer_visible_region_rect_tracks_manual_zoom_and_pan(
        tmp_path: Path,
) -> None:
    create_jpeg(tmp_path / 'IMG_7003.JPG', 'orange')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7003.JPG', (0.5, 0.5))

    assert viewer.visible_region_rect() is None

    viewer.toggle_focus_zoom()
    viewer.zoom_step(1.25)
    visible_region_before = viewer.visible_region_rect()

    assert visible_region_before is not None
    assert visible_region_before[2] < 1.0
    assert visible_region_before[3] < 1.0

    viewer.pan_by(40, -30)
    visible_region_after = viewer.visible_region_rect()

    assert visible_region_after is not None
    assert visible_region_after[0] > visible_region_before[0]
    assert visible_region_after[1] < visible_region_before[1]

    viewer.set_fit_view()

    assert viewer.visible_region_rect() is None

    viewer.close()


def test_photo_viewer_focus_point_marker_tracks_loaded_photo(
        tmp_path: Path,
) -> None:
    create_jpeg(tmp_path / 'IMG_7004.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    marker = viewer._focus_point_marker
    viewer.set_focus_point_marker_visible(enabled=True)
    viewer.set_photo(tmp_path / 'IMG_7004.JPG', (0.25, 0.75))

    assert marker.isVisible() is True
    assert marker.pos().x() == pytest.approx(160)
    assert marker.pos().y() == pytest.approx(360)

    viewer.toggle_focus_zoom()

    assert marker.isVisible() is True

    viewer.set_fit_view()

    assert marker.isVisible() is True

    viewer.clear_photo()

    assert marker.isVisible() is False

    viewer.close()


def test_photo_viewer_focus_point_marker_can_be_disabled_and_stays_screen_sized(
        tmp_path: Path,
) -> None:
    create_jpeg(tmp_path / 'IMG_7005.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    marker = viewer._focus_point_marker
    viewer.set_focus_point_marker_visible(enabled=True)
    viewer.set_photo(tmp_path / 'IMG_7005.JPG', (0.5, 0.5))
    viewer.toggle_focus_zoom()
    before_rect = marker.rect()

    assert marker.isVisible() is True
    assert before_rect.width() == pytest.approx(
        photo_viewer_module.FOCUS_POINT_MARKER_SIZE
    )
    assert before_rect.height() == pytest.approx(
        photo_viewer_module.FOCUS_POINT_MARKER_SIZE
    )
    assert bool(
        marker.flags()
        & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
    )

    viewer.zoom_step(1.25)

    assert marker.isVisible() is True
    assert marker.rect().width() == pytest.approx(before_rect.width())
    assert marker.rect().height() == pytest.approx(before_rect.height())

    viewer.set_focus_point_marker_visible(enabled=False)

    assert marker.isVisible() is False

    viewer.close()


def test_photo_viewer_focus_zoom_starts_from_af_point(
        tmp_path: Path,
) -> None:
    create_jpeg(tmp_path / 'IMG_7006.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7006.JPG', (0.8, 0.2))
    viewer.toggle_focus_zoom()

    assert viewer._mode == 'manual'
    assert viewer.normalized_viewport_center() == pytest.approx((0.8, 0.2))

    viewer.close()


def test_photo_viewer_remembered_manual_zoom_precedes_af_point_zoom(
        tmp_path: Path,
) -> None:
    create_jpeg(tmp_path / 'IMG_7007.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7007.JPG', (0.8, 0.2))
    viewer.toggle_focus_zoom()
    viewer.zoom_step(1.25)
    viewer.pan_by(-40, 30)
    remembered_scale = viewer._current_scale
    remembered_center = viewer.normalized_viewport_center()

    viewer.set_fit_view()
    viewer.toggle_focus_zoom()

    assert viewer._current_scale == pytest.approx(remembered_scale)
    assert viewer.normalized_viewport_center() == pytest.approx(
        remembered_center
    )

    viewer.close()
