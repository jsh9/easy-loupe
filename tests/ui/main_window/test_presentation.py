from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import easy_loupe.ui.main_window.window as main_window_module
from easy_loupe.core.photo_library import PhotoLibrary
from easy_loupe.core.records import SceneGroup
from tests.ui._helpers import (
    create_jpeg,
    create_main_window_with_library,
    stub_read_exif,
    thumbnail_item_widget,
    thumbnail_overlay,
    trigger_viewer_shortcut,
)

if TYPE_CHECKING:
    from pathlib import Path


def _minimap_point(widget: Any, x: float, y: float) -> QPoint:
    target = widget.displayed_image_rect()
    return QPoint(
        int(target.left() + (target.width() * x)),
        int(target.top() + (target.height() * y)),
    )


def _drag_minimap(
        widget: Any, start: tuple[float, float], end: tuple[float, float]
) -> None:
    QTest.mousePress(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        _minimap_point(widget, *start),
    )
    QTest.mouseMove(widget, _minimap_point(widget, *end))
    QTest.mouseRelease(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        _minimap_point(widget, *end),
    )


def _click_thumbnail_image(
        widget: Any,
        point: tuple[float, float],
        modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
) -> None:
    QTest.mouseClick(
        widget,
        Qt.MouseButton.LeftButton,
        modifier,
        _minimap_point(widget, *point),
    )


def _press_drag_thumbnail_image(
        widget: Any,
        start: tuple[float, float],
        end: tuple[float, float] | QPoint,
) -> None:
    """Simulate one held thumbnail press that selects, pans, then releases."""
    QTest.mousePress(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        _minimap_point(widget, *start),
    )
    end_point = (
        end if isinstance(end, QPoint) else _minimap_point(widget, *end)
    )
    QTest.mouseMove(widget, end_point)
    QTest.mouseRelease(
        widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        end_point,
    )


def test_main_window_thumbnail_list_shows_visible_region_for_zoomed_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8080', 'dimgray'), ('IMG_8081', 'blue')],
    )

    assert thumbnail_overlay(window.thumbnail_list, 0) is None
    assert thumbnail_overlay(window.thumbnail_list, 1) is None

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    app.processEvents()

    overlay_before = thumbnail_overlay(window.thumbnail_list, 0)

    assert overlay_before is not None
    assert overlay_before[2] < 1.0
    assert overlay_before[3] < 1.0
    assert thumbnail_overlay(window.thumbnail_list, 1) is None

    trigger_viewer_shortcut(window, 'D')
    app.processEvents()

    overlay_after = thumbnail_overlay(window.thumbnail_list, 0)

    assert overlay_after is not None
    assert overlay_after[0] > overlay_before[0]

    window.close()


def test_thumbnail_image_click_spatially_recenters_new_current_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify zoomed thumbnail-image clicks select and recenter a new photo.

    This covers the manual UX regression: clicking a point on another strip
    thumbnail should inspect that same relative point instead of restoring that
    photo's old remembered center.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8100', 'dimgray'),
            ('IMG_8101', 'blue'),
        ],
    )

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    app.processEvents()

    widget = thumbnail_item_widget(window.thumbnail_list, 1)
    image_widget = widget._front_image_widget
    assert image_widget is not None

    _click_thumbnail_image(image_widget, (0.58, 0.42))
    app.processEvents()

    assert window.current_photo_id == 'IMG_8101'
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        (0.58, 0.42), abs=0.02
    )
    assert thumbnail_overlay(window.thumbnail_list, 1) == pytest.approx(
        window.viewer.visible_region_rect()
    )

    window.close()


