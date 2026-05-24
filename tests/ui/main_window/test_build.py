from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt

from tests.ui._helpers import create_main_window_with_library

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_mode_shortcuts_trigger_correct_state_transitions(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _desktop_app, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_K400', 'dimgray'), ('IMG_K401', 'blue')],
    )

    choose_calls: list[str] = []
    original_choose = window.choose_folder
    window.choose_folder = lambda: choose_calls.append('choose')
    window.open_action.trigger()
    app.processEvents()
    assert choose_calls == ['choose']
    window.choose_folder = original_choose

    detect_calls: list[str] = []
    original_detect = window.detect_scenes
    window.detect_scenes = lambda: detect_calls.append('detect')
    window.detect_action.trigger()
    app.processEvents()
    assert detect_calls == ['detect']
    window.detect_scenes = original_detect

    organize_calls: list[str] = []
    original_organize = window.open_organizer_dialog
    window.open_organizer_dialog = lambda: organize_calls.append('organize')
    window.organize_action.trigger()
    app.processEvents()
    assert organize_calls == ['organize']
    window.open_organizer_dialog = original_organize

    assert window._browse_mode is False
    window.browse_mode_shortcut.activated.emit()
    app.processEvents()
    assert window._browse_mode is True
    assert window.browse_list.isVisible() is True
    assert window.content_splitter.isVisible() is False

    window.space_shortcut.activated.emit()
    app.processEvents()
    assert window._browse_mode is False
    assert window.content_splitter.isVisible() is True
    assert window.viewer._mode == 'single-fit'

    window.zoom_toggle_shortcut.activated.emit()
    app.processEvents()
    assert window.viewer._mode == 'single-manual'

    window.zoom_toggle_shortcut.activated.emit()
    app.processEvents()
    assert window.viewer._mode == 'single-fit'

    window.split_mode_shortcut.activated.emit()
    app.processEvents()
    assert window.viewer.is_split_view() is True
    assert window.viewer._mode == 'split'

    window.split_mode_shortcut.activated.emit()
    app.processEvents()
    assert window.viewer.is_split_view() is False

    window.close()
    del app


def test_change_event_restores_navigation_focus_when_window_reactivates(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Window reactivation should pull focus back to the active navigation list.
    """
    _desktop_app, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_K500', 'dimgray'), ('IMG_K501', 'blue')],
    )
    window.activateWindow()
    window.raise_()
    app.processEvents()

    window.open_button.setFocus(Qt.OtherFocusReason)
    app.processEvents()
    assert app.focusWidget() is window.open_button

    window.changeEvent(QEvent(QEvent.ActivationChange))
    app.processEvents()

    assert app.focusWidget() in {
        window.thumbnail_list,
        window.thumbnail_list.viewport(),
    }

    window.close()
    del app
