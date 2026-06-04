from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
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


def test_main_window_scene_mode_shows_visible_region_on_horizontal_strip_only(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    left_overlay = thumbnail_overlay(window.thumbnail_list, 0)
    scene_overlay_before = thumbnail_overlay(window.scene_list, 0)

    assert left_overlay is None
    assert scene_overlay_before is not None

    trigger_viewer_shortcut(window, 'D')
    app.processEvents()

    scene_overlay_after = thumbnail_overlay(window.scene_list, 0)

    assert scene_overlay_after is not None
    assert scene_overlay_after[0] > scene_overlay_before[0]
    assert thumbnail_overlay(window.thumbnail_list, 0) is None

    window.close()


def test_scene_mode_visible_region_overlay_survives_vertical_navigation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify the minimap box appears after moving between scene stacks.

    A user can press Space to zoom into IMG_8180, then move down in the
    vertical strip to the IMG_8182/IMG_8183 scene. The red visible-region box
    should show on IMG_8182 in the horizontal strip immediately, without
    needing another Space, +, or - press.
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
