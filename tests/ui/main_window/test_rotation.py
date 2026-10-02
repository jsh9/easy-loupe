"""
MainWindow tests for view-only photo rotation with ``[`` and ``]``.

Rotation is persisted per photo in ``easy-loupe.json`` and shares the tag
selection, gating, and undo rules, but it must update existing cards and
viewers in place because it never changes list membership or order.
"""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from easy_loupe.core.records import METADATA_FILENAME
from tests.ui._helpers import (
    create_main_window_with_library,
    set_qt_active_window,
    set_scene_detection_result,
    thumbnail_item_widget,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any


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
    Verify real ``]`` and ``[`` keypresses turn the photo and save the
    rotation.

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
    assert window.viewer.single_viewer.get_rotation() == 90
    assert window.viewer.single_viewer.image_aspect_ratio() < 1
    assert thumbnail_item_widget(window.thumbnail_list, 0).get_rotation() == 90
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
    assert window.viewer.single_viewer.get_rotation() == 0

    window.close()
    del app


def test_rotation_undo_and_redo_restore_viewer_cards_and_metadata(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify rotation joins the metadata undo history.

    Undo and redo must restore the saved value and visibly turn the viewer and
    cards back, without the list rebuilds that tag edits can trigger.
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
    assert window.viewer.single_viewer.get_rotation() == 0
    assert thumbnail_item_widget(window.thumbnail_list, 0).get_rotation() == 0

    window.redo_metadata_action.trigger()
    app.processEvents()

    assert window.library.get_photo('IMG_R200').rotation == 90
    assert _read_metadata(tmp_path) == {
        'photos': {'IMG_R200': {'rotation': 90}}
    }
    assert window.viewer.single_viewer.get_rotation() == 90
    assert thumbnail_item_widget(window.thumbnail_list, 0).get_rotation() == 90
    assert _item_widgets(window.thumbnail_list) == strip_widgets

    window.close()
    del app


def test_browse_multi_selection_rotates_every_selected_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify browse rotation applies to the whole selection like tags.

    The hidden main viewer is reloaded on browse exit, so returning with Space
    must show the current photo at its new rotation.
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
    assert [widget.get_rotation() for widget in browse_widgets] == [90, 90, 0]
    assert _item_widgets(window.browse_list) == browse_widgets

    window._exit_browse_mode(force_fit_photo=True)
    app.processEvents()

    assert window.current_photo_id == 'IMG_R300'
    assert window.viewer.single_viewer.get_rotation() == 90

    window.close()
    del app


def test_compare_rotation_turns_only_the_active_pane_and_undoes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify compare mode rotates only the active compare photo.

    Compare tags already target only the active pane; rotation must follow the
    same rule and stay undoable while compare is open.
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
    assert [pane.get_rotation() for pane in panes] == [0, 270]

    window.undo_metadata_action.trigger()
    app.processEvents()

    assert window.library.get_photo('IMG_R401').rotation == 0
    assert [pane.get_rotation() for pane in panes] == [0, 0]

    window.close()
    del app


def test_rotated_scene_cover_turns_stack_and_scene_strip_cards(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify rotating a scene cover updates both strips in place.

    The left strip shows the cover inside a stacked card, while the scene strip
    shows the exact photo, so both cards must turn together.
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
    assert stack_card.get_rotation() == 180
    assert thumbnail_item_widget(window.scene_list, 0).get_rotation() == 180
    assert thumbnail_item_widget(window.scene_list, 1).get_rotation() == 0

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
    assert reopened.viewer.single_viewer.get_rotation() == 90
    assert (
        thumbnail_item_widget(reopened.thumbnail_list, 0).get_rotation() == 90
    )
    assert thumbnail_item_widget(reopened.browse_list, 0).get_rotation() == 90

    reopened.close()
    del app


def test_rotate_menu_exposes_bracket_shortcuts(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify the rotate actions are discoverable in ``Assign to Photo``.

    Real QAction shortcuts give ``]`` and ``[`` the same busy, frozen, and help
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


def test_scene_detection_finish_from_browse_keeps_browse_rotation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify a rotation made in browse survives the scene-detection fit reset.

    Scene detection finishing in browse mode leaves browse through
    ``viewer.set_fit_view()``, which reloads from the viewer's own cached photo
    and rotation rather than ``_display_current_photo``. The hidden viewer must
    already carry the new rotation, or the photo would reappear unrotated while
    its cards show it turned.
    """
    _theme, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_R800', 'dimgray'), ('IMG_R801', 'blue')],
    )
    window._enter_browse_mode()
    app.processEvents()

    window.rotate_actions[1].trigger()
    app.processEvents()
    set_scene_detection_result(window, [['IMG_R800', 'IMG_R801']])
    window._handle_scene_finished()
    app.processEvents()

    assert window._browse_mode is False
    assert window.current_photo_id == 'IMG_R800'
    assert window.library.get_photo('IMG_R800').rotation == 90
    assert window.viewer.single_viewer.get_rotation() == 90
    assert window.viewer.single_viewer.image_aspect_ratio() < 1

    window.close()
    del app


def test_hidden_viewer_turns_only_for_the_photo_it_holds(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify rotation refreshes follow the photo the main viewer holds.

    Browse selection moves ``current_photo_id`` without reloading the hidden
    viewer. Rotating the newly current photo must leave the photo the viewer
    still holds alone, while rotating that held photo must turn it.
    """
    _theme, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_R900', 'dimgray'), ('IMG_R901', 'blue')],
    )
    window._enter_browse_mode()
    app.processEvents()
    _select_rows(window.browse_list, [1])
    app.processEvents()
    assert window.current_photo_id == 'IMG_R901'

    window.rotate_actions[1].trigger()
    app.processEvents()

    assert window.library.get_photo('IMG_R901').rotation == 90
    assert window.viewer.single_viewer.get_rotation() == 0

    _select_rows(window.browse_list, [0])
    app.processEvents()
    window.rotate_actions[1].trigger()
    app.processEvents()

    assert window.library.get_photo('IMG_R900').rotation == 90
    assert window.viewer.single_viewer.get_rotation() == 90

    window.close()
    del app


def _fail_metadata_save() -> None:
    raise PermissionError(13, 'Permission denied')


@pytest.mark.parametrize(
    'action',
    ['rotate', 'rating', 'undo'],
    ids=['rotate', 'rating', 'undo-rotation'],
)
def test_failed_metadata_save_still_updates_display_and_warns(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    """
    Verify read-only metadata saves keep the screen in sync and warn.

    On a read-only card or share ``save_metadata`` raises ``OSError``. Edits
    already applied in memory must still refresh the viewer, cards, and labels
    and stay undoable, with a warning that they apply to this session only,
    instead of the error escaping the Qt slot halfway through.
    """
    _theme, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_RA00', 'dimgray')],
    )
    if action == 'undo':
        window.rotate_actions[1].trigger()
        app.processEvents()

    monkeypatch.setattr(window.library, 'save_metadata', _fail_metadata_save)
    if action == 'rotate':
        window.rotate_actions[1].trigger()
    elif action == 'rating':
        window.rating_actions[4].trigger()
    else:
        window.undo_metadata_action.trigger()

    app.processEvents()

    photo = window.library.get_photo('IMG_RA00')
    card = thumbnail_item_widget(window.thumbnail_list, 0)
    if action == 'rating':
        assert photo.rating == 4
        assert '★★★★☆' in card.meta_label.text()
        assert window._metadata_undo_stack
    else:
        expected_rotation = 90 if action == 'rotate' else 0
        assert photo.rotation == expected_rotation
        assert window.viewer.single_viewer.get_rotation() == expected_rotation
        assert card.get_rotation() == expected_rotation
        history = (
            window._metadata_undo_stack
            if action == 'rotate'
            else window._metadata_redo_stack
        )
        assert len(history) == 1

    assert window.transient_message_overlay.isVisible() is True
    warning = window.transient_message_label.text()
    assert f'Could not save {METADATA_FILENAME}' in warning
    assert 'Permission denied' in warning
    assert 'this session only' in warning

    window.close()
    del app
