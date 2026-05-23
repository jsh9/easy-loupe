from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from easy_cull.ui.theme import THEMES
from easy_cull.ui.viewers.compare_photo_viewer import (
    ACTIVE_COMPARE_BORDER_WIDTH,
    COMPARE_HELP_TEXT,
    ComparePhoto,
    ComparePhotoViewer,
)
from tests.ui._helpers import create_jpeg

if TYPE_CHECKING:
    from pathlib import Path


def _close_viewer(viewer: ComparePhotoViewer, app: QApplication) -> None:
    viewer.close()
    app.processEvents()


def _assert_frames_fill_grid_area(viewer: ComparePhotoViewer) -> None:
    frames = viewer._frames
    occupied_width = (
        max(frame.geometry().right() for frame in frames)
        - min(frame.geometry().left() for frame in frames)
        + 1
    )
    occupied_height = (
        max(frame.geometry().bottom() for frame in frames)
        - min(frame.geometry().top() for frame in frames)
        + 1
    )
    assert occupied_width == pytest.approx(viewer.grid_widget.width(), abs=2)
    assert occupied_height == pytest.approx(viewer.grid_widget.height(), abs=2)


def _assert_single_row_frames_fill_height(viewer: ComparePhotoViewer) -> None:
    assert viewer._rows == 1
    for frame in viewer._frames:
        assert frame.geometry().height() == pytest.approx(
            viewer.grid_widget.height(), abs=2
        )


@pytest.mark.parametrize(
    ('photo_count', 'vertical_count', 'expected_shape'),
    [
        (2, 0, (1, 2)),
        (3, 3, (1, 3)),
        (4, 0, (2, 2)),
        (4, 2, (2, 2)),
        (4, 3, (1, 4)),
        (4, 4, (1, 4)),
        (5, 5, (2, 3)),
        (6, 0, (2, 3)),
        (7, 7, (2, 4)),
        (8, 0, (2, 4)),
    ],
)
def test_compare_photo_viewer_grid_shape_is_count_based(
        photo_count: int, vertical_count: int, expected_shape: tuple[int, int]
) -> None:
    """
    Verify the hard-coded compare grid decision table.

    These cases document when compare uses a single full-height row versus a
    multi-row grid. The explicit table prevents future layout tweaks from
    reintroducing narrow or partially filled compare panes.
    """
    assert (
        ComparePhotoViewer._grid_shape(photo_count, vertical_count)
        == expected_shape
    )


def test_compare_photo_viewer_locked_and_unlocked_zoom_targets(
        tmp_path: Path,
) -> None:
    """
    Verify locked zoom targets all panes and unlocked zoom targets one.

    Compare mode's core value is synchronized inspection, but users can opt out
    for individual checks. This test protects both interaction modes and the
    active pane selection made by clicking a pane.
    """
    create_jpeg(tmp_path / 'IMG_9000.JPG', 'dimgray')
    create_jpeg(tmp_path / 'IMG_9001.JPG', 'blue')

    app = QApplication.instance() or QApplication([])
    viewer = ComparePhotoViewer()
    viewer.resize(640, 480)
    viewer.show()
    app.processEvents()

    viewer.set_photos([
        ComparePhoto('IMG_9000', tmp_path / 'IMG_9000.JPG', (0.2, 0.8)),
        ComparePhoto('IMG_9001', tmp_path / 'IMG_9001.JPG', (0.7, 0.3)),
    ])
    app.processEvents()

    assert viewer.is_locked_zoom() is True

    viewer.toggle_focus_zoom()

    assert viewer._viewers[0].normalized_viewport_center() == pytest.approx((
        0.2,
        0.8,
    ))
    assert viewer._viewers[1].normalized_viewport_center() == pytest.approx((
        0.7,
        0.3,
    ))

    viewer._handle_viewer_click(0, (0.4, 0.6))

    assert viewer._viewers[0].normalized_viewport_center() == pytest.approx((
        0.4,
        0.6,
    ))
    assert viewer._viewers[1].normalized_viewport_center() == pytest.approx((
        0.4,
        0.6,
    ))

    viewer.lock_zoom_button.setChecked(False)
    first_zoom = viewer._viewers[0].current_zoom_factor()
    second_zoom = viewer._viewers[1].current_zoom_factor()
    viewer._handle_viewer_click(1, (0.8, 0.2))
    viewer.zoom_step(1.25)

    assert viewer._viewers[0].normalized_viewport_center() == pytest.approx((
        0.4,
        0.6,
    ))
    assert viewer._viewers[1].normalized_viewport_center() == pytest.approx((
        0.8,
        0.2,
    ))
    assert viewer._viewers[0].current_zoom_factor() == pytest.approx(
        first_zoom
    )
    assert viewer._viewers[1].current_zoom_factor() > second_zoom

    _close_viewer(viewer, app)