def test_thumbnail_image_press_drag_continues_after_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify held thumbnail-image drags keep panning after photo selection.

    Users should be able to press another thumbnail and immediately drag the
    red box without releasing and clicking the newly selected minimap again.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8110', 'dimgray'),
            ('IMG_8111', 'blue'),
        ],
    )

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    app.processEvents()

    widget = thumbnail_item_widget(window.thumbnail_list, 1)
    image_widget = widget._front_image_widget
    assert image_widget is not None

    QTest.mousePress(
        image_widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        _minimap_point(image_widget, 0.5, 0.5),
    )
    app.processEvents()

    assert window.current_photo_id == 'IMG_8111'

    QTest.mouseMove(image_widget, _minimap_point(image_widget, 0.58, 0.42))
    app.processEvents()
    QTest.mouseRelease(
        image_widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        _minimap_point(image_widget, 0.58, 0.42),
    )

    assert window.viewer.normalized_viewport_center() == pytest.approx(
        (0.58, 0.42), abs=0.02
    )

    window.close()


def test_thumbnail_image_press_drag_clamps_zoomed_view_to_image_edge(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify held thumbnail-image drags clamp to the thumbnail image edge.

    Dragging outside the pressed thumbnail should pin the newly selected zoomed
    view to the corresponding photo edge instead of drifting beyond it.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8112', 'dimgray'),
            ('IMG_8113', 'blue'),
        ],
    )

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    app.processEvents()

    widget = thumbnail_item_widget(window.thumbnail_list, 1)
    image_widget = widget._front_image_widget
    assert image_widget is not None

    _press_drag_thumbnail_image(image_widget, (0.5, 0.5), QPoint(-20, -20))
    app.processEvents()

    visible_region = window.viewer.visible_region_rect()

    assert window.current_photo_id == 'IMG_8113'
    assert visible_region is not None
    assert visible_region[0] == pytest.approx(0.0)
    assert visible_region[1] == pytest.approx(0.0)

    window.close()


def test_scene_thumbnail_image_click_spatially_recenters_exact_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify scene-strip image clicks spatially select exact scene photos.

    Scene stacks in the left strip may represent multiple photos, so non-cover
    photos need the horizontal strip path to carry the clicked inspection
    point.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8102', 'dimgray'),
            ('IMG_8103', 'green'),
            ('IMG_8104', 'blue'),
        ],
        scene_groups=[['IMG_8102', 'IMG_8103'], ['IMG_8104']],
    )

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    app.processEvents()

    widget = thumbnail_item_widget(window.scene_list, 1)
    image_widget = widget._front_image_widget
    assert image_widget is not None

    _click_thumbnail_image(image_widget, (0.58, 0.42))
    app.processEvents()

    assert window.current_photo_id == 'IMG_8103'
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        (0.58, 0.42), abs=0.02
    )
    assert thumbnail_overlay(window.scene_list, 1) == pytest.approx(
        window.viewer.visible_region_rect()
    )

    window.close()


def test_scene_thumbnail_image_press_drag_continues_after_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify held scene-strip thumbnail drags keep panning exact photos.

    Scene mode uses horizontal exact-photo thumbnails for non-cover photos, so
    that path needs the same no-release spatial drag behavior.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8114', 'dimgray'),
            ('IMG_8115', 'green'),
            ('IMG_8116', 'blue'),
        ],
        scene_groups=[['IMG_8114', 'IMG_8115'], ['IMG_8116']],
    )

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    app.processEvents()

    widget = thumbnail_item_widget(window.scene_list, 1)
    image_widget = widget._front_image_widget
    assert image_widget is not None

    QTest.mousePress(
        image_widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        _minimap_point(image_widget, 0.5, 0.5),
    )
    app.processEvents()

    assert window.current_photo_id == 'IMG_8115'

    QTest.mouseMove(image_widget, _minimap_point(image_widget, 0.58, 0.42))
    app.processEvents()
    QTest.mouseRelease(
        image_widget,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        _minimap_point(image_widget, 0.58, 0.42),
    )

    assert window.viewer.normalized_viewport_center() == pytest.approx(
        (0.58, 0.42), abs=0.02
    )

    window.close()


