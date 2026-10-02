"""
MainWindow tests for view-only photo rotation with `[` and `]`.

Rotation is persisted per photo in ``easy-loupe.json`` and shares the tag
selection, gating, and undo rules, but it must update existing cards and
viewers in place because it never changes list membership or order.
"""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from easy_loupe.core.records import METADATA_FILENAME
from tests.ui._helpers import (
    create_main_window_with_library,
    set_qt_active_window,
    thumbnail_item_widget,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    import pytest


def _read_metadata(tmp_path: Path) -> dict[str, Any]:
    return json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )


def _item_widgets(list_widget: Any) -> list[Any]:
    return [
        list_widget.itemWidget(list_widget.item(row))
        for row in range(list_widget.count())
    ]


def _select_rows(list_widget: Any, rows: list[int]) -> None:
    list_widget.clearSelection()
    list_widget.setCurrentItem(list_widget.item(rows[0]))
    for row in rows:
        list_widget.item(row).setSelected(True)

    list_widget.setFocus(Qt.OtherFocusReason)


def _press_on_thumbnail_strip(app: Any, window: Any, key: Qt.Key) -> None:
    set_qt_active_window(window)
    app.processEvents()
    window.thumbnail_list.setFocus(Qt.OtherFocusReason)
    app.processEvents()
    QTest.keyClick(window.thumbnail_list.viewport(), key)
    app.processEvents()


def test_bracket_keys_rotate_current_photo_and_persist_rotation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify real `]`/`[` keypresses turn the photo and save the rotation.

    The keys must reach the window while the thumbnail strip has focus, turn
    the main viewer and the existing strip card in place, and keep
    ``easy-loupe.json`` free of a rotation entry once the photo is back at 0.
    """
    _theme, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_R100', 'dimgray'), ('IMG_R101', 'blue')],
    )
    strip_widgets = _item_widgets(window.thumbnail_list)

    _press_on_thumbnail_strip(app, window, Qt.Key_BracketRight)

    assert window.library.get_photo('IMG_R100').rotation == 90
    assert window.library.get_photo('IMG_R101').rotation == 0
    assert _read_metadata(tmp_path) == {
        'photos': {'IMG_R100': {'rotation': 90}}
    }
    assert window.viewer.single_viewer.current_rotation() == 90
    assert window.viewer.single_viewer.image_aspect_ratio() < 1
    assert thumbnail_item_widget(window.thumbnail_list, 0).rotation() == 90
    assert _item_widgets(window.thumbnail_list) == strip_widgets

    _press_on_thumbnail_strip(app, window, Qt.Key_BracketLeft)
    _press_on_thumbnail_strip(app, window, Qt.Key_BracketLeft)

    assert window.library.get_photo('IMG_R100').rotation == 270
    assert _read_metadata(tmp_path) == {
        'photos': {'IMG_R100': {'rotation': 270}}
    }

    _press_on_thumbnail_strip(app, window, Qt.Key_BracketRight)

    assert window.library.get_photo('IMG_R100').rotation == 0
    assert _read_metadata(tmp_path) == {'photos': {}}
    assert window.viewer.single_viewer.current_rotation() == 0

    window.close()
    del app


def test_rotation_undo_and_redo_restore_viewer_cards_and_metadata(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify rotation joins the metadata undo history.

    Undo and redo must restore the saved value and visibly turn the viewer
    and cards back, without the list rebuilds that tag edits can trigger.
    """
    _theme, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_R200', 'dimgray')],
    )
    strip_widgets = _item_widgets(window.thumbnail_list)

    window.rotate_actions[1].trigger()
    app.processEvents()

    assert window.undo_metadata_action.isEnabled() is True

    window.undo_metadata_action.trigger()
    app.processEvents()

    assert window.library.get_photo('IMG_R200').rotation == 0
    assert _read_metadata(tmp_path) == {'photos': {}}
    assert window.viewer.single_viewer.current_rotation() == 0
    assert thumbnail_item_widget(window.thumbnail_list, 0).rotation() == 0

    window.redo_metadata_action.trigger()
    app.processEvents()

    assert window.library.get_photo('IMG_R200').rotation == 90
    assert _read_metadata(tmp_path) == {
        'photos': {'IMG_R200': {'rotation': 90}}
    }
    assert window.viewer.single_viewer.current_rotation() == 90
    assert thumbnail_item_widget(window.thumbnail_list, 0).rotation() == 90
    assert _item_widgets(window.thumbnail_list) == strip_widgets

    window.close()
    del app