def test_compare_photo_viewer_shows_helper_metadata_and_active_border(
        tmp_path: Path,
) -> None:
    """
    Verify the compare viewer's helper UI, metadata rows, and active border.

    Compare hides the normal metadata strip, so each pane needs its own
    metadata label and a clear active marker for keyboard tagging. This catches
    visual regressions in those compare-only cues.
    """
    create_jpeg(tmp_path / 'IMG_9002.JPG', 'dimgray')
    create_jpeg(tmp_path / 'IMG_9003.JPG', 'blue')

    app = QApplication.instance() or QApplication([])
    viewer = ComparePhotoViewer()
    viewer.resize(640, 480)
    viewer.show()
    app.processEvents()

    viewer.set_photos([
        ComparePhoto(
            'IMG_9002',
            tmp_path / 'IMG_9002.JPG',
            (0.5, 0.5),
            metadata_text='★★★★★',
        ),
        ComparePhoto(
            'IMG_9003',
            tmp_path / 'IMG_9003.JPG',
            (0.5, 0.5),
            metadata_text='✅',
        ),
    ])
    app.processEvents()

    assert viewer.help_label.text() == COMPARE_HELP_TEXT
    assert viewer._metadata_labels[0].text() == '★★★★★'
    assert viewer._metadata_labels[1].text() == '✅'
    assert f'border: {ACTIVE_COMPARE_BORDER_WIDTH}px' in (
        viewer._frames[0].styleSheet()
    )
    assert f'border: {ACTIVE_COMPARE_BORDER_WIDTH}px' in (
        viewer._frames[1].styleSheet()
    )
    assert viewer._theme.selected_background in viewer._frames[0].styleSheet()
    assert viewer._theme.button_border in viewer._frames[1].styleSheet()

    viewer.lock_zoom_button.setChecked(True)
    assert f'border: {ACTIVE_COMPARE_BORDER_WIDTH}px' in (
        viewer._frames[0].styleSheet()
    )

    viewer.move_active_selection(0, 1)
    assert f'border: {ACTIVE_COMPARE_BORDER_WIDTH}px' in (
        viewer._frames[0].styleSheet()
    )
    assert f'border: {ACTIVE_COMPARE_BORDER_WIDTH}px' in (
        viewer._frames[1].styleSheet()
    )
    assert viewer._theme.button_border in viewer._frames[0].styleSheet()
    assert viewer._theme.selected_background in viewer._frames[1].styleSheet()

    _close_viewer(viewer, app)


def test_compare_photo_viewer_styles_metadata_labels_created_after_theme_change(
        tmp_path: Path,
) -> None:
    """
    Verify compare metadata labels inherit a preselected theme.

    This makes sure that if the app theme was changed before entering Compare
    mode, the metadata labels (such as ★ & ☆) created for the new compare panes
    are consistent with the active theme. Otherwise, users would see dark stars
    on a dark background or light stars on a light background.
    """
    create_jpeg(tmp_path / 'IMG_9004.JPG', 'dimgray')
    create_jpeg(tmp_path / 'IMG_9005.JPG', 'blue')

    app = QApplication.instance() or QApplication([])
    viewer = ComparePhotoViewer()
    viewer.set_theme(THEMES['dark'])
    viewer.set_photos([
        ComparePhoto('IMG_9004', tmp_path / 'IMG_9004.JPG', (0.5, 0.5)),
        ComparePhoto('IMG_9005', tmp_path / 'IMG_9005.JPG', (0.5, 0.5)),
    ])
    app.processEvents()

    assert all(
        THEMES['dark'].meta_color in label.styleSheet()
        for label in viewer._metadata_labels
    )

    _close_viewer(viewer, app)