def test_spatial_thumbnail_clicks_ignore_browse_mode_and_stale_navigation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify spatial click centers apply only to matching strip selections.

    Browse thumbnails and stale pending clicks must not rewrite zoom centers
    during hidden-viewer, keyboard, or programmatic navigation flows.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8105', 'dimgray'),
            ('IMG_8106', 'green'),
            ('IMG_8107', 'blue'),
        ],
    )

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    app.processEvents()
    center_before = window.viewer.normalized_viewport_center()

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()
    widget = thumbnail_item_widget(window.browse_list, 1)
    image_widget = widget._front_image_widget
    assert image_widget is not None

    _press_drag_thumbnail_image(image_widget, (0.5, 0.5), (0.58, 0.42))
    app.processEvents()

    assert window._pending_thumbnail_click_center is None
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        center_before
    )

    window.space_shortcut.activated.emit()
    window.space_shortcut.activated.emit()
    app.processEvents()
    window._handle_thumbnail_image_clicked(
        window.thumbnail_list, 'IMG_8106', 0.58, 0.42
    )
    window.thumbnail_list.setCurrentRow(2)
    app.processEvents()

    assert window.current_photo_id == 'IMG_8107'
    assert window._pending_thumbnail_click_center is None
    assert window.viewer.normalized_viewport_center() != pytest.approx(
        (0.58, 0.42), abs=0.02
    )

    window.close()


def test_main_window_minimap_drag_recenters_zoomed_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify the active strip minimap is a direct pan control.

    The thumbnail widget emits normalized image coordinates while MainWindow
    policy ensures only the active overlay owner moves the viewer.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8090', 'dimgray'), ('IMG_8091', 'blue')],
    )

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    app.processEvents()

    widget = thumbnail_item_widget(window.thumbnail_list, 0)
    minimap = widget._front_image_widget
    assert minimap is not None

    _drag_minimap(minimap, (0.5, 0.5), (0.58, 0.42))
    app.processEvents()

    assert window.viewer.normalized_viewport_center() == pytest.approx(
        (0.58, 0.42), abs=0.02
    )
    assert thumbnail_overlay(window.thumbnail_list, 0) == pytest.approx(
        window.viewer.visible_region_rect()
    )

    window.close()


def test_scene_strip_minimap_controls_exact_current_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify scene-mode minimap input uses the horizontal exact-photo owner.

    Non-cover photos do not own the vertical scene-stack minimap, so their
    interactive overlay belongs to the scene strip.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8092', 'dimgray'),
            ('IMG_8093', 'green'),
            ('IMG_8094', 'blue'),
        ],
        scene_groups=[['IMG_8092', 'IMG_8093'], ['IMG_8094']],
    )

    window.scene_list.setCurrentRow(1)
    app.processEvents()
    assert window.current_photo_id == 'IMG_8093'

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    app.processEvents()

    scene_widget = thumbnail_item_widget(window.scene_list, 1)
    scene_minimap = scene_widget._front_image_widget
    assert scene_minimap is not None

    _drag_minimap(scene_minimap, (0.5, 0.5), (0.58, 0.35))
    app.processEvents()

    assert thumbnail_overlay(window.thumbnail_list, 0) is None
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        (0.58, 0.35), abs=0.02
    )
    assert thumbnail_overlay(window.scene_list, 1) == pytest.approx(
        window.viewer.visible_region_rect()
    )

    window.close()


def test_non_owner_and_inactive_minimap_requests_do_not_move_viewer(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify stale or inactive minimap signals cannot pan the active viewer.

    The widgets are generic coordinate emitters; window policy must still
    reject non-owner, browse-mode, and compare-mode requests.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8095', 'dimgray'),
            ('IMG_8096', 'green'),
            ('IMG_8097', 'blue'),
        ],
    )

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    app.processEvents()
    center_before = window.viewer.normalized_viewport_center()

    window._handle_minimap_center_requested(
        window.thumbnail_list, 'IMG_8096', 0.65, 0.35
    )
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        center_before
    )

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()
    window._handle_minimap_center_requested(
        window.thumbnail_list, 'IMG_8095', 0.65, 0.35
    )
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        center_before
    )

    window.space_shortcut.activated.emit()
    app.processEvents()
    window.space_shortcut.activated.emit()
    app.processEvents()
    window.thumbnail_list.item(0).setSelected(True)
    window.thumbnail_list.item(1).setSelected(True)
    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    window._handle_minimap_center_requested(
        window.thumbnail_list, 'IMG_8095', 0.65, 0.35
    )
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        center_before
    )

    window.close()


