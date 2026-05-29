from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QMessageBox

import easy_cull.ui.identity as identity_module
import easy_cull.ui.main_window.build as build_module
import easy_cull.ui.main_window.window as main_window_module
import easy_cull.ui.theme as theme_module
from easy_cull.core.folder_loading import (
    PHOTO_SORT_MODE_CAPTURE_TIME,
    PHOTO_SORT_MODE_FILENAME,
    normalize_sort_reversed,
)
from easy_cull.core.photo_library import PhotoLibrary
from easy_cull.ui.viewers.compare_photo_viewer import (
    COMPARE_PHOTO_LIMIT_OPTIONS,
    DEFAULT_COMPARE_PHOTO_LIMIT,
)
from easy_cull.ui.viewers.exif_overlay import HISTOGRAM_HEIGHT
from tests.ui._helpers import (
    create_jpeg,
    create_main_window_with_library,
    stub_read_exif,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def assert_default_photo_sort_control(window: Any) -> None:
    menu_titles = [action.text() for action in window.menuBar().actions()]
    assert '&View' not in menu_titles
    assert not hasattr(window, 'view_menu')
    assert not hasattr(window, 'photo_sort_actions')
    assert window.photo_sort_group.objectName() == 'photoSortGroup'
    assert window.sort_label.parentWidget() is window.photo_sort_group
    assert window.photo_sort_segment.parentWidget() is window.photo_sort_group
    assert (
        window.photo_sort_reverse_checkbox.parentWidget()
        is window.photo_sort_group
    )
    assert window.sort_label.text() == 'Sort by:'
    assert window.photo_sort_segment.objectName() == 'photoSortSegment'
    assert window.photo_sort_buttons[PHOTO_SORT_MODE_FILENAME].text() == (
        'File Name'
    )
    assert (
        window.photo_sort_buttons[PHOTO_SORT_MODE_CAPTURE_TIME].text()
        == 'Capture Time'
    )
    assert window.photo_sort_buttons[PHOTO_SORT_MODE_CAPTURE_TIME].isChecked()
    assert not window.photo_sort_buttons[PHOTO_SORT_MODE_FILENAME].isChecked()
    assert (
        window.photo_sort_buttons[PHOTO_SORT_MODE_FILENAME].toolTip()
        == 'Sort photos by file name'
    )
    assert (
        window.photo_sort_buttons[PHOTO_SORT_MODE_CAPTURE_TIME].toolTip()
        == 'Sort photos by EXIF capture time'
    )
    assert window.photo_sort_reverse_checkbox.text() == 'Reverse order'
    assert window.photo_sort_reverse_checkbox.objectName() == (
        'photoSortReverseCheckbox'
    )
    assert not window.photo_sort_reverse_checkbox.isChecked()
    assert window.photo_sort_reverse_checkbox.toolTip() == (
        'Reverse the current sort order'
    )
    assert window.library.sort_mode == PHOTO_SORT_MODE_CAPTURE_TIME
    assert window.library.sort_reversed is False


def _collect_photo_ids_from_list(list_widget: Any) -> list[str]:
    return [
        str(list_widget.item(index).data(Qt.UserRole))
        for index in range(list_widget.count())
    ]


def _collect_selected_photo_ids(list_widget: Any) -> list[str]:
    return [
        str(item.data(Qt.UserRole))
        for item in sorted(list_widget.selectedItems(), key=list_widget.row)
    ]


def _select_photo_ids(
        list_widget: Any, photo_ids: list[str], *, set_current: bool = False
) -> None:
    selected = set(photo_ids)
    list_widget.clearSelection()
    if set_current:
        for index in range(list_widget.count()):
            item = list_widget.item(index)
            assert item is not None
            if str(item.data(Qt.UserRole)) == photo_ids[0]:
                list_widget.setCurrentItem(item)
                break

    for index in range(list_widget.count()):
        item = list_widget.item(index)
        assert item is not None
        photo_id = str(item.data(Qt.UserRole))
        if photo_id in selected:
            item.setSelected(True)


def _create_sorting_window(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, Any, Any]:
    create_jpeg(tmp_path / 'IMG_2402.JPG', 'blue')
    create_jpeg(tmp_path / 'IMG_2400.JPG', 'green')
    create_jpeg(tmp_path / 'IMG_2403.JPG', 'purple')
    create_jpeg(tmp_path / 'IMG_2401.JPG', 'red')
    stub_read_exif(
        monkeypatch,
        {
            'IMG_2402.JPG': {'DateTimeOriginal': '2024:05:01 10:00:00'},
            'IMG_2400.JPG': {'DateTimeOriginal': '2024:05:01 10:00:05'},
            'IMG_2403.JPG': {'DateTimeOriginal': '2024:05:01 10:00:10'},
            'IMG_2401.JPG': {'DateTimeOriginal': '2024:05:01 10:00:15'},
        },
    )

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    library.set_scene_group_photo_ids(
        [['IMG_2402', 'IMG_2401'], ['IMG_2400', 'IMG_2403']],
        scene_source='manual',
    )
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.library = library
    window.current_photo_id = 'IMG_2401'
    window._populate_thumbnail_list()
    window._populate_browse_list()
    window._populate_scene_list()
    window._display_current_photo()
    window._refresh_ui()
    window.show()
    app.processEvents()
    return theme_module, app, window


def test_main_window_registers_open_detect_and_organize_actions() -> None:
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()

    assert window.windowTitle() == 'EasyCull'
    assert not window.windowIcon().isNull()
    assert (
        window.open_action.shortcut().toString(QKeySequence.PortableText)
        == 'Ctrl+O'
    )
    assert (
        window.detect_action.shortcut().toString(QKeySequence.PortableText)
        == 'Ctrl+D'
    )
    assert window.detect_action.isEnabled() is False
    assert (
        window.organize_action.shortcut().toString(QKeySequence.PortableText)
        == 'Ctrl+Shift+E'
    )
    assert window.organize_action.isEnabled() is False
    assert window.history_menu.title() == '&History'
    assert_default_photo_sort_control(window)
    assert window.compare_menu.title() == '&Compare'
    assert window.compare_limit_menu.title() == '&Limit'
    assert list(window.compare_limit_actions) == list(
        COMPARE_PHOTO_LIMIT_OPTIONS
    )
    assert window.compare_limit_actions[
        DEFAULT_COMPARE_PHOTO_LIMIT
    ].isChecked()
    assert window.compare_viewer.photo_limit == DEFAULT_COMPARE_PHOTO_LIMIT
    assert window.scenes_menu.title() == '&Scenes'
    assert (
        window.merge_scene_action.shortcut().toString(
            QKeySequence.PortableText
        )
        == 'Ctrl+Shift+M'
    )
    assert window.merge_scene_action.isEnabled() is False
    assert window.assign_photo_menu.title() == 'Assign to &Photo'
    assert window.help_menu.title() == '&Help'
    assert window.about_action.text() == 'About EasyCull'
    assert window.about_action.menuRole() == QAction.AboutRole
    assert (
        window.rating_actions[1].shortcut().toString(QKeySequence.PortableText)
        == '1'
    )
    assert (
        window.rating_actions[None]
        .shortcut()
        .toString(QKeySequence.PortableText)
        == '0'
    )
    assert (
        window.color_label_actions['red']
        .shortcut()
        .toString(QKeySequence.PortableText)
        == '6'
    )
    assert (
        window.color_label_actions['blue']
        .shortcut()
        .toString(QKeySequence.PortableText)
        == '9'
    )
    assert window.color_label_actions[None].shortcut().isEmpty()
    assert window.color_label_actions[None].text().endswith('\t`')
    assert (
        window.color_label_actions['purple']
        .shortcut()
        .toString(QKeySequence.PortableText)
        == ''
    )
    assert (
        window.flag_actions['picked']
        .shortcut()
        .toString(QKeySequence.PortableText)
        == 'P'
    )
    assert (
        window.flag_actions[None]
        .shortcut()
        .toString(QKeySequence.PortableText)
        == 'U'
    )
    assert (
        window.browse_mode_shortcut.key().toString(QKeySequence.PortableText)
        == 'G'
    )
    assert (
        window.space_shortcut.key().toString(QKeySequence.PortableText)
        == 'Space'
    )
    assert (
        window.split_mode_shortcut.key().toString(QKeySequence.PortableText)
        == '\\'
    )
    assert (
        window.show_af_point_shortcut.key().toString(QKeySequence.PortableText)
        == 'F'
    )
    assert (
        window.info_overlay_shortcut.key().toString(QKeySequence.PortableText)
        == 'I'
    )
    assert (
        window.open_button.toolTip()
        == main_window_module.MainWindow._shortcut_tooltip(
            'Open Folder', 'Ctrl+O'
        )
    )
    assert (
        window.detect_button.toolTip()
        == main_window_module.MainWindow._shortcut_tooltip(
            'Detect Scenes', 'Ctrl+D'
        )
    )
    assert (
        window.organize_button.toolTip()
        == main_window_module.MainWindow._shortcut_tooltip(
            'Organize Photos', 'Ctrl+Shift+E'
        )
    )
    assert window.show_af_point_toggle.text() == 'Show AF point'
    assert window.show_af_point_toggle.isChecked() is True
    assert (
        window.show_af_point_toggle.toolTip()
        == main_window_module.MainWindow._shortcut_tooltip(
            'Show AF point', 'F'
        )
    )
    assert not hasattr(window, 'zoom_to_af_point_toggle')
    assert window.viewer._focus_point_marker_enabled is True
    assert window.viewer.single_viewer._focus_point_marker_enabled is True

    window.show_af_point_toggle.setChecked(False)

    assert window.viewer._focus_point_marker_enabled is False
    assert window.viewer.single_viewer._focus_point_marker_enabled is False
    assert window.viewer.split_fit_viewer._focus_point_marker_enabled is False
    assert window.viewer.split_zoom_viewer._focus_point_marker_enabled is False

    window.show_af_point_shortcut.activated.emit()

    assert window.show_af_point_toggle.isChecked() is True
    assert window.viewer._focus_point_marker_enabled is True
    assert window.viewer.single_viewer._focus_point_marker_enabled is True
    assert window.viewer.split_fit_viewer._focus_point_marker_enabled is True
    assert window.viewer.split_zoom_viewer._focus_point_marker_enabled is True
    assert (
        window.metadata_label.text()
        == f'Metadata: {theme_module.NO_METADATA_TEXT}'
    )

    window.close()
    del app


def test_info_overlay_shortcut_toggles_normal_view_only_overlay(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_2500', 'indianred'), ('IMG_2501', 'steelblue')],
    )
    window.library.get_photo('IMG_2500').exif_display = {
        'Camera Model': 'Z 8',
        'ISO': '800',
    }

    assert window.exif_overlay.isHidden() is True

    window.info_overlay_shortcut.activated.emit()
    app.processEvents()

    assert window._info_overlay_enabled is True
    assert window.exif_overlay.isVisible() is True
    assert window.exif_overlay.exif_display() == {
        'Camera Model': 'Z 8',
        'ISO': '800',
    }
    assert window.exif_overlay.histogram_plot.histogram() is not None

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._browse_mode is True
    assert window._info_overlay_enabled is True
    assert window.exif_overlay.isHidden() is True

    window.space_shortcut.activated.emit()
    app.processEvents()

    assert window._browse_mode is False
    assert window.exif_overlay.isVisible() is True

    for row in range(window.thumbnail_list.count()):
        item = window.thumbnail_list.item(row)
        assert item is not None
        item.setSelected(True)

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.exif_overlay.isHidden() is True

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is False
    assert window.exif_overlay.isVisible() is True

    window.info_overlay_shortcut.activated.emit()
    app.processEvents()

    assert window._info_overlay_enabled is False
    assert window.exif_overlay.isHidden() is True

    window.close()


def test_info_overlay_stays_readable_after_folder_rebuild(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_2600', 'indianred'), ('IMG_2601', 'steelblue')],
    )
    window.library.get_photo('IMG_2600').exif_display = {
        'Camera Model': 'Z 8',
        'Lens Model': 'NIKKOR Z 50mm f/1.8 S',
        'Focal Length': '50\u00a0mm',
        'Aperture': '\u0192/2.8',
        'Shutter Speed': '1/250\u00a0s',
        'ISO': '800',
        'GPS': '40.712776º, -74.005974º, 12.4\u00a0m',
    }
    window.info_overlay_shortcut.activated.emit()
    app.processEvents()
    assert window.exif_overlay.isVisible() is True

    next_folder = tmp_path / 'next'
    next_folder.mkdir()
    create_jpeg(next_folder / 'IMG_2700.JPG', 'seagreen')
    create_jpeg(next_folder / 'IMG_2701.JPG', 'mediumpurple')
    window._show_progress('Scanning folder', 0)
    window.library.load_folder(next_folder)
    window.library.get_photo('IMG_2700').exif_display = {
        'Camera Model': 'EOS R5',
        'Lens Model': 'RF 50mm F1.2L USM',
        'Focal Length': '50\u00a0mm',
        'Aperture': '\u0192/1.2',
        'Shutter Speed': '1/500\u00a0s',
        'ISO': '100',
        'GPS': '34.052235º, -118.243683º',
    }
    window._rebuild_loaded_views(show_progress=True)
    window._hide_progress()
    window._refresh_ui()
    app.processEvents()

    assert window._info_overlay_enabled is True
    assert window.exif_overlay.isVisible() is True
    assert window.exif_overlay.height() >= window.exif_overlay.minimumHeight()
    assert window.exif_overlay.histogram_plot.height() == HISTOGRAM_HEIGHT
    assert window.exif_overlay.exif_display()['Camera Model'] == 'EOS R5'

    window.close()


def test_main_window_compare_limit_menu_persists_selection() -> None:
    """
    Verify the View menu updates and restores the compare photo limit.

    Compare limit is a user preference rather than folder metadata, so it is
    stored in QSettings and restored for the next main-window instance.
    """
    app = QApplication.instance() or QApplication([])
    settings = QSettings(identity_module.APP_NAME, identity_module.APP_NAME)
    window = main_window_module.MainWindow()

    window.compare_limit_actions[12].trigger()

    assert window.compare_viewer.photo_limit == 12
    assert window.compare_limit_actions[12].isChecked() is True
    assert (
        int(settings.value(build_module.COMPARE_PHOTO_LIMIT_SETTINGS_KEY))
        == 12
    )

    window.close()

    restored_window = main_window_module.MainWindow()

    assert restored_window.compare_viewer.photo_limit == 12
    assert restored_window.compare_limit_actions[12].isChecked() is True

    restored_window.close()
    del app


def test_main_window_invalid_stored_compare_limit_uses_default() -> None:
    """
    Verify invalid persisted compare limits fall back to the default.

    This protects startup from stale or manually edited QSettings values that
    are not part of the supported discrete compare-limit options.
    """
    app = QApplication.instance() or QApplication([])
    settings = QSettings(identity_module.APP_NAME, identity_module.APP_NAME)
    settings.setValue(build_module.COMPARE_PHOTO_LIMIT_SETTINGS_KEY, 9)
    settings.sync()

    window = main_window_module.MainWindow()

    assert window.compare_viewer.photo_limit == DEFAULT_COMPARE_PHOTO_LIMIT
    assert window.compare_limit_actions[
        DEFAULT_COMPARE_PHOTO_LIMIT
    ].isChecked()

    window.close()
    del app


def test_main_window_photo_sort_control_persists_selection() -> None:
    """
    Verify the top-bar sort controls store and restore sort preferences.

    Sort mode and direction are app-level state, so both must survive a new
    main window.
    """
    app = QApplication.instance() or QApplication([])
    settings = QSettings(identity_module.APP_NAME, identity_module.APP_NAME)
    window = main_window_module.MainWindow()

    window.photo_sort_buttons[PHOTO_SORT_MODE_FILENAME].click()
    window.photo_sort_reverse_checkbox.setChecked(True)

    assert window.library.sort_mode == PHOTO_SORT_MODE_FILENAME
    assert window.library.sort_reversed is True
    assert window.photo_sort_buttons[PHOTO_SORT_MODE_FILENAME].isChecked()
    assert window.photo_sort_reverse_checkbox.isChecked()
    assert (
        settings.value(build_module.PHOTO_SORT_MODE_SETTINGS_KEY)
        == PHOTO_SORT_MODE_FILENAME
    )
    assert (
        normalize_sort_reversed(
            settings.value(build_module.PHOTO_SORT_REVERSED_SETTINGS_KEY)
        )
        is True
    )

    window.close()

    restored_window = main_window_module.MainWindow()

    assert restored_window.library.sort_mode == PHOTO_SORT_MODE_FILENAME
    assert restored_window.library.sort_reversed is True
    assert restored_window.photo_sort_buttons[
        PHOTO_SORT_MODE_FILENAME
    ].isChecked()
    assert restored_window.photo_sort_reverse_checkbox.isChecked()

    restored_window.close()
    del app


def test_main_window_invalid_stored_photo_sort_uses_default() -> None:
    """
    Verify stale or manually edited sort settings fall back to capture time.

    This protects startup from unsupported persisted QSettings values.
    """
    app = QApplication.instance() or QApplication([])
    settings = QSettings(identity_module.APP_NAME, identity_module.APP_NAME)
    settings.setValue(build_module.PHOTO_SORT_MODE_SETTINGS_KEY, 'unknown')
    settings.setValue(
        build_module.PHOTO_SORT_REVERSED_SETTINGS_KEY, 'not-a-bool'
    )
    settings.sync()

    window = main_window_module.MainWindow()

    assert window.library.sort_mode == PHOTO_SORT_MODE_CAPTURE_TIME
    assert window.library.sort_reversed is False
    assert window.photo_sort_buttons[PHOTO_SORT_MODE_CAPTURE_TIME].isChecked()
    assert not window.photo_sort_reverse_checkbox.isChecked()

    window.close()
    del app


def test_main_window_photo_sort_applies_to_loaded_folder_immediately(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify changing sort mode rebuilds loaded views around the current photo.

    Immediate apply should reorder both navigation lists without throwing away
    the user's active selection.
    """
    create_jpeg(tmp_path / 'IMG_2302.JPG', 'blue')
    create_jpeg(tmp_path / 'IMG_2300.JPG', 'green')
    create_jpeg(tmp_path / 'IMG_2301.JPG', 'purple')
    stub_read_exif(
        monkeypatch,
        {
            'IMG_2302.JPG': {'DateTimeOriginal': '2024:05:01 10:00:00'},
            'IMG_2301.JPG': {'DateTimeOriginal': '2024:05:01 10:00:05'},
            'IMG_2300.JPG': {'DateTimeOriginal': '2024:05:01 10:00:10'},
        },
    )

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.library = library
    window.current_photo_id = 'IMG_2301'
    window._populate_thumbnail_list()
    window._populate_browse_list()
    window._populate_scene_list()
    window._display_current_photo()
    window._refresh_ui()

    assert [photo.photo_id for photo in window.library.photos] == [
        'IMG_2302',
        'IMG_2301',
        'IMG_2300',
    ]

    _select_photo_ids(window.thumbnail_list, ['IMG_2302', 'IMG_2300'])

    window.photo_sort_buttons[PHOTO_SORT_MODE_FILENAME].click()

    assert [photo.photo_id for photo in window.library.photos] == [
        'IMG_2300',
        'IMG_2301',
        'IMG_2302',
    ]
    assert window.current_photo_id == 'IMG_2301'
    assert window.thumbnail_list.currentRow() == 1
    assert window.browse_list.currentRow() == 1
    assert _collect_selected_photo_ids(window.thumbnail_list) == [
        'IMG_2300',
        'IMG_2302',
    ]

    window.close()
    del app


def test_main_window_photo_sort_reorders_scene_and_browse_lists(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify sort-mode changes immediately reorder all non-compare lists.

    Scene membership is stable, but the vertical stack covers, horizontal
    in-scene strip, and browse grid should all follow the new photo order.
    """
    _, app, window = _create_sorting_window(tmp_path, monkeypatch)

    assert [photo.photo_id for photo in window.library.photos] == [
        'IMG_2402',
        'IMG_2400',
        'IMG_2403',
        'IMG_2401',
    ]
    assert _collect_photo_ids_from_list(window.thumbnail_list) == [
        'IMG_2402',
        'IMG_2400',
    ]
    assert _collect_photo_ids_from_list(window.scene_list) == [
        'IMG_2402',
        'IMG_2401',
    ]
    assert _collect_photo_ids_from_list(window.browse_list) == [
        'IMG_2402',
        'IMG_2400',
        'IMG_2403',
        'IMG_2401',
    ]

    _select_photo_ids(
        window.scene_list,
        ['IMG_2402', 'IMG_2401'],
        set_current=True,
    )
    window.scene_list.setFocus(Qt.OtherFocusReason)

    window.photo_sort_buttons[PHOTO_SORT_MODE_FILENAME].click()
    app.processEvents()

    assert [photo.photo_id for photo in window.library.photos] == [
        'IMG_2400',
        'IMG_2401',
        'IMG_2402',
        'IMG_2403',
    ]
    assert _collect_photo_ids_from_list(window.thumbnail_list) == [
        'IMG_2400',
        'IMG_2401',
    ]
    assert _collect_photo_ids_from_list(window.scene_list) == [
        'IMG_2401',
        'IMG_2402',
    ]
    assert _collect_photo_ids_from_list(window.browse_list) == [
        'IMG_2400',
        'IMG_2401',
        'IMG_2402',
        'IMG_2403',
    ]
    assert _collect_selected_photo_ids(window.scene_list) == [
        'IMG_2401',
        'IMG_2402',
    ]

    window.close()
    del app


def test_main_window_photo_sort_reverse_reorders_loaded_views(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify the Reverse checkbox applies immediately to loaded views.

    Reverse capture-time order should flow through scene stacks, the current
    scene strip, and the browse grid without changing the current photo.
    """
    _, app, window = _create_sorting_window(tmp_path, monkeypatch)

    window.photo_sort_reverse_checkbox.setChecked(True)
    app.processEvents()

    assert window.library.sort_reversed is True
    assert [photo.photo_id for photo in window.library.photos] == [
        'IMG_2401',
        'IMG_2403',
        'IMG_2400',
        'IMG_2402',
    ]
    assert _collect_photo_ids_from_list(window.thumbnail_list) == [
        'IMG_2401',
        'IMG_2403',
    ]
    assert _collect_photo_ids_from_list(window.scene_list) == [
        'IMG_2401',
        'IMG_2402',
    ]
    assert _collect_photo_ids_from_list(window.browse_list) == [
        'IMG_2401',
        'IMG_2403',
        'IMG_2400',
        'IMG_2402',
    ]
    assert window.current_photo_id == 'IMG_2401'

    window.close()
    del app


def test_main_window_photo_sort_reorders_compare_grid(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify sort changes immediately rearrange the active compare grid.

    Compare mode owns its own pane order, so it must be refreshed explicitly
    while preserving the same compared photo set and active pane.
    """
    _, app, window = _create_sorting_window(tmp_path, monkeypatch)
    window._enter_browse_mode()
    _select_photo_ids(
        window.browse_list,
        ['IMG_2402', 'IMG_2400', 'IMG_2403', 'IMG_2401'],
        set_current=True,
    )
    window.browse_list.setFocus(Qt.OtherFocusReason)
    window._enter_compare_mode()
    app.processEvents()

    assert window._compare_mode is True
    assert window.compare_viewer.photo_ids() == [
        'IMG_2402',
        'IMG_2400',
        'IMG_2403',
        'IMG_2401',
    ]

    window.compare_viewer.set_active_photo_id('IMG_2403')

    window.photo_sort_buttons[PHOTO_SORT_MODE_FILENAME].click()
    app.processEvents()

    assert window.compare_viewer.photo_ids() == [
        'IMG_2400',
        'IMG_2401',
        'IMG_2402',
        'IMG_2403',
    ]
    assert window.compare_viewer.active_photo_id() == 'IMG_2403'
    assert window.current_photo_id == 'IMG_2403'

    window.photo_sort_reverse_checkbox.setChecked(True)
    app.processEvents()

    assert window.compare_viewer.photo_ids() == [
        'IMG_2403',
        'IMG_2402',
        'IMG_2401',
        'IMG_2400',
    ]
    assert window.compare_viewer.active_photo_id() == 'IMG_2403'
    assert window.current_photo_id == 'IMG_2403'

    window.close()
    del app


def test_main_window_photo_sort_preserves_selected_compare_photo_view(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify sort changes keep one-photo compare inspection open.

    Sorting should rearrange the same compare working set without pushing the
    user back to the grid or losing the active photo's 100% inspection state.
    """
    _, app, window = _create_sorting_window(tmp_path, monkeypatch)
    window._enter_browse_mode()
    _select_photo_ids(
        window.browse_list,
        ['IMG_2402', 'IMG_2400', 'IMG_2403', 'IMG_2401'],
        set_current=True,
    )
    window.browse_list.setFocus(Qt.OtherFocusReason)
    window._enter_compare_mode()
    app.processEvents()
    window.compare_viewer.set_active_photo_id('IMG_2403')

    window.space_shortcut.activated.emit()
    app.processEvents()
    window.space_shortcut.activated.emit()
    app.processEvents()

    selected_viewer = window.compare_viewer.selected_viewer
    assert window.compare_viewer.is_selected_photo_view() is True
    assert window.compare_viewer.active_photo_id() == 'IMG_2403'
    assert selected_viewer.is_actual_size_zoom_active() is True
    selected_center = selected_viewer.normalized_viewport_center()

    window.photo_sort_buttons[PHOTO_SORT_MODE_FILENAME].click()
    app.processEvents()

    selected_viewer = window.compare_viewer.selected_viewer
    assert window._compare_mode is True
    assert window.compare_viewer.is_selected_photo_view() is True
    assert window.compare_viewer.photo_ids() == [
        'IMG_2400',
        'IMG_2401',
        'IMG_2402',
        'IMG_2403',
    ]
    assert window.compare_viewer.active_photo_id() == 'IMG_2403'
    assert window.current_photo_id == 'IMG_2403'
    assert selected_viewer.is_actual_size_zoom_active() is True
    assert selected_viewer.normalized_viewport_center() == selected_center

    window.close()
    del app


def test_about_action_shows_easy_cull_version(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    about_calls: list[tuple[object, str, str]] = []

    monkeypatch.setattr(
        QMessageBox,
        'about',
        lambda parent, title, text: about_calls.append((parent, title, text)),
    )

    window.about_action.trigger()

    assert about_calls == [
        (
            window,
            'About EasyCull',
            (
                'EasyCull\n\n'
                f'Version {identity_module.APP_VERSION}\n\n'
                'Photo culling made easy.'
            ),
        )
    ]
    assert f'Version {identity_module.APP_VERSION}' in about_calls[0][2]

    window.close()
    del app


def test_main_window_theme_toggle_switches_between_light_and_dark() -> None:
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False

    assert window.current_theme.name == 'light'

    window.theme_toggle.setChecked(True)
    assert window.current_theme.name == 'dark'

    window.theme_toggle.setChecked(False)
    assert window.current_theme.name == 'light'

    window.close()
    del app


def test_browse_mode_shortcut_does_nothing_when_no_photos_loaded() -> None:
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._browse_mode is False
    assert window.browse_list.isVisible() is False

    window.close()
    del app


def test_assign_photo_menu_structure_and_shortcuts(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _desktop_app, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_M300', 'dimgray')],
    )

    menu_bar = window.menuBar()
    menu_titles = [action.text() for action in menu_bar.actions()]
    assert 'Assign to &Photo' in menu_titles
    assert window.organize_action.isEnabled() is True

    rating_labels = [a.text() for a in window.rating_menu.actions()]
    assert '1 Star' in rating_labels
    assert '2 Stars' in rating_labels
    assert '3 Stars' in rating_labels
    assert '4 Stars' in rating_labels
    assert '5 Stars' in rating_labels
    assert 'Clear Rating' in rating_labels

    color_labels = [
        a.text().split('\t', 1)[0] for a in window.color_label_menu.actions()
    ]
    assert 'Red' in color_labels
    assert 'Yellow' in color_labels
    assert 'Green' in color_labels
    assert 'Blue' in color_labels
    assert 'Purple' in color_labels
    assert 'Clear Color Label' in color_labels

    flag_labels = [a.text() for a in window.flag_menu.actions()]
    assert 'Pick' in flag_labels
    assert 'Reject' in flag_labels
    assert 'Clear Flag' in flag_labels

    for key, action in window.color_label_actions.items():
        if key == 'purple':
            assert action.shortcut().isEmpty()
        elif key is not None:
            assert not action.shortcut().isEmpty()

    for action in window.rating_actions.values():
        assert not action.shortcut().isEmpty()

    for action in window.flag_actions.values():
        assert not action.shortcut().isEmpty()

    window.close()
    del app
