from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

import easy_loupe.ui.identity as identity_module
import easy_loupe.ui.main_window.build as build_module
import easy_loupe.ui.main_window.window as main_window_module
import easy_loupe.ui.theme as theme_module
from easy_loupe.core.folder_loading import (
    PHOTO_SORT_MODE_CAPTURE_TIME,
    PHOTO_SORT_MODE_FILENAME,
    normalize_sort_reversed,
)
from easy_loupe.core.photo_library import PhotoLibrary
from easy_loupe.ui.launch import CullingLaunchRequest
from easy_loupe.ui.shortcut_help import ShortcutHelpContext
from easy_loupe.ui.viewers.compare_photo_viewer import (
    COMPARE_PHOTO_LIMIT_OPTIONS,
    DEFAULT_COMPARE_PHOTO_LIMIT,
)
from easy_loupe.ui.viewers.exif_overlay import HISTOGRAM_HEIGHT
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
    assert window.photo_open_group.objectName() == 'photoOpenGroup'
    assert window.open_button.parentWidget() is window.photo_open_group
    assert (
        window.photo_load_recursively_checkbox.parentWidget()
        is window.photo_open_group
    )
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


def _shortcut_help_description_texts(window: Any) -> set[str]:
    return {
        label.text()
        for label in window.shortcut_help_overlay.findChildren(
            QLabel, 'shortcutHelpDescriptionLabel'
        )
    }


def _action_shortcut_texts(action: QAction) -> list[str]:
    return [
        shortcut.toString(QKeySequence.PortableText)
        for shortcut in action.shortcuts()
    ]


def _open_shortcut_help_with_shift_slash(
        window: Any, app: QApplication
) -> None:
    """
    Open shortcut help through the physical question-mark key chord.

    The test sends explicit key events instead of ``QTest.keyClick`` because Qt
    can leave the global Shift modifier active after synthetic shortcut
    delivery. Releasing both slash and Shift keeps later focus/navigation tests
    from seeing a stale extended-selection modifier.
    """
    for target in (window.central_widget, window):
        for _attempt in range(3):
            window.raise_()
            window.activateWindow()
            app.processEvents()
            QTest.qWait(10)
            press_event = QKeyEvent(
                QEvent.KeyPress,
                Qt.Key_Slash,
                Qt.KeyboardModifier.ShiftModifier,
                '?',
            )
            release_event = QKeyEvent(
                QEvent.KeyRelease,
                Qt.Key_Slash,
                Qt.KeyboardModifier.NoModifier,
                '',
            )
            shift_release_event = QKeyEvent(
                QEvent.KeyRelease,
                Qt.Key_Shift,
                Qt.KeyboardModifier.NoModifier,
                '',
            )
            QApplication.sendEvent(target, press_event)
            QApplication.sendEvent(target, release_event)
            QApplication.sendEvent(target, shift_release_event)
            app.processEvents()
            if window.shortcut_help_overlay.isVisible():
                return

    raise AssertionError('Shift+/ did not open shortcut help')


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


def _create_recursive_loading_window(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, Any]:
    create_jpeg(tmp_path / 'ROOT.JPG', 'blue')
    subfolder = tmp_path / 'subfolder_1'
    subfolder.mkdir()
    create_jpeg(subfolder / 'NESTED.JPG', 'green')
    stub_read_exif(monkeypatch, {})
    library = PhotoLibrary(cache_dir=tmp_path / '.cache-recursive')
    library.load_folder(tmp_path)

    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.library = library
    window.current_photo_id = 'subfolder_1/NESTED'
    window._populate_thumbnail_list()
    window._populate_browse_list()
    window._populate_scene_list()
    window._display_current_photo()
    window._refresh_ui()
    window.show()
    app.processEvents()
    return app, window