def test_current_thumbnail_has_visible_border_without_resizing_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify the current thumbnail gets a border while other rows reserve space.

    Multi-selected thumbnails already use a shaded background. The extra border
    identifies the current photo, and a transparent border on inactive rows
    prevents layout shifts as the current item changes.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8330', 'dimgray'), ('IMG_8331', 'blue')],
    )

    current_widget = thumbnail_item_widget(window.thumbnail_list, 0)
    inactive_widget = thumbnail_item_widget(window.thumbnail_list, 1)

    assert (
        f'border: 3px solid {window.current_theme.current_border_color}'
        in (current_widget.styleSheet())
    )
    assert 'border: 3px solid transparent' in inactive_widget.styleSheet()

    window.thumbnail_list.setCurrentRow(1)
    app.processEvents()

    assert 'border: 3px solid transparent' in current_widget.styleSheet()
    assert (
        f'border: 3px solid {window.current_theme.current_border_color}'
        in (inactive_widget.styleSheet())
    )

    window.close()


def test_main_window_scene_mode_shows_visible_region_on_both_strips(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify scene-mode minimap overlays update for scene covers.

    The vertical strip displays the scene cover, so it should show the overlay
    only when the current photo is also that cover.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8175', 'dimgray'),
            ('IMG_8176', 'green'),
            ('IMG_8177', 'blue'),
        ],
        scene_groups=[['IMG_8175', 'IMG_8176'], ['IMG_8177']],
    )

    assert window.thumbnail_list.count() == 2
    assert window.scene_list.count() == 2

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    app.processEvents()

    left_overlay_before = thumbnail_overlay(window.thumbnail_list, 0)
    scene_overlay_before = thumbnail_overlay(window.scene_list, 0)

    assert left_overlay_before is not None
    assert scene_overlay_before is not None
    assert thumbnail_overlay(window.thumbnail_list, 1) is None
    assert thumbnail_overlay(window.scene_list, 1) is None

    trigger_viewer_shortcut(window, 'D')
    app.processEvents()

    left_overlay_after = thumbnail_overlay(window.thumbnail_list, 0)
    scene_overlay_after = thumbnail_overlay(window.scene_list, 0)

    assert left_overlay_after is not None
    assert left_overlay_after[0] > left_overlay_before[0]
    assert scene_overlay_after is not None
    assert scene_overlay_after[0] > scene_overlay_before[0]
    assert thumbnail_overlay(window.thumbnail_list, 1) is None
    assert thumbnail_overlay(window.scene_list, 1) is None

    window.close()


def test_scene_mode_visible_region_overlay_hides_vertical_strip_for_non_cover_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify non-cover scene photos do not paint over the scene-cover thumbnail.

    The horizontal strip shows exact photos. The vertical strip shows the scene
    cover, so painting IMG_8176's visible region on IMG_8175 would be wrong.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8175', 'dimgray'),
            ('IMG_8176', 'green'),
            ('IMG_8177', 'blue'),
        ],
        scene_groups=[['IMG_8175', 'IMG_8176'], ['IMG_8177']],
    )

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    app.processEvents()

    cover_overlay = window.viewer.visible_region_rect()

    assert cover_overlay is not None
    assert thumbnail_overlay(window.thumbnail_list, 0) == pytest.approx(
        cover_overlay
    )
    assert thumbnail_overlay(window.scene_list, 0) == pytest.approx(
        cover_overlay
    )

    window.scene_list.setCurrentRow(1)
    app.processEvents()

    non_cover_overlay = window.viewer.visible_region_rect()

    assert window.current_photo_id == 'IMG_8176'
    assert non_cover_overlay is not None
    assert thumbnail_overlay(window.thumbnail_list, 0) is None
    assert thumbnail_overlay(window.scene_list, 0) is None
    assert thumbnail_overlay(window.scene_list, 1) == pytest.approx(
        non_cover_overlay
    )

    window.scene_list.setCurrentRow(0)
    app.processEvents()

    restored_cover_overlay = window.viewer.visible_region_rect()

    assert window.current_photo_id == 'IMG_8175'
    assert restored_cover_overlay is not None
    assert thumbnail_overlay(window.thumbnail_list, 0) == pytest.approx(
        restored_cover_overlay
    )
    assert thumbnail_overlay(window.scene_list, 0) == pytest.approx(
        restored_cover_overlay
    )
    assert thumbnail_overlay(window.scene_list, 1) is None

    window.close()


