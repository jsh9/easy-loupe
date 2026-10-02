from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

import easy_loupe.ui.viewers.photo_viewer as photo_viewer_module
from easy_loupe.ui.viewers.compare_photo_viewer import (
    ComparePhoto,
    ComparePhotoViewer,
)
from easy_loupe.ui.viewers.main_photo_viewer import MainPhotoViewer
from tests.ui._helpers import (
    CLIPPING_OVERLAY_TIMEOUT_MS,
    create_jpeg,
    process_events_until,
)

if TYPE_CHECKING:
    from pathlib import Path

RED = (200, 40, 40)
BLUE = (40, 60, 200)


def _create_split_png(path: Path, size: tuple[int, int]) -> None:
    """Write a lossless image whose left half is red and right half blue."""
    width, height = size
    image = Image.new('RGB', size, color=BLUE)
    image.paste(RED, (0, 0, width // 2, height))
    image.save(path, format='PNG')


def _show_photo_viewer(
        size: tuple[int, int],
) -> tuple[QApplication, photo_viewer_module.PhotoViewer]:
    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(*size)
    viewer.show()
    app.processEvents()
    return app, viewer


def _displayed_pixel(
        viewer: photo_viewer_module.PhotoViewer, x: float, y: float
) -> tuple[int, int, int]:
    """Return the displayed pixmap color at normalized ``(x, y)``."""
    image = viewer._pixmap_item.pixmap().toImage()
    color = image.pixelColor(
        min(int(x * image.width()), image.width() - 1),
        min(int(y * image.height()), image.height() - 1),
    )
    return (color.red(), color.green(), color.blue())


@pytest.mark.parametrize(
    ('rotation', 'red_point', 'blue_point', 'expected_aspect'),
    [
        pytest.param(0, (0.1, 0.5), (0.9, 0.5), 2.0, id='unrotated'),
        pytest.param(90, (0.5, 0.1), (0.5, 0.9), 0.5, id='clockwise'),
        pytest.param(180, (0.9, 0.5), (0.1, 0.5), 2.0, id='half-turn'),
        pytest.param(270, (0.5, 0.9), (0.5, 0.1), 0.5, id='counterclockwise'),
    ],
)
def test_photo_viewer_rotation_turns_displayed_pixels_clockwise(
        tmp_path: Path,
        rotation: int,
        red_point: tuple[float, float],
        blue_point: tuple[float, float],
        expected_aspect: float,
) -> None:
    """
    Verify view rotation turns the displayed pixels in the expected direction.

    The left (red) half must end up on top after a clockwise quarter turn.
    Pinning direction and aspect ratio protects the shared contract that all
    fit, zoom, and minimap math runs in the rotated frame.
    """
    image_path = tmp_path / 'IMG_R001.png'
    _create_split_png(image_path, (400, 200))
    _app, viewer = _show_photo_viewer((320, 240))

    viewer.set_photo(image_path, (0.5, 0.5), rotation=rotation)

    assert viewer.current_rotation() == rotation
    assert viewer.image_aspect_ratio() == pytest.approx(expected_aspect)
    assert _displayed_pixel(viewer, *red_point) == RED
    assert _displayed_pixel(viewer, *blue_point) == BLUE

    viewer.close()


def test_photo_viewer_rotation_maps_af_marker_into_rotated_frame(
        tmp_path: Path,
) -> None:
    """
    Verify AF points stay on the same subject after rotation.

    Callers keep passing AF points in the unrotated preview frame, including
    late AF updates, so the viewer must map them on every load and update.
    """
    image_path = tmp_path / 'IMG_R002.png'
    _create_split_png(image_path, (400, 200))
    _app, viewer = _show_photo_viewer((320, 240))
    viewer.set_focus_point_marker_visible(enabled=True)
    marker = viewer._focus_point_marker

    viewer.set_photo(image_path, (0.25, 0.1), rotation=90)

    # (x, y) -> (1 - y, x) in a 200x400 rotated scene.
    assert marker.pos().x() == pytest.approx(180)
    assert marker.pos().y() == pytest.approx(100)

    viewer.set_focus_point((0.75, 0.5))

    assert marker.pos().x() == pytest.approx(100)
    assert marker.pos().y() == pytest.approx(300)

    viewer.set_rotation(0)

    assert marker.pos().x() == pytest.approx(300)
    assert marker.pos().y() == pytest.approx(100)

    viewer.close()


def test_photo_viewer_set_rotation_keeps_fit_without_rereading_file(
        tmp_path: Path,
) -> None:
    """
    Verify in-place rotation reuses decoded pixels and keeps fit view.

    Viewer previews are full resolution, so re-decoding on every `]` press
    would stall the UI. Deleting the file proves the turn uses memory only.
    """
    image_path = tmp_path / 'IMG_R003.png'
    _create_split_png(image_path, (400, 200))
    _app, viewer = _show_photo_viewer((320, 240))
    viewer.set_photo(image_path, (0.5, 0.5))
    image_path.unlink()

    viewer.set_rotation(90)

    assert viewer.is_fit_view() is True
    assert viewer.image_aspect_ratio() == pytest.approx(0.5)
    assert _displayed_pixel(viewer, 0.5, 0.1) == RED
    assert viewer.visible_region_rect() is None

    viewer.close()


def test_photo_viewer_set_rotation_keeps_manual_detail_centered(
        tmp_path: Path,
) -> None:
    """
    Verify rotating during manual zoom keeps inspecting the same detail.

    The remembered center moves with the pixels, and the fit-relative zoom
    never shrinks (the fill-viewport rule may enlarge near edges). The turned
    view is also remembered under the new orientation.
    """
    image_path = tmp_path / 'IMG_R004.JPG'
    create_jpeg(image_path, 'dimgray', size=(2400, 1600))
    _app, viewer = _show_photo_viewer((1200, 800))
    viewer.set_photo(image_path, (0.5, 0.5))
    viewer.toggle_focus_zoom()
    viewer.set_normalized_viewport_center((0.3, 0.4))
    zoom_before = viewer.current_zoom_factor()

    viewer.set_rotation(90)

    assert viewer.should_preserve_zoom() is True
    assert viewer.normalized_viewport_center() == pytest.approx(
        (0.6, 0.3), abs=0.01
    )
    assert viewer.current_zoom_factor() >= zoom_before - 0.001
    remembered = viewer._manual_views[f'{image_path}|rotation=90']
    assert remembered.center == pytest.approx((0.6, 0.3), abs=0.01)

    viewer.close()


def test_photo_viewer_set_rotation_keeps_actual_size_inspection(
        tmp_path: Path,
) -> None:
    """
    Verify 100 percent inspection stays at true pixel scale after rotation.

    Actual-size inspection is absolute rather than fit-relative, so rotating
    must not reinterpret it through the new fit scale.
    """
    image_path = tmp_path / 'IMG_R005.JPG'
    create_jpeg(image_path, 'dimgray', size=(2400, 1600))
    _app, viewer = _show_photo_viewer((1200, 800))
    viewer.set_photo(image_path, (0.5, 0.5))
    viewer.zoom_to_actual_size((0.3, 0.4))

    viewer.set_rotation(90)

    assert viewer.is_actual_size_zoom_active() is True
    assert viewer._current_scale == pytest.approx(1.0)
    assert viewer.normalized_viewport_center() == pytest.approx(
        (0.6, 0.3), abs=0.01
    )

    viewer.close()


def test_photo_viewer_manual_memory_is_kept_per_rotation(
        tmp_path: Path,
) -> None:
    """
    Verify remembered zoom centers never cross orientations.

    A photo can be rotated while hidden (for example from a browse
    multi-selection). Its old center is in the unrotated frame, so focus
    zoom must start fresh at the rotated AF point, while rotation 0 keeps
    the historical plain image-path key.
    """
    image_path = tmp_path / 'IMG_R006.JPG'
    create_jpeg(image_path, 'dimgray', size=(2400, 1600))
    _app, viewer = _show_photo_viewer((1200, 800))
    viewer.set_photo(image_path, (0.4, 0.5))
    viewer.toggle_focus_zoom()
    viewer.set_normalized_viewport_center((0.7, 0.6))
    unrotated_memory = viewer._manual_views[str(image_path)]

    viewer.set_photo(image_path, (0.4, 0.5), rotation=90)
    viewer.toggle_focus_zoom()

    # The rotated AF point is (1 - 0.5, 0.4); the stale (0.7, 0.6) center
    # from the unrotated frame must not be restored.
    assert viewer.normalized_viewport_center() == pytest.approx(
        (0.5, 0.4), abs=0.01
    )
    assert viewer._manual_views[str(image_path)] == unrotated_memory
    assert f'{image_path}|rotation=90' in viewer._manual_views

    viewer.close()


def test_photo_viewer_late_af_clears_pending_centers_for_all_rotations(
        tmp_path: Path,
) -> None:
    """
    Verify late AF data drops fallback-centered pans in every orientation.

    Pans made while AF was pending are centered on fallback coordinates.
    Rotating carries that pan into a new orientation key, so both keys must
    be cleared or turning back could resurrect the stale view.
    """
    image_path = tmp_path / 'IMG_R007.JPG'
    create_jpeg(image_path, 'white', size=(2400, 1600))
    _app, viewer = _show_photo_viewer((1200, 800))
    viewer.set_photo(image_path, (0.5, 0.5), focus_point_pending=True)
    viewer.toggle_focus_zoom()
    viewer.zoom_step(2.0)
    viewer.pan_by(120, -80)
    viewer.set_rotation(90)

    assert str(image_path) in viewer._manual_views
    assert f'{image_path}|rotation=90' in viewer._manual_views

    viewer.set_focus_point((0.2, 0.8))

    assert str(image_path) not in viewer._manual_views
    assert f'{image_path}|rotation=90' not in viewer._manual_views

    viewer.close()


def _wait_for_clipping_overlay(
        app: QApplication, viewer: photo_viewer_module.PhotoViewer
) -> None:
    process_events_until(
        app,
        viewer._clipping_overlay_item.isVisible,
        timeout_ms=CLIPPING_OVERLAY_TIMEOUT_MS,
    )


def test_photo_viewer_rotates_clipping_overlay_without_new_job(
        tmp_path: Path,
) -> None:
    """
    Verify clipping warnings turn with the photo and stay aligned.

    Analysis runs on the unrotated cached preview, so the overlay must be
    rotated and rescaled with swapped dimensions. In-place rotation re-places
    the existing result instead of restarting background work.
    """
    image_path = tmp_path / 'IMG_R008.JPG'
    create_jpeg(image_path, 'white', size=(4000, 1000))
    app, viewer = _show_photo_viewer((320, 240))
    viewer.set_photo(image_path, (0.5, 0.5))
    viewer.set_clipping_warning_visible(enabled=True)
    _wait_for_clipping_overlay(app, viewer)
    overlay = viewer._clipping_overlay_item
    request_id = viewer._clipping_overlay_request_id

    viewer.set_rotation(90)

    assert viewer._clipping_overlay_request_id == request_id
    assert overlay.isVisible() is True
    assert overlay.pixmap().width() == 750
    assert overlay.pixmap().height() == 3000
    assert overlay.transform().m11() == pytest.approx(1000 / 750)
    assert overlay.transform().m22() == pytest.approx(4000 / 3000)

    viewer.close()


def test_photo_viewer_clipping_result_after_rotation_is_aligned(
        tmp_path: Path,
) -> None:
    """
    Verify a clipping job that lands after a rotation uses the new frame.

    Users can press `]` before the delayed background analysis finishes. The
    late result must be rotated at apply time rather than drawn sideways.
    """
    image_path = tmp_path / 'IMG_R009.JPG'
    create_jpeg(image_path, 'white', size=(4000, 1000))
    app, viewer = _show_photo_viewer((320, 240))
    viewer.set_clipping_warning_visible(enabled=True)
    viewer.set_photo(image_path, (0.5, 0.5))

    viewer.set_rotation(270)
    _wait_for_clipping_overlay(app, viewer)
    overlay = viewer._clipping_overlay_item

    assert overlay.pixmap().width() == 750
    assert overlay.pixmap().height() == 3000
    assert overlay.boundingRect().width() * overlay.transform().m11() == (
        pytest.approx(1000)
    )
    assert overlay.boundingRect().height() * overlay.transform().m22() == (
        pytest.approx(4000)
    )

    viewer.close()


def test_main_photo_viewer_rotation_survives_split_and_fit_reloads(
        tmp_path: Path,
) -> None:
    """
    Verify every internal reload keeps the current rotation.

    Split toggles, Space promotion, and forced fit all re-call
    ``PhotoViewer.set_photo`` from cached state; a stale cached rotation
    would silently undo the user's turn.
    """
    image_path = tmp_path / 'IMG_R010.png'
    _create_split_png(image_path, (400, 200))
    app = QApplication.instance() or QApplication([])
    viewer = MainPhotoViewer()
    viewer.resize(640, 480)
    viewer.show()
    app.processEvents()
    viewer.set_photo(image_path, (0.5, 0.5), rotation=90)

    viewer.toggle_split_view()

    assert viewer.split_fit_viewer.current_rotation() == 90
    assert viewer.split_zoom_viewer.current_rotation() == 90

    viewer.set_rotation(180)

    assert viewer.split_fit_viewer.current_rotation() == 180
    assert viewer.split_zoom_viewer.current_rotation() == 180

    viewer.toggle_focus_zoom()

    assert viewer.is_split_view() is False
    assert viewer.single_viewer.current_rotation() == 180

    viewer.set_fit_view()

    assert viewer.single_viewer.current_rotation() == 180

    viewer.set_rotation(270)
    viewer.toggle_split_view()
    viewer.toggle_split_view()

    assert viewer.single_viewer.current_rotation() == 270

    viewer.clear_photo()
    viewer.set_rotation(90)

    assert viewer.single_viewer.current_rotation() == 0

    viewer.close()


def _show_compare_viewer(
        tmp_path: Path, rotations: list[int]
) -> tuple[QApplication, ComparePhotoViewer]:
    for index in range(len(rotations)):
        create_jpeg(
            tmp_path / f'IMG_R1{index}.JPG', 'dimgray', size=(720, 480)
        )

    app = QApplication.instance() or QApplication([])
    viewer = ComparePhotoViewer()
    viewer.resize(1200, 520)
    viewer.show()
    app.processEvents()
    viewer.set_photos([
        ComparePhoto(
            f'IMG_R1{index}',
            tmp_path / f'IMG_R1{index}.JPG',
            (0.5, 0.5),
            rotation=rotation,
        )
        for index, rotation in enumerate(rotations)
    ])
    app.processEvents()
    return app, viewer


def test_compare_photo_viewer_shows_rotation_and_keeps_it_on_label_refresh(
        tmp_path: Path,
) -> None:
    """
    Verify compare panes display per-photo rotation and keep it.

    Metadata label refreshes rebuild the stored payloads; they must not drop
    the rotation that later selected-photo reloads read from.
    """
    _app, viewer = _show_compare_viewer(tmp_path, [90, 0])

    assert viewer._viewers[0].current_rotation() == 90
    assert viewer._viewers[1].current_rotation() == 0

    viewer.update_metadata_texts({'IMG_R10': 'rated'})
    viewer.show_active_photo()

    assert viewer._photos[0].rotation == 90
    assert viewer.selected_viewer.current_rotation() == 90

    viewer.close()


def test_compare_photo_viewer_rotation_relayouts_four_photo_grid(
        tmp_path: Path,
) -> None:
    """
    Verify rotating compared photos re-lays out the grid in place.

    Four photos switch from 2x2 to one row once three are vertical. Turning
    panes must update that shape without rebuilding panes, so other panes
    keep their zoom state.
    """
    app, viewer = _show_compare_viewer(tmp_path, [0, 0, 0, 0])
    assert (viewer._rows, viewer._columns) == (2, 2)
    viewers_before = list(viewer._viewers)
    viewer._viewers[3].zoom_to_actual_size((0.2, 0.2))

    for photo_id in ('IMG_R10', 'IMG_R11', 'IMG_R12'):
        viewer.set_photo_rotation(photo_id, 90)

    app.processEvents()

    assert (viewer._rows, viewer._columns) == (1, 4)
    assert viewer._viewers == viewers_before
    assert viewer._viewers[3].is_actual_size_zoom_active() is True
    assert [photo.rotation for photo in viewer._photos] == [90, 90, 90, 0]

    viewer.set_photo_rotation('IMG_R10', 180)
    app.processEvents()

    assert (viewer._rows, viewer._columns) == (2, 2)
    for index, frame in enumerate(viewer._frames):
        position = viewer.grid_layout.getItemPosition(
            viewer.grid_layout.indexOf(frame)
        )
        assert position[:2] == (index // 2, index % 2)

    viewer.close()


def test_compare_photo_viewer_rotation_updates_selected_photo_view(
        tmp_path: Path,
) -> None:
    """
    Verify the one-photo compare view turns with its active photo.

    The selected-photo viewer is separate from the grid panes, so rotating
    the active photo must update it as well.
    """
    _app, viewer = _show_compare_viewer(tmp_path, [0, 0])
    viewer.show_active_photo()

    viewer.set_photo_rotation('IMG_R10', 270)

    assert viewer.selected_viewer.current_rotation() == 270
    assert viewer._viewers[0].current_rotation() == 270
    assert viewer._viewers[1].current_rotation() == 0

    viewer.close()