def test_compare_photo_viewer_left_drag_pans_locked_and_unlocked_targets(
        tmp_path: Path,
) -> None:
    """
    Verify mouse drag panning follows locked and unlocked targeting.

    Click-to-recenter and drag-to-pan share mouse input. This test ensures a
    drag pans all panes while locked and only the active pane when unlocked.
    """
    create_jpeg(tmp_path / 'IMG_9010.JPG', 'dimgray')
    create_jpeg(tmp_path / 'IMG_9011.JPG', 'blue')

    app = QApplication.instance() or QApplication([])
    viewer = ComparePhotoViewer()
    viewer.resize(640, 480)
    viewer.show()
    app.processEvents()
    viewer.set_photos([
        ComparePhoto('IMG_9010', tmp_path / 'IMG_9010.JPG', (0.5, 0.5)),
        ComparePhoto('IMG_9011', tmp_path / 'IMG_9011.JPG', (0.5, 0.5)),
    ])
    app.processEvents()
    viewer.toggle_focus_zoom()
    first_center_before = viewer._viewers[0].normalized_viewport_center()
    second_center_before = viewer._viewers[1].normalized_viewport_center()

    QTest.mousePress(
        viewer._viewers[0].viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(160, 120),
    )
    QTest.mouseMove(viewer._viewers[0].viewport(), QPoint(120, 120))
    QTest.mouseRelease(
        viewer._viewers[0].viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(120, 120),
    )
    app.processEvents()

    assert (
        viewer._viewers[0].normalized_viewport_center()[0]
        > (first_center_before[0])
    )
    assert (
        viewer._viewers[1].normalized_viewport_center()[0]
        > (second_center_before[0])
    )

    viewer.lock_zoom_button.setChecked(False)
    first_center_before = viewer._viewers[0].normalized_viewport_center()
    second_center_before = viewer._viewers[1].normalized_viewport_center()

    QTest.mousePress(
        viewer._viewers[1].viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(160, 120),
    )
    QTest.mouseMove(viewer._viewers[1].viewport(), QPoint(120, 120))
    QTest.mouseRelease(
        viewer._viewers[1].viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(120, 120),
    )
    app.processEvents()

    assert viewer._viewers[0].normalized_viewport_center() == pytest.approx(
        first_center_before
    )
    assert (
        viewer._viewers[1].normalized_viewport_center()[0]
        > (second_center_before[0])
    )

    _close_viewer(viewer, app)


def test_compare_photo_viewer_two_photos_fill_single_row(
        tmp_path: Path,
) -> None:
    """
    Verify two compared photos fill one full-height row.

    Two-photo compare is a common workflow and should use all available compare
    space. This prevents layouts where panes cluster into a small part of the
    viewer.
    """
    create_jpeg(
        tmp_path / 'IMG_9020.JPG',
        'dimgray',
        size=(720, 480),
    )
    create_jpeg(tmp_path / 'IMG_9021.JPG', 'blue', size=(480, 720))

    app = QApplication.instance() or QApplication([])
    viewer = ComparePhotoViewer()
    viewer.resize(1000, 520)
    viewer.show()
    app.processEvents()
    viewer.set_photos([
        ComparePhoto('IMG_9020', tmp_path / 'IMG_9020.JPG', (0.5, 0.5)),
        ComparePhoto('IMG_9021', tmp_path / 'IMG_9021.JPG', (0.5, 0.5)),
    ])
    app.processEvents()
    app.processEvents()

    assert (viewer._rows, viewer._columns) == (1, 2)
    _assert_frames_fill_grid_area(viewer)
    _assert_single_row_frames_fill_height(viewer)
    assert viewer._frames[0].geometry().width() == pytest.approx(
        viewer._frames[1].geometry().width(), abs=2
    )

    _close_viewer(viewer, app)