def test_scene_mode_visible_region_overlay_survives_vertical_navigation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify minimap overlays survive moving between scene stacks.

    A user can press Space to zoom into IMG_8180, then move down in the
    vertical strip to the IMG_8182/IMG_8183 scene. The red visible-region boxes
    should move to the new vertical stack and exact horizontal photo
    immediately, without needing another Space, +, or - press.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8180', 'dimgray'),
            ('IMG_8181', 'green'),
            ('IMG_8182', 'blue'),
            ('IMG_8183', 'purple'),
        ],
        scene_groups=[
            ['IMG_8180', 'IMG_8181'],
            ['IMG_8182', 'IMG_8183'],
        ],
    )

    assert window.thumbnail_list.count() == 2
    assert window.scene_list.count() == 2

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    app.processEvents()

    window.thumbnail_list.setCurrentRow(1)
    app.processEvents()

    visible_region = window.viewer.visible_region_rect()

    assert window.current_photo_id == 'IMG_8182'
    assert visible_region is not None
    assert window.scene_list.count() == 2
    assert window.scene_list.currentRow() == 0
    assert thumbnail_overlay(window.scene_list, 0) == pytest.approx(
        visible_region
    )
    assert thumbnail_overlay(window.thumbnail_list, 0) is None
    assert thumbnail_overlay(window.thumbnail_list, 1) == pytest.approx(
        visible_region
    )

    window.close()


def test_populate_scene_list_uses_targeted_visible_region_refresh(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify scene-list rebuilds do not run a full browse-grid overlay pass.

    The scene strip may rebuild during ordinary vertical scene navigation. That
    path only needs to target the current thumbnail and scene-strip rows.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8200', 'dimgray'),
            ('IMG_8201', 'green'),
            ('IMG_8202', 'blue'),
        ],
        scene_groups=[['IMG_8200', 'IMG_8201'], ['IMG_8202']],
    )

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    app.processEvents()

    bulk_overlay_widgets: list[object] = []

    def record_bulk_overlay(
            list_widget: object,
            target_photo_id: object,
            visible_region: object,
    ) -> None:
        del target_photo_id, visible_region
        bulk_overlay_widgets.append(list_widget)

    # Treat the full-list overlay helper as a sentinel. Scene-strip rebuilds
    # should use cached overlay owners so moving between scenes does not touch
    # every browse-grid thumbnail.
    monkeypatch.setattr(
        window, '_apply_visible_region_overlay', record_bulk_overlay
    )

    window._populate_scene_list()
    app.processEvents()

    assert window.browse_list not in bulk_overlay_widgets
    assert thumbnail_overlay(window.thumbnail_list, 0) is not None
    assert thumbnail_overlay(window.scene_list, 0) is not None

    window.close()