def test_main_window_registers_open_detect_and_organize_actions() -> None:  # noqa: PLR0915
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()

    assert window.windowTitle() == 'EasyLoupe'
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
    assert window.shortcut_help_action.text() == 'Keyboard Shortcuts'
    assert (
        window.shortcut_help_action.shortcut().toString(
            QKeySequence.PortableText
        )
        == '?'
    )
    assert _action_shortcut_texts(window.shortcut_help_action) == [
        '?',
        'Shift+/',
    ]
    assert window.about_action.text() == 'About EasyLoupe'
    assert window.about_action.menuRole() == QAction.AboutRole
    assert (
        window.rating_actions[1].shortcut().toString(QKeySequence.PortableText)
        == '1'
    )
    assert (
        window
        .rating_actions[None]
        .shortcut()
        .toString(QKeySequence.PortableText)
        == '0'
    )
    assert (
        window
        .color_label_actions['red']
        .shortcut()
        .toString(QKeySequence.PortableText)
        == '6'
    )
    assert (
        window
        .color_label_actions['blue']
        .shortcut()
        .toString(QKeySequence.PortableText)
        == '9'
    )
    assert window.color_label_actions[None].shortcut().isEmpty()
    assert window.color_label_actions[None].text().endswith('\t`')
    assert (
        window
        .color_label_actions['purple']
        .shortcut()
        .toString(QKeySequence.PortableText)
        == ''
    )
    assert (
        window
        .flag_actions['picked']
        .shortcut()
        .toString(QKeySequence.PortableText)
        == 'P'
    )
    assert (
        window
        .flag_actions[None]
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
    assert window.show_af_point_toggle.isChecked() is False
    assert (
        window.show_af_point_toggle.toolTip()
        == main_window_module.MainWindow._shortcut_tooltip(
            'Show AF point', 'F'
        )
    )
    assert not hasattr(window, 'zoom_to_af_point_toggle')
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

    window.show_af_point_toggle.setChecked(False)

    assert window.viewer._focus_point_marker_enabled is False
    assert window.viewer.single_viewer._focus_point_marker_enabled is False
    assert window.viewer.split_fit_viewer._focus_point_marker_enabled is False
    assert window.viewer.split_zoom_viewer._focus_point_marker_enabled is False
    assert (
        window.metadata_label.text()
        == f'Metadata: {theme_module.NO_METADATA_TEXT}'
    )

    window.close()
    del app


def test_main_window_shortcut_help_tracks_current_view(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify ``?`` shows context-specific help and Esc closes it first.

    Compare mode already uses Esc for navigation, so the help overlay must win
    the first Esc press without exiting compare or selected-photo compare.
    """
    no_scenes_path = tmp_path / 'no-scenes'
    no_scenes_path.mkdir()
    _theme, app, window = create_main_window_with_library(
        no_scenes_path,
        monkeypatch,
        photo_specs=[
            ('IMG_1000', 'red'),
            ('IMG_1001', 'green'),
            ('IMG_1002', 'blue'),
        ],
    )

    assert (
        window._shortcut_help_context()
        == ShortcutHelpContext.CULLING_VIEW_NO_SCENES
    )
    _open_shortcut_help_with_shift_slash(window, app)

    assert window.shortcut_help_overlay.isVisible() is True
    assert window.shortcut_help_overlay.title_label.text() == (
        'Culling View Shortcuts'
    )

    # Help is modal for keyboard shortcuts, so browse entry must not happen
    # behind the overlay and leave the visible help text out of date.
    window.browse_mode_shortcut.activated.emit()
    app.processEvents()
    assert window.shortcut_help_overlay.isVisible() is True
    assert window._browse_mode is False

    window.shortcut_help_action.trigger()
    app.processEvents()
    assert window.shortcut_help_overlay.isHidden() is True

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()
    assert window._shortcut_help_context() == ShortcutHelpContext.BROWSE

    window.shortcut_help_action.trigger()
    app.processEvents()
    assert window.shortcut_help_overlay.title_label.text() == (
        'Browse View Shortcuts'
    )

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()
    assert window.shortcut_help_overlay.isHidden() is True
    assert window._browse_mode is True

    window.space_shortcut.activated.emit()
    app.processEvents()
    _select_photo_ids(
        window.thumbnail_list,
        ['IMG_1000', 'IMG_1001'],
        set_current=True,
    )
    window.compare_mode_shortcut.activated.emit()
    app.processEvents()
    assert window._compare_mode is True
    assert window._shortcut_help_context() == ShortcutHelpContext.COMPARE_GRID

    window.shortcut_help_action.trigger()
    app.processEvents()
    assert window.shortcut_help_overlay.title_label.text() == (
        'Compare Grid Shortcuts'
    )

    # Space normally opens the active compare photo. While help is visible it
    # must wait, otherwise the next Esc would target different compare state.
    window.space_shortcut.activated.emit()
    app.processEvents()
    assert window.shortcut_help_overlay.isVisible() is True
    assert window.compare_viewer.is_selected_photo_view() is False

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()
    assert window.shortcut_help_overlay.isHidden() is True
    assert window._compare_mode is True

    window.space_shortcut.activated.emit()
    app.processEvents()
    assert window.compare_viewer.is_selected_photo_view() is True
    assert (
        window._shortcut_help_context()
        == ShortcutHelpContext.COMPARE_SELECTED_PHOTO
    )

    window.shortcut_help_action.trigger()
    app.processEvents()
    assert window.shortcut_help_overlay.title_label.text() == (
        'Selected Compare Photo Shortcuts'
    )

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()
    assert window.shortcut_help_overlay.isHidden() is True
    assert window.compare_viewer.is_selected_photo_view() is True
    window.close()
    app.processEvents()


def test_main_window_shortcut_help_tracks_scene_state(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify culling help includes scene-strip rows only after scenes exist.

    Scene-strip navigation is unavailable before scene detection, so the
    context-aware help must not advertise those rows until the strip is
    visible.
    """
    no_scenes_path = tmp_path / 'no-scenes'
    no_scenes_path.mkdir()
    _theme, app, window = create_main_window_with_library(
        no_scenes_path,
        monkeypatch,
        photo_specs=[
            ('IMG_1000', 'red'),
            ('IMG_1001', 'green'),
            ('IMG_1002', 'blue'),
        ],
    )

    assert (
        window._shortcut_help_context()
        == ShortcutHelpContext.CULLING_VIEW_NO_SCENES
    )
    window.shortcut_help_action.trigger()
    app.processEvents()

    description_texts = _shortcut_help_description_texts(window)
    assert 'Merge selected photos into a scene' in description_texts
    assert 'Move within the scene strip' not in description_texts
    assert 'Extend the in-scene selection' not in description_texts
    assert 'Extend selection across scene-stack rows' not in description_texts

    window.shortcut_help_action.trigger()
    app.processEvents()
    window.close()
    app.processEvents()

    with_scenes_path = tmp_path / 'with-scenes'
    with_scenes_path.mkdir()
    _theme, app, window = create_main_window_with_library(
        with_scenes_path,
        monkeypatch,
        photo_specs=[
            ('IMG_2000', 'cyan'),
            ('IMG_2001', 'magenta'),
            ('IMG_2002', 'yellow'),
        ],
        scene_groups=[
            ['IMG_2000', 'IMG_2001'],
            ['IMG_2002'],
        ],
    )

    assert window._shortcut_help_context() == ShortcutHelpContext.CULLING_VIEW
    window.shortcut_help_action.trigger()
    app.processEvents()

    description_texts = _shortcut_help_description_texts(window)
    assert 'Move within the scene strip' in description_texts
    assert 'Extend the in-scene selection' in description_texts
    assert 'Extend selection across scene-stack rows' in description_texts
    window.close()
    app.processEvents()


def test_main_window_shortcut_help_blocks_compare_limit_action(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify compare limit actions are disabled while shortcut help is visible.

    Compare limit options are checkable QAction items, so this regression
    covers the visible menu state as well as the guarded compare grid state.
    """
    _theme, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_1000', 'red'),
            ('IMG_1001', 'green'),
            ('IMG_1002', 'blue'),
        ],
    )
    _select_photo_ids(
        window.thumbnail_list,
        ['IMG_1000', 'IMG_1001', 'IMG_1002'],
        set_current=True,
    )
    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.compare_viewer.photo_ids() == [
        'IMG_1000',
        'IMG_1001',
        'IMG_1002',
    ]

    window.shortcut_help_action.trigger()
    app.processEvents()

    assert all(
        not action.isEnabled()
        for action in window.compare_limit_actions.values()
    )
    # Users cannot click a disabled QAction; the direct trigger also verifies
    # the defensive guard cannot leave a stale checked limit behind help.
    window.compare_limit_actions[3].trigger()
    app.processEvents()

    assert window.compare_viewer.photo_limit == DEFAULT_COMPARE_PHOTO_LIMIT
    assert window.compare_viewer.photo_ids() == [
        'IMG_1000',
        'IMG_1001',
        'IMG_1002',
    ]
    assert window.compare_limit_actions[
        DEFAULT_COMPARE_PHOTO_LIMIT
    ].isChecked()
    assert window.compare_limit_actions[3].isChecked() is False

    window.shortcut_help_action.trigger()
    app.processEvents()

    assert window.shortcut_help_overlay.isHidden() is True
    compare_limit_actions = window.compare_limit_actions.values()
    assert all(action.isEnabled() for action in compare_limit_actions)
    assert window.merge_scene_action.isEnabled() is False

    window.compare_limit_actions[2].trigger()
    app.processEvents()

    assert window.compare_viewer.photo_limit == 2
    assert window.compare_limit_actions[2].isChecked() is True
    window.close()
    app.processEvents()


def test_main_window_shortcut_help_disables_merge_scene_action(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify scene merge is greyed out while shortcut help is visible.

    The QAction slot is guarded, but the menu item also needs to communicate
    that the command is unavailable while the modal help overlay is open.
    """
    _theme, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_1000', 'red'),
            ('IMG_1001', 'green'),
            ('IMG_1002', 'blue'),
        ],
    )
    _select_photo_ids(
        window.thumbnail_list,
        ['IMG_1000', 'IMG_1001'],
        set_current=True,
    )
    before_groups = window.library.scene_group_photo_ids()
    before_source = window.library.scene_source

    assert window.merge_scene_action.isEnabled() is True

    window.shortcut_help_action.trigger()
    app.processEvents()

    assert window.merge_scene_action.isEnabled() is False
    # Direct trigger bypasses the disabled menu affordance, so this also
    # verifies the guarded slot cannot mutate scenes behind help.
    window.merge_scene_action.trigger()
    app.processEvents()

    assert window.library.scene_group_photo_ids() == before_groups
    assert window.library.scene_source == before_source
    assert window.library.scene_detection_done is False

    window.shortcut_help_action.trigger()
    app.processEvents()

    assert window.shortcut_help_overlay.isHidden() is True
    assert window.merge_scene_action.isEnabled() is True
    window.close()
    app.processEvents()


def test_main_window_shortcut_help_disables_loaded_file_actions(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify loaded File menu actions are greyed out by shortcut help.

    These actions use QAction menu entries as well as top-bar buttons, so this
    regression covers the menu affordance and the guarded QAction path.
    """
    _theme, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_1000', 'red'),
            ('IMG_1001', 'green'),
        ],
    )
    triggered_actions: list[str] = []
    monkeypatch.setattr(
        window, 'choose_folder', lambda: triggered_actions.append('open')
    )
    monkeypatch.setattr(
        window, 'detect_scenes', lambda: triggered_actions.append('detect')
    )
    monkeypatch.setattr(
        window,
        'open_organizer_dialog',
        lambda: triggered_actions.append('organize'),
    )

    assert window.open_action.isEnabled() is True
    assert window.detect_action.isEnabled() is True
    assert window.organize_action.isEnabled() is True

    window.shortcut_help_action.trigger()
    app.processEvents()

    assert window.open_action.isEnabled() is False
    assert window.detect_action.isEnabled() is False
    assert window.organize_action.isEnabled() is False
    # Direct triggers bypass the disabled menu affordance, so this also
    # verifies the shared action guard blocks programmatic activation.
    window.open_action.trigger()
    window.detect_action.trigger()
    window.organize_action.trigger()
    app.processEvents()

    assert triggered_actions == []

    window.shortcut_help_action.trigger()
    app.processEvents()

    assert window.shortcut_help_overlay.isHidden() is True
    assert window.open_action.isEnabled() is True
    assert window.detect_action.isEnabled() is True
    assert window.organize_action.isEnabled() is True
    window.close()
    app.processEvents()


def test_main_window_shortcut_help_disables_history_actions(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify undo/redo menu state matches the shortcut-help modal guard.

    The QAction slots are guarded defensively, but enabled menu state should
    also tell users that metadata history waits while help is open.
    """
    _theme, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_1000', 'red')],
    )
    photo = window.library.get_photo('IMG_1000')

    window._set_rating(3)
    app.processEvents()

    assert photo.rating == 3
    assert window.undo_metadata_action.isEnabled() is True
    assert window.redo_metadata_action.isEnabled() is False

    window.shortcut_help_action.trigger()
    app.processEvents()

    assert window.undo_metadata_action.isEnabled() is False
    assert window.redo_metadata_action.isEnabled() is False

    window.shortcut_help_action.trigger()
    app.processEvents()

    assert window.undo_metadata_action.isEnabled() is True
    window.undo_metadata_action.trigger()
    app.processEvents()

    assert photo.rating is None
    assert window.undo_metadata_action.isEnabled() is False
    assert window.redo_metadata_action.isEnabled() is True

    window.shortcut_help_action.trigger()
    app.processEvents()

    assert window.undo_metadata_action.isEnabled() is False
    assert window.redo_metadata_action.isEnabled() is False

    window.shortcut_help_action.trigger()
    app.processEvents()

    assert window.redo_metadata_action.isEnabled() is True
    window.close()
    app.processEvents()


def test_main_window_shortcut_help_restores_empty_file_actions() -> None:
    """
    Verify File menu action state restores correctly without loaded photos.

    Opening a folder is still allowed in an empty window after help closes,
    while photo-dependent File actions must remain unavailable.
    """
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.show()
    app.processEvents()

    assert window.open_action.isEnabled() is True
    assert window.detect_action.isEnabled() is False
    assert window.organize_action.isEnabled() is False

    window.shortcut_help_action.trigger()
    app.processEvents()

    assert window.open_action.isEnabled() is False
    assert window.detect_action.isEnabled() is False
    assert window.organize_action.isEnabled() is False

    window.shortcut_help_action.trigger()
    app.processEvents()

    assert window.shortcut_help_overlay.isHidden() is True
    assert window.open_action.isEnabled() is True
    assert window.detect_action.isEnabled() is False
    assert window.organize_action.isEnabled() is False
    window.close()
    app.processEvents()
    del app


def test_main_window_shortcut_help_blocks_deferred_thumbnail_focus(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify delayed thumbnail focus restores wait while help is visible.

    Scene-detection cleanup queues this helper after rebuilding lists, so it
    must respect the same modal guard as active-navigation focus restores.
    """
    _theme, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_1000', 'red'), ('IMG_1001', 'green')],
    )
    monkeypatch.setattr(window, 'isActiveWindow', lambda: True)

    assert window._thumbnail_strip_focus_available() is True

    window.shortcut_help_action.trigger()
    app.processEvents()

    assert window.shortcut_help_overlay.isVisible() is True
    assert window._thumbnail_strip_focus_available() is False

    window._restore_thumbnail_strip_focus()
    app.processEvents()
    focus_widget = app.focusWidget()
    if focus_widget is not None:
        assert focus_widget is not window.thumbnail_list
        assert focus_widget is not window.thumbnail_list.viewport()

    window.close()
    app.processEvents()


def test_main_window_shortcut_help_blocks_focused_list_key_events(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify real focused-list key events wait while shortcut help is visible.

    ``QShortcut.activated`` tests do not cover native QListWidget key handling.
    This guards the modal overlay from letting focused navigation widgets move
    photos behind the visible shortcut reference.
    """
    _theme, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_1000', 'red'),
            ('IMG_1001', 'green'),
            ('IMG_1002', 'blue'),
        ],
        scene_groups=[
            ['IMG_1000', 'IMG_1001'],
            ['IMG_1002'],
        ],
    )
    window.thumbnail_list.setFocus(Qt.OtherFocusReason)
    window.thumbnail_list.viewport().setFocus(Qt.OtherFocusReason)
    window.shortcut_help_action.trigger()
    app.processEvents()

    focus_widget = app.focusWidget()
    if focus_widget is not None:
        assert focus_widget is window.shortcut_help_overlay

    assert window.current_photo_id == 'IMG_1000'
    assert _collect_selected_photo_ids(window.thumbnail_list) == ['IMG_1000']

    # Some Qt backends leave app.focusWidget() unset after focus changes; the
    # fallback still sends the key through the overlay path that must block
    # list navigation behind help.
    QTest.keyClick(focus_widget or window.shortcut_help_overlay, Qt.Key_Down)
    app.processEvents()

    assert window.current_photo_id == 'IMG_1000'
    assert _collect_selected_photo_ids(window.thumbnail_list) == ['IMG_1000']

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()
    assert window.shortcut_help_overlay.isHidden() is True
    focus_widget = app.focusWidget()
    if focus_widget is not None:
        assert (
            focus_widget is window.thumbnail_list
            or focus_widget is window.thumbnail_list.viewport()
        )

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()
    assert window._browse_mode is True
    window.browse_list.setFocus(Qt.OtherFocusReason)
    window.browse_list.viewport().setFocus(Qt.OtherFocusReason)
    window.shortcut_help_action.trigger()
    app.processEvents()

    focus_widget = app.focusWidget()
    if focus_widget is not None:
        assert focus_widget is window.shortcut_help_overlay

    assert window.current_photo_id == 'IMG_1000'
    QTest.keyClick(focus_widget or window.shortcut_help_overlay, Qt.Key_Right)
    app.processEvents()

    assert window._browse_mode is True
    assert window.current_photo_id == 'IMG_1000'
    assert _collect_selected_photo_ids(window.browse_list) == ['IMG_1000']

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()
    window.space_shortcut.activated.emit()
    app.processEvents()
    assert window._browse_mode is False

    window.scene_list.setFocus(Qt.OtherFocusReason)
    window.scene_list.viewport().setFocus(Qt.OtherFocusReason)
    window.shortcut_help_action.trigger()
    app.processEvents()

    focus_widget = app.focusWidget()
    if focus_widget is not None:
        assert focus_widget is window.shortcut_help_overlay

    assert window.current_photo_id == 'IMG_1000'
    QTest.keyClick(focus_widget or window.shortcut_help_overlay, Qt.Key_Right)
    app.processEvents()

    assert window.current_photo_id == 'IMG_1000'
    assert _collect_selected_photo_ids(window.scene_list) == ['IMG_1000']
    window.exit_compare_shortcut.activated.emit()
    app.processEvents()
    window.close()
    app.processEvents()


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


