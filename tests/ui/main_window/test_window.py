from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QMessageBox

import easy_cull.ui.identity as identity_module
import easy_cull.ui.main_window.build as build_module
import easy_cull.ui.main_window.window as main_window_module
import easy_cull.ui.theme as theme_module
from easy_cull.ui.viewers.compare_photo_viewer import (
    COMPARE_PHOTO_LIMIT_OPTIONS,
    DEFAULT_COMPARE_PHOTO_LIMIT,
)
from tests.ui._helpers import create_main_window_with_library

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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
    assert window.compare_menu.title() == '&Compare'
    assert window.compare_limit_menu.title() == '&Limit'
    assert list(window.compare_limit_actions) == list(
        COMPARE_PHOTO_LIMIT_OPTIONS
    )
    assert window.compare_limit_actions[
        DEFAULT_COMPARE_PHOTO_LIMIT
    ].isChecked()
    assert window.compare_viewer.photo_limit == DEFAULT_COMPARE_PHOTO_LIMIT
    assert window.assign_photo_menu.title() == 'Assign to &Photo'
    assert window.help_menu.title() == '&Help'
    assert window.about_action.text() == 'About EasyCull'
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
    assert 'Version 0.1.4' in about_calls[0][2]

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