def test_compare_photo_viewer_three_photos_fill_single_row(
        tmp_path: Path,
) -> None:
    """
    Verify three compared photos fill one full-height row.

    Three-photo compare is intentionally horizontal regardless of orientation,
    so each pane should stretch top-to-bottom across the full compare grid.
    """
    create_jpeg(
        tmp_path / 'IMG_9023.JPG',
        'dimgray',
        size=(480, 720),
    )
    create_jpeg(tmp_path / 'IMG_9024.JPG', 'blue', size=(480, 720))
    create_jpeg(tmp_path / 'IMG_9025.JPG', 'green', size=(720, 480))

    app = QApplication.instance() or QApplication([])
    viewer = ComparePhotoViewer()
    viewer.resize(1200, 520)
    viewer.show()
    app.processEvents()
    viewer.set_photos([
        ComparePhoto('IMG_9023', tmp_path / 'IMG_9023.JPG', (0.5, 0.5)),
        ComparePhoto('IMG_9024', tmp_path / 'IMG_9024.JPG', (0.5, 0.5)),
        ComparePhoto('IMG_9025', tmp_path / 'IMG_9025.JPG', (0.5, 0.5)),
    ])
    app.processEvents()
    app.processEvents()

    assert (viewer._rows, viewer._columns) == (1, 3)
    _assert_frames_fill_grid_area(viewer)
    _assert_single_row_frames_fill_height(viewer)

    _close_viewer(viewer, app)


def test_compare_photo_viewer_four_vertical_photos_fill_single_row(
        tmp_path: Path,
) -> None:
    """
    Verify four vertical photos use a single full-height row.

    A 2x2 grid wastes space for portrait-heavy selections. This locks in the
    special four-portrait layout requested for better side-by-side comparison.
    """
    for index in range(4):
        create_jpeg(
            tmp_path / f'IMG_902{index + 6}.JPG',
            'dimgray',
            size=(480, 720),
        )

    app = QApplication.instance() or QApplication([])
    viewer = ComparePhotoViewer()
    viewer.resize(1200, 520)
    viewer.show()
    app.processEvents()
    viewer.set_photos([
        ComparePhoto(
            f'IMG_902{index + 6}',
            tmp_path / f'IMG_902{index + 6}.JPG',
            (0.5, 0.5),
        )
        for index in range(4)
    ])
    app.processEvents()
    app.processEvents()

    assert (viewer._rows, viewer._columns) == (1, 4)
    _assert_frames_fill_grid_area(viewer)
    _assert_single_row_frames_fill_height(viewer)

    _close_viewer(viewer, app)


def test_compare_photo_viewer_four_photos_with_three_vertical_fill_single_row(
        tmp_path: Path,
) -> None:
    """
    Verify four photos with three vertical images use one row.

    This is the threshold case for portrait-majority four-photo compare. It is
    necessary because one landscape image should not force the whole set into a
    2x2 grid.
    """
    sizes = [(480, 720), (480, 720), (480, 720), (720, 480)]
    for index, size in enumerate(sizes):
        create_jpeg(
            tmp_path / f'IMG_903{index}.JPG',
            'dimgray',
            size=size,
        )

    app = QApplication.instance() or QApplication([])
    viewer = ComparePhotoViewer()
    viewer.resize(1200, 520)
    viewer.show()
    app.processEvents()
    viewer.set_photos([
        ComparePhoto(
            f'IMG_903{index}',
            tmp_path / f'IMG_903{index}.JPG',
            (0.5, 0.5),
        )
        for index in range(4)
    ])
    app.processEvents()
    app.processEvents()

    assert (viewer._rows, viewer._columns) == (1, 4)
    _assert_frames_fill_grid_area(viewer)
    _assert_single_row_frames_fill_height(viewer)

    _close_viewer(viewer, app)