def test_main_window_recursive_loading_control_persists_selection() -> None:
    """
    Verify Include subfolders is a persisted app-level preference.

    This protects startup from losing the user's scan-mode choice between
    main-window instances.
    """
    app = QApplication.instance() or QApplication([])
    settings = QSettings(identity_module.APP_NAME, identity_module.APP_NAME)
    window = main_window_module.MainWindow()

    assert window.photo_load_recursively_checkbox.text() == (
        'Include subfolders'
    )
    assert window.photo_load_recursively_checkbox.isChecked() is True
    assert window.library.load_recursively is True

    window.photo_load_recursively_checkbox.setChecked(False)

    assert window.library.load_recursively is False
    assert window.photo_load_recursively_checkbox.isChecked() is False
    assert (
        build_module.normalize_load_recursively(
            settings.value(build_module.PHOTO_LOAD_RECURSIVELY_SETTINGS_KEY)
        )
        is False
    )

    window.close()

    restored_window = main_window_module.MainWindow()

    assert restored_window.library.load_recursively is False
    assert restored_window.photo_load_recursively_checkbox.isChecked() is False

    restored_window.close()
    del app


def test_main_window_invalid_stored_recursive_loading_uses_default() -> None:
    """
    Verify invalid persisted recursive settings fall back to checked.

    Manually edited settings should not disable recursive loading by accident.
    """
    app = QApplication.instance() or QApplication([])
    settings = QSettings(identity_module.APP_NAME, identity_module.APP_NAME)
    settings.setValue(
        build_module.PHOTO_LOAD_RECURSIVELY_SETTINGS_KEY, 'not-a-bool'
    )
    settings.sync()

    window = main_window_module.MainWindow()

    assert window.library.load_recursively is True
    assert window.photo_load_recursively_checkbox.isChecked() is True

    window.close()
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