def test_scene_mode_visible_region_overlay_moves_to_vertical_strip_when_scenes_clear(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify clearing scenes does not lose the zoom minimap overlay.

    Removing scene mode rebuilds both thumbnail strips. This guards the subtle
    Qt timing path where stale scene-list selection signals could change the
    current photo before the overlay is reassigned to the vertical strip.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8195', 'dimgray'), ('IMG_8196', 'blue')],
        scene_groups=[['IMG_8195', 'IMG_8196']],
    )

    assert window.thumbnail_list.count() == 1
    assert window.scene_list.count() == 2

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    app.processEvents()

    visible_region = window.viewer.visible_region_rect()

    assert visible_region is not None
    assert thumbnail_overlay(window.thumbnail_list, 0) == pytest.approx(
        visible_region
    )
    assert thumbnail_overlay(window.scene_list, 0) == pytest.approx(
        visible_region
    )

    window.library.set_scene_group_photo_ids([], scene_source=None)
    window._after_scene_change(selected_photo_ids=['IMG_8195'])
    app.processEvents()

    assert window.library.scene_detection_done is False
    assert window.scene_list.count() == 0
    assert window.scene_list.isVisible() is False
    assert window.thumbnail_list.count() == 2
    assert thumbnail_overlay(window.thumbnail_list, 0) == pytest.approx(
        window.viewer.visible_region_rect()
    )
    assert thumbnail_overlay(window.thumbnail_list, 1) is None

    window.close()


def test_main_window_visible_region_overlay_clears_in_fit_and_browse_and_tracks_split_view(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8190', 'dimgray'), ('IMG_8191', 'green')],
    )

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    window.viewer.pan_by(35, -20)
    app.processEvents()

    overlay_before_browse = thumbnail_overlay(window.thumbnail_list, 0)

    assert overlay_before_browse is not None

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()

    assert thumbnail_overlay(window.thumbnail_list, 0) is None

    window.space_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer._mode == 'single-fit'
    assert thumbnail_overlay(window.thumbnail_list, 0) is None

    window.space_shortcut.activated.emit()
    app.processEvents()

    overlay_after_restore = thumbnail_overlay(window.thumbnail_list, 0)

    assert overlay_after_restore == pytest.approx(overlay_before_browse)

    window.split_mode_shortcut.activated.emit()
    app.processEvents()

    overlay_in_split_before = thumbnail_overlay(window.thumbnail_list, 0)

    assert overlay_in_split_before is not None
    assert overlay_in_split_before == pytest.approx(
        window.viewer.visible_region_rect()
    )

    trigger_viewer_shortcut(window, 'D')
    app.processEvents()

    overlay_in_split_after = thumbnail_overlay(window.thumbnail_list, 0)

    assert overlay_in_split_after is not None
    assert overlay_in_split_after[0] > overlay_in_split_before[0]

    window.split_mode_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer.is_split_view() is False
    assert thumbnail_overlay(window.thumbnail_list, 0) == pytest.approx(
        window.viewer.visible_region_rect()
    )

    window.close()


def test_main_window_scene_stack_shows_range_badge_and_rejected_state(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7700', 'dimgray'),
            ('IMG_7701', 'green'),
            ('IMG_7702', 'blue'),
        ],
        scene_groups=[['IMG_7700', 'IMG_7701'], ['IMG_7702']],
    )

    window.library.get_photo('IMG_7700').flag = 'rejected'
    window.library.get_photo('IMG_7701').flag = 'rejected'
    window._populate_thumbnail_list()
    window._refresh_ui()
    app.processEvents()

    widget = thumbnail_item_widget(window.thumbnail_list, 0)
    item = window.thumbnail_list.item(0)

    assert widget.name_label.text() == 'IMG_7700...IMG_7701'
    assert widget.meta_label.isVisible() is False
    assert widget._badge is not None
    assert widget._badge.text() == '2'
    assert item.data(theme_module.SCENE_COUNT_ROLE) == 2
    assert item.data(theme_module.FLAG_ROLE) == 'rejected'
    assert widget._front_image_widget is not None
    assert widget._front_image_widget.graphicsEffect() is not None

    window.close()


def test_scene_display_name_handles_single_and_empty_scenes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'IMG_9090.JPG', 'green')
    stub_read_exif(monkeypatch, {})

    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    window.library = library

    empty_scene = SceneGroup(scene_id='empty', photo_ids=[])
    assert window._scene_display_name(empty_scene) == ''

    single_scene = SceneGroup(scene_id='single', photo_ids=['IMG_9090'])
    assert window._scene_display_name(single_scene) == 'IMG_9090'

    window.close()
    del app