def test_browse_multi_selection_rotates_every_selected_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify browse rotation applies to the whole selection like tags.

    The hidden main viewer is reloaded on browse exit, so returning with
    Space must show the current photo at its new rotation.
    """
    _theme, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_R300', 'dimgray'),
            ('IMG_R301', 'blue'),
            ('IMG_R302', 'green'),
        ],
    )
    window._enter_browse_mode()
    app.processEvents()
    browse_widgets = _item_widgets(window.browse_list)
    _select_rows(window.browse_list, [0, 1])
    app.processEvents()

    window.rotate_actions[1].trigger()
    app.processEvents()

    assert [photo.rotation for photo in window.library.get_photos()] == [
        90,
        90,
        0,
    ]
    assert [widget.rotation() for widget in browse_widgets] == [90, 90, 0]
    assert _item_widgets(window.browse_list) == browse_widgets

    window._exit_browse_mode(force_fit_photo=True)
    app.processEvents()

    assert window.current_photo_id == 'IMG_R300'
    assert window.viewer.single_viewer.current_rotation() == 90

    window.close()
    del app


def test_compare_rotation_turns_only_the_active_pane_and_undoes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify compare mode rotates only the active compare photo.

    Compare tags already target only the active pane; rotation must follow
    the same rule and stay undoable while compare is open.
    """
    _theme, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_R400', 'dimgray'), ('IMG_R401', 'blue')],
    )
    _select_rows(window.thumbnail_list, [0, 1])
    window._enter_compare_mode()
    app.processEvents()
    window.compare_viewer.move_active_selection(0, 1)
    app.processEvents()

    window.rotate_actions[-1].trigger()
    app.processEvents()

    panes = window.compare_viewer._viewers
    assert window.library.get_photo('IMG_R400').rotation == 0
    assert window.library.get_photo('IMG_R401').rotation == 270
    assert [pane.current_rotation() for pane in panes] == [0, 270]

    window.undo_metadata_action.trigger()
    app.processEvents()

    assert window.library.get_photo('IMG_R401').rotation == 0
    assert [pane.current_rotation() for pane in panes] == [0, 0]

    window.close()
    del app


def test_rotated_scene_cover_turns_stack_and_scene_strip_cards(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify rotating a scene cover updates both strips in place.

    The left strip shows the cover inside a stacked card, while the scene
    strip shows the exact photo, so both cards must turn together.
    """
    _theme, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_R500', 'dimgray'), ('IMG_R501', 'blue')],
        scene_groups=[['IMG_R500', 'IMG_R501']],
    )
    window._populate_thumbnail_list()
    window._populate_scene_list()
    app.processEvents()

    stack_card_before = thumbnail_item_widget(window.thumbnail_list, 0)

    window.rotate_actions[1].trigger()
    window.rotate_actions[1].trigger()
    app.processEvents()

    assert window.library.get_photo('IMG_R500').rotation == 180
    assert window.library.get_photo('IMG_R501').rotation == 0
    stack_card = thumbnail_item_widget(window.thumbnail_list, 0)
    assert stack_card is stack_card_before
    assert stack_card.rotation() == 180
    assert thumbnail_item_widget(window.scene_list, 0).rotation() == 180
    assert thumbnail_item_widget(window.scene_list, 1).rotation() == 0

    window.close()
    del app


def test_saved_rotation_is_shown_after_reopening_the_folder(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify ``easy-loupe.json`` rotation is applied on the next folder load.

    The point of persisting rotation is that a later session shows sideways
    photos upright in the viewer and every thumbnail list.
    """
    photo_specs = [('IMG_R600', 'dimgray'), ('IMG_R601', 'blue')]
    _theme, app, window = create_main_window_with_library(
        tmp_path, monkeypatch, photo_specs=photo_specs
    )
    window.rotate_actions[1].trigger()
    app.processEvents()
    window.close()
    # The helper keeps its preview cache inside the photo folder; drop it so
    # the recursive reload sees only the two photos again.
    shutil.rmtree(tmp_path / '.cache')

    _theme, app, reopened = create_main_window_with_library(
        tmp_path, monkeypatch, photo_specs=photo_specs
    )

    assert reopened.library.get_photo('IMG_R600').rotation == 90
    assert reopened.viewer.single_viewer.current_rotation() == 90
    assert thumbnail_item_widget(reopened.thumbnail_list, 0).rotation() == 90
    assert thumbnail_item_widget(reopened.browse_list, 0).rotation() == 90

    reopened.close()
    del app


def test_rotate_menu_exposes_bracket_shortcuts(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify the rotate actions are discoverable in ``Assign to Photo``.

    Real QAction shortcuts give `]`/`[` the same busy, frozen, and help
    gating as the other assignment keys.
    """
    _theme, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_R700', 'dimgray')],
    )

    assert window.rotate_menu.title() == 'R&otate'
    assert window.rotate_menu.menuAction() in (
        window.assign_photo_menu.actions()
    )
    assert [action.text() for action in window.rotate_menu.actions()] == [
        'Clockwise',
        'Counterclockwise',
    ]
    assert window.rotate_actions[1].shortcut() == QKeySequence(']')
    assert window.rotate_actions[-1].shortcut() == QKeySequence('[')
    assert all(
        action in window._assignment_actions
        for action in window.rotate_actions.values()
    )

    window.close()
    del app