def test_main_window_recursive_loading_cancel_reverts_toggle(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Canceling the reload prompt leaves loaded state and setting unchanged.

    This guards the Qt toggle timing where the checkbox changes visually before
    the app knows whether the user accepted the required folder reload.
    """
    app, window = _create_recursive_loading_window(tmp_path, monkeypatch)
    clicked_button: dict[str, object | None] = {'button': None}

    def fake_exec(message_box: QMessageBox) -> int:
        clicked_button['button'] = message_box.button(
            QMessageBox.StandardButton.Cancel
        )
        return 0

    monkeypatch.setattr(QMessageBox, 'exec', fake_exec)
    monkeypatch.setattr(
        QMessageBox,
        'clickedButton',
        lambda _message_box: clicked_button['button'],
    )

    window.photo_load_recursively_checkbox.setChecked(False)
    app.processEvents()

    settings = QSettings(identity_module.APP_NAME, identity_module.APP_NAME)
    assert window.library.load_recursively is True
    assert window.photo_load_recursively_checkbox.isChecked() is True
    assert [photo.photo_id for photo in window.library.photos] == [
        'ROOT',
        'subfolder_1/NESTED',
    ]
    assert not settings.contains(
        build_module.PHOTO_LOAD_RECURSIVELY_SETTINGS_KEY
    )

    window.close()
    del app


def test_main_window_recursive_loading_reload_applies_to_current_folder(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify confirming the reload prompt rescans with the new preference.

    The current photo may disappear when subfolders are excluded, so the reload
    path must choose a valid selection after rebuilding all lists.
    """
    app, window = _create_recursive_loading_window(tmp_path, monkeypatch)
    clicked_button: dict[str, object | None] = {'button': None}

    def fake_exec(message_box: QMessageBox) -> int:
        reload_button = next(
            button
            for button in message_box.buttons()
            if button.text() == 'Reload'
        )
        clicked_button['button'] = reload_button
        return 0

    monkeypatch.setattr(QMessageBox, 'exec', fake_exec)
    monkeypatch.setattr(
        QMessageBox,
        'clickedButton',
        lambda _message_box: clicked_button['button'],
    )

    window.photo_load_recursively_checkbox.setChecked(False)
    app.processEvents()

    settings = QSettings(identity_module.APP_NAME, identity_module.APP_NAME)
    assert window.library.load_recursively is False
    assert window.photo_load_recursively_checkbox.isChecked() is False
    assert [photo.photo_id for photo in window.library.photos] == ['ROOT']
    assert window.current_photo_id == 'ROOT'
    assert (
        build_module.normalize_load_recursively(
            settings.value(build_module.PHOTO_LOAD_RECURSIVELY_SETTINGS_KEY)
        )
        is False
    )

    window.close()
    del app


def test_main_window_recursive_loading_empty_reload_shows_no_eligible_dialog(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify direct-only reloads that find no photos explain the empty state.

    This covers folders where all eligible photos live below the selected root
    and become hidden when Include subfolders is unchecked.
    """
    nested = tmp_path / 'subfolder_1'
    nested.mkdir()
    create_jpeg(nested / 'NESTED.JPG', 'green')
    stub_read_exif(monkeypatch, {})
    library = PhotoLibrary(cache_dir=tmp_path / '.cache-recursive')
    library.load_folder(tmp_path)
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.library = library
    window.current_photo_id = 'subfolder_1/NESTED'
    window._populate_thumbnail_list()
    window._populate_browse_list()
    window._populate_scene_list()
    window._display_current_photo()
    window._refresh_ui()
    clicked_button: dict[str, object | None] = {'button': None}
    empty_dialogs: list[tuple[str, str]] = []

    def fake_exec(message_box: QMessageBox) -> int:
        reload_button = next(
            button
            for button in message_box.buttons()
            if button.text() == 'Reload'
        )
        clicked_button['button'] = reload_button
        return 0

    def fake_information(
            _parent: object,
            title: str,
            text: str,
            *_args: object,
    ) -> QMessageBox.StandardButton:
        empty_dialogs.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, 'exec', fake_exec)
    monkeypatch.setattr(
        QMessageBox,
        'clickedButton',
        lambda _message_box: clicked_button['button'],
    )
    monkeypatch.setattr(QMessageBox, 'information', fake_information)

    window.photo_load_recursively_checkbox.setChecked(False)
    app.processEvents()

    assert empty_dialogs == [
        (
            'No Eligible Photos',
            'No supported photos were found in the selected folder.',
        )
    ]
    assert window.library.load_recursively is False
    assert window.library.photos == []
    assert window.current_photo_id is None
    assert window.detect_button.isEnabled() is False
    assert window.organize_button.isEnabled() is False

    window.close()
    del app


def test_main_window_handoff_reapplies_persisted_culling_sort(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify culling handoff reapplies persisted sort to a preloaded library.

    The photo viewer deliberately hydrates folders in filename order, but
    culling mode must restore its own saved sort before building the UI lists.
    """
    app = QApplication.instance() or QApplication([])
    settings = QSettings(identity_module.APP_NAME, identity_module.APP_NAME)
    settings.setValue(
        build_module.PHOTO_SORT_MODE_SETTINGS_KEY,
        PHOTO_SORT_MODE_CAPTURE_TIME,
    )
    settings.setValue(build_module.PHOTO_SORT_REVERSED_SETTINGS_KEY, True)
    settings.sync()
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    stub_read_exif(
        monkeypatch,
        {
            'A.JPG': {'DateTimeOriginal': '2024:05:01 10:00:00'},
            'B.JPG': {'DateTimeOriginal': '2024:05:01 10:00:10'},
        },
    )
    preloaded_library = PhotoLibrary(
        cache_dir=tmp_path / '.cache',
        sort_mode=PHOTO_SORT_MODE_FILENAME,
    )
    preloaded_library.load_folder(tmp_path)

    window = main_window_module.MainWindow(
        launch_request=CullingLaunchRequest(
            folder=tmp_path,
            selected_photo_id='A',
            enter_browse=True,
            preloaded_library=preloaded_library,
        )
    )

    assert [photo.photo_id for photo in window.library.photos] == ['B', 'A']
    assert window.current_photo_id == 'A'
    assert window.library.sort_mode == PHOTO_SORT_MODE_CAPTURE_TIME
    assert window.library.sort_reversed is True
    assert window.photo_sort_buttons[PHOTO_SORT_MODE_CAPTURE_TIME].isChecked()
    assert window.photo_sort_reverse_checkbox.isChecked()
    assert window._browse_mode is True
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


def test_about_action_shows_easy_loupe_version(
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
            'About EasyLoupe',
            (
                'EasyLoupe\n\n'
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