def test_compare_photo_viewer_four_photos_with_two_vertical_use_two_by_two(
        tmp_path: Path,
) -> None:
    """
    Verify four photos with only two vertical images use the 2x2 grid.

    The portrait-majority exception should not apply to balanced or landscape-
    heavy sets. This keeps ordinary four-photo compare dense in both axes.
    """
    sizes = [(480, 720), (480, 720), (720, 480), (720, 480)]
    for index, size in enumerate(sizes):
        create_jpeg(
            tmp_path / f'IMG_904{index}.JPG',
            'dimgray',
            size=size,
        )

    app = QApplication.instance() or QApplication([])
    viewer = ComparePhotoViewer()
    viewer.resize(1000, 520)
    viewer.show()
    app.processEvents()
    viewer.set_photos([
        ComparePhoto(
            f'IMG_904{index}',
            tmp_path / f'IMG_904{index}.JPG',
            (0.5, 0.5),
        )
        for index in range(4)
    ])
    app.processEvents()
    app.processEvents()

    assert (viewer._rows, viewer._columns) == (2, 2)
    _assert_frames_fill_grid_area(viewer)

    _close_viewer(viewer, app)


def test_compare_photo_viewer_square_photos_count_as_non_vertical_for_four(
        tmp_path: Path,
) -> None:
    """
    Verify square images do not count as vertical for layout selection.

    Squares should behave like horizontal images for the four-photo threshold;
    otherwise mixed square/portrait selections would unexpectedly switch to the
    one-row layout.
    """
    sizes = [(480, 720), (480, 720), (600, 600), (600, 600)]
    for index, size in enumerate(sizes):
        create_jpeg(
            tmp_path / f'IMG_905{index}.JPG',
            'dimgray',
            size=size,
        )

    app = QApplication.instance() or QApplication([])
    viewer = ComparePhotoViewer()
    viewer.resize(1000, 520)
    viewer.show()
    app.processEvents()
    viewer.set_photos([
        ComparePhoto(
            f'IMG_905{index}',
            tmp_path / f'IMG_905{index}.JPG',
            (0.5, 0.5),
        )
        for index in range(4)
    ])
    app.processEvents()
    app.processEvents()

    assert (viewer._rows, viewer._columns) == (2, 2)
    _assert_frames_fill_grid_area(viewer)

    _close_viewer(viewer, app)


@pytest.mark.parametrize(
    ('photo_count', 'expected_shape'),
    [
        (5, (2, 3)),
        (6, (2, 3)),
        (7, (2, 4)),
        (8, (2, 4)),
    ],
)
def test_compare_photo_viewer_large_counts_use_fixed_grid(
        tmp_path: Path, photo_count: int, expected_shape: tuple[int, int]
) -> None:
    """
    Verify 5-8 photo compares use fixed multi-row grids.

    Larger compare sets should prioritize a predictable full-area grid over
    orientation-specific layouts. This test documents the stable 2x3 and 2x4
    arrangements.
    """
    for index in range(photo_count):
        create_jpeg(
            tmp_path / f'IMG_906{index}.JPG',
            'dimgray',
            size=(480, 720),
        )

    app = QApplication.instance() or QApplication([])
    viewer = ComparePhotoViewer()
    viewer.resize(1200, 680)
    viewer.show()
    app.processEvents()
    viewer.set_photos([
        ComparePhoto(
            f'IMG_906{index}',
            tmp_path / f'IMG_906{index}.JPG',
            (0.5, 0.5),
        )
        for index in range(photo_count)
    ])
    app.processEvents()
    app.processEvents()

    assert (viewer._rows, viewer._columns) == expected_shape
    _assert_frames_fill_grid_area(viewer)

    _close_viewer(viewer, app)
