from __future__ import annotations

import json
from pathlib import Path
from typing import Never

import pytest
from PySide6.QtCore import Qt, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

import easy_cull.ui.main_window.window as main_window_module
import easy_cull.ui.main_window.workflows as workflows_module
import easy_cull.ui.theme as theme_module
from easy_cull.core.records import METADATA_FILENAME
from easy_cull.operations.common import OperationSummary, UndoPlan
from easy_cull.operations.export import OrganizeFilesOptions
from easy_cull.operations.xmp import WriteXmpOptions
from easy_cull.ui.main_window.dialogs import OrganizerDialogResult
from tests.ui._helpers import (
    assert_choose_folder_idle,
    create_jpeg,
    create_main_window_with_library,
    record_fit_view_calls,
    set_scene_detection_result,
    stub_read_exif,
    thumbnail_item_widget,
)


def _list_widget_has_focus(app: QApplication, list_widget: object) -> bool:
    focus_widget = app.focusWidget()
    return focus_widget in {list_widget, list_widget.viewport()}


def test_main_window_sets_color_label_and_saves_metadata() -> None:
    class FakeLibrary:
        def __init__(self) -> None:
            self.update_calls: list[tuple[str, str | None, set[str]]] = []
            self.saved = False

        def update_metadata(
                self,
                photo_id: str,
                *,
                color_label: str | None,
                fields: set[str],
        ) -> None:
            self.update_calls.append((photo_id, color_label, fields))

        def save_metadata(self) -> None:
            self.saved = True

    class FakeWindow:
        def __init__(self) -> None:
            self.current_photo_id = 'IMG_7100'
            self.library = FakeLibrary()
            self.refreshed = False

        def _after_metadata_change(self) -> None:
            self.refreshed = True

    fake_window = FakeWindow()

    main_window_module.MainWindow._set_color_label(fake_window, 'green')

    assert fake_window.library.update_calls == [
        ('IMG_7100', 'green', {'color_label'})
    ]
    assert fake_window.library.saved is True
    assert fake_window.refreshed is True


def test_main_window_show_event_triggers_initial_folder_prompt_once() -> None:
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()

    choose_calls: list[str] = []
    window.choose_folder = lambda: choose_calls.append('choose')

    window.show()
    app.processEvents()
    app.processEvents()

    assert choose_calls == ['choose']
    assert window._initial_folder_prompt_pending is False

    window.close()
    del app


@pytest.mark.parametrize(
    ('dialog_result', 'load_behavior', 'expected_errors'),
    [
        pytest.param('', 'unused', [], id='folder-dialog-cancel'),
        pytest.param(
            'selected-folder',
            'raise',
            [('Failed to Open Folder', 'boom')],
            id='folder-load-failure',
        ),
    ],
)
def test_main_window_choose_folder_cancel_and_failure_paths_restore_ui(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        dialog_result: str,
        load_behavior: str,
        expected_errors: list[tuple[str, str]],
) -> None:
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    monkeypatch.setattr(
        QFileDialog,
        'getExistingDirectory',
        lambda *_args, **_kwargs: (
            '' if dialog_result == '' else str(tmp_path / dialog_result)
        ),
    )

    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        'critical',
        lambda _parent, title, text: errors.append((title, text)),
    )

    if load_behavior == 'raise':

        def fail_load_folder(
                _folder: Path, *, progress_callback: object | None = None
        ) -> Never:
            del progress_callback
            raise RuntimeError('boom')

        monkeypatch.setattr(window.library, 'load_folder', fail_load_folder)

    window.choose_folder()

    assert errors == expected_errors
    assert_choose_folder_idle(window)
    assert window.open_button.isEnabled() is True
    assert window.detect_button.isEnabled() is False

    window.close()
    del app


def test_main_window_detect_scenes_starts_worker_thread_and_sets_busy_state(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_7400', 'dimgray'), ('IMG_7401', 'blue')],
    )
    started: list[str] = []
    monkeypatch.setattr(
        QThread,
        'start',
        lambda self: started.append(self.objectName() or 'started'),
    )

    window.detect_scenes()

    assert started == ['started']
    assert window._scene_thread is not None
    assert window._scene_worker is not None
    assert window._busy is True
    assert window.progress_overlay.isVisible() is True

    window.close()
    del app


def test_main_window_progress_overlay_disables_and_restores_interaction(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify progress overlays disable and then restore interactive controls.

    This is necessary because long-running workflows temporarily disable the
    main UI, and every focusable top-bar control must follow that busy state so
    keyboard focus does not jump to a still-enabled control behind the overlay.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_7410', 'dimgray')],
    )
    window.activateWindow()
    window.raise_()
    app.processEvents()

    window.thumbnail_list.setFocus(Qt.OtherFocusReason)
    app.processEvents()

    window._show_progress('Loading', 50)

    assert window._busy is True
    assert app.focusWidget() is not window.show_af_point_toggle
    assert window.menuBar().isEnabled() is False
    assert window.open_button.isEnabled() is False
    assert window.organize_button.isEnabled() is False
    assert window.theme_toggle.isEnabled() is False
    assert window.show_af_point_toggle.isEnabled() is False
    assert all(
        action.isEnabled() is False for action in window._assignment_actions
    )
    assert window.organize_action.isEnabled() is False

    window._hide_progress()

    assert window._busy is False
    assert window.menuBar().isEnabled() is True
    assert window.open_button.isEnabled() is True
    assert window.organize_button.isEnabled() is True
    assert window.theme_toggle.isEnabled() is True
    assert window.show_af_point_toggle.isEnabled() is True
    assert all(
        action.isEnabled() is True for action in window._assignment_actions
    )
    assert window.organize_action.isEnabled() is True

    window._show_progress('Re-rendering comparison grid...', 0, show_bar=False)

    assert window._busy is True
    assert window.progress_overlay.isVisible() is True
    assert window.overlay_message_label.text() == (
        'Re-rendering comparison grid...'
    )
    assert window.overlay_progress_bar.isVisible() is False

    window._hide_progress()

    assert window._busy is False
    assert window.progress_overlay.isHidden() is True

    window._show_progress('Loading again', 50)

    assert window.overlay_progress_bar.isVisible() is True

    window._hide_progress()

    window.close()
    del app


def test_main_window_handle_scene_failed_and_clear_worker_restore_ui(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_7420', 'dimgray')],
    )
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        'critical',
        lambda _parent, title, text: errors.append((title, text)),
    )
    window._scene_thread = object()
    window._scene_worker = object()
    window._show_progress('Preparing scenes', 10)

    window._handle_scene_failed('boom')

    assert errors == [('Scene Detection Failed', 'boom')]
    assert window._busy is False
    assert window.progress_overlay.isHidden() is True
    assert window.detect_button.isEnabled() is True
    assert window.organize_button.isEnabled() is False

    window._clear_scene_worker()

    assert window._scene_thread is None
    assert window._scene_worker is None
    assert window.detect_button.isEnabled() is True
    assert window.organize_button.isEnabled() is True

    window.close()
    del app


def test_main_window_assignment_actions_update_metadata_and_persist_changes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _desktop_app, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_7500', 'dimgray')],
    )

    photo = window.library.get_photo('IMG_7500')

    window.rating_actions[5].trigger()
    window.color_label_actions['purple'].trigger()
    window.flag_actions['picked'].trigger()
    app.processEvents()

    assert photo.rating == 5
    assert photo.color_label == 'purple'
    assert photo.flag == 'picked'
    assert '★★★★★' in window.metadata_label.text()
    assert (
        theme_module.COLOR_LABEL_SWATCHES['purple']
        in window.metadata_label.text()
    )
    assert '✅' in window.metadata_label.text()
    assert json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    ) == {
        'IMG_7500': {
            'rating': 5,
            'color_label': 'purple',
            'flag': 'picked',
        }
    }

    window.rating_actions[None].trigger()
    window.color_label_actions[None].trigger()
    window.flag_actions[None].trigger()
    app.processEvents()

    assert photo.rating is None
    assert photo.color_label is None
    assert photo.flag is None
    assert (
        json.loads((tmp_path / METADATA_FILENAME).read_text(encoding='utf-8'))
        == {}
    )
    assert (
        window.metadata_label.text()
        == f'Metadata: {theme_module.NO_METADATA_TEXT}'
    )

    window.close()
    del app


def test_backtick_shortcut_clears_color_label_from_runtime_keypress(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _desktop_app, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_7510', 'dimgray')],
    )

    photo = window.library.get_photo('IMG_7510')
    window._set_color_label('green')
    app.processEvents()
    assert photo.color_label == 'green'

    window.activateWindow()
    window.raise_()
    app.processEvents()
    window.thumbnail_list.setFocus(Qt.OtherFocusReason)
    app.processEvents()
    QTest.keyClick(window.thumbnail_list.viewport(), Qt.Key_QuoteLeft)
    app.processEvents()

    assert photo.color_label is None
    assert (
        json.loads((tmp_path / METADATA_FILENAME).read_text(encoding='utf-8'))
        == {}
    )
    assert (
        window.metadata_label.text()
        == f'Metadata: {theme_module.NO_METADATA_TEXT}'
    )

    window.close()
    del app


def test_metadata_tagging_preserves_thumbnail_strip_scroll_position(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Guard against metadata refreshes turning tagging into a scroll jump.

    Tagging a photo in the main view rebuilds the left thumbnail strip so the
    metadata badges can update immediately. Before the fix, that rebuild also
    reselected the current item with ``scrollToItem()``, which moved the
    viewport and pushed the tagged thumbnail to the bottom of the visible
    strip. That behavior was jarring because tagging is an in-place metadata
    action, not a navigation action.

    This test keeps enough rows in the strip to require scrolling, tags a photo
    away from the top of the list, and asserts that the selected photo and
    vertical scrollbar value are unchanged after the refresh. It ensures future
    UI refactors preserve the user's visual position while still updating
    thumbnail metadata immediately.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[(f'IMG_{index:04d}', 'dimgray') for index in range(30)],
    )
    window.resize(1200, 800)
    app.processEvents()

    target_row = 12
    window.thumbnail_list.setCurrentRow(target_row)
    app.processEvents()

    scrollbar = window.thumbnail_list.verticalScrollBar()
    assert scrollbar.maximum() > 0
    before_scroll = scrollbar.value()
    before_widget = thumbnail_item_widget(window.thumbnail_list, target_row)
    before_height = before_widget.height()
    before_name_top = before_widget.name_label.geometry().top()

    window.flag_actions['picked'].trigger()
    app.processEvents()

    after_widget = thumbnail_item_widget(window.thumbnail_list, target_row)

    assert window.current_photo_id == f'IMG_{target_row:04d}'
    assert window.thumbnail_list.currentRow() == target_row
    assert scrollbar.value() == before_scroll
    assert after_widget.height() == before_height
    assert after_widget.name_label.geometry().top() == before_name_top

    window.close()
    del app


def test_metadata_tagging_preserves_browse_grid_scroll_position(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Guard against browse-grid tagging forcing the selected row to shift.

    Browse mode rebuilds the full photo grid after metadata changes so rating,
    color-label, and flag badges stay in sync. The original bug caused that
    rebuild to scroll the selected item back into view as if the user had just
    navigated to it, which shifted the whole grid and often pulled the tagged
    row down toward the bottom of the viewport.

    This test creates a scrollable browse grid, positions the current photo in
    a mid-list visible row, triggers a metadata update, and verifies both the
    selection and the browse scrollbar value remain stable. That makes the
    expected contract explicit: metadata tagging in browse mode must be a
    no-movement refresh rather than an implicit scroll operation.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[(f'IMG_{index:04d}', 'dimgray') for index in range(80)],
    )
    window.resize(760, 640)
    app.processEvents()

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()
    app.processEvents()

    target_row = 40
    window.browse_list.setCurrentRow(target_row)
    app.processEvents()
    app.processEvents()

    scrollbar = window.browse_list.verticalScrollBar()
    assert scrollbar.maximum() > 0
    # Position the current item near the vertical center of the viewport.
    # ``setCurrentRow`` uses EnsureVisible, which can land the item at any
    # edge depending on the previous scroll position and platform DPI.
    # Computing the exact scrollbar adjustment removes the platform
    # dependency that broke earlier hardcoded / fractional offsets on
    # Windows CI runners.
    item_rect = window.browse_list.visualItemRect(
        window.browse_list.currentItem(),
    )
    viewport_h = window.browse_list.viewport().height()
    desired_y = (viewport_h - item_rect.height()) // 3
    shift = item_rect.y() - desired_y
    scrollbar.setValue(
        max(0, min(scrollbar.value() + shift, scrollbar.maximum())),
    )
    app.processEvents()
    app.processEvents()

    current_item = window.browse_list.currentItem()
    assert current_item is not None
    current_rect = window.browse_list.visualItemRect(current_item)
    assert 0 <= current_rect.y() < window.browse_list.viewport().height()
    before_scroll = scrollbar.value()
    before_grid_size = window.browse_list.gridSize()
    before_widget = thumbnail_item_widget(window.browse_list, target_row)
    before_height = before_widget.height()
    before_name_top = before_widget.name_label.geometry().top()

    window.rating_actions[5].trigger()
    app.processEvents()
    app.processEvents()

    after_widget = thumbnail_item_widget(window.browse_list, target_row)

    assert window._browse_mode is True
    assert window.current_photo_id == f'IMG_{target_row:04d}'
    assert window.browse_list.currentRow() == target_row
    assert scrollbar.value() == before_scroll
    assert window.browse_list.gridSize() == before_grid_size
    assert after_widget.height() == before_height
    assert after_widget.name_label.geometry().top() == before_name_top

    window.close()
    del app


def test_scene_mode_tagging_preserves_scene_card_heights(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_5000', 'dimgray'),
            ('IMG_5001', 'green'),
            ('IMG_5002', 'blue'),
        ],
        scene_groups=[['IMG_5000', 'IMG_5001'], ['IMG_5002']],
    )

    stacked_before = thumbnail_item_widget(window.thumbnail_list, 0)
    scene_before = thumbnail_item_widget(window.scene_list, 0)
    stacked_before_height = stacked_before.height()
    scene_before_height = scene_before.height()
    scene_before_name_top = scene_before.name_label.geometry().top()
    stacked_before_text = stacked_before.name_label.parentWidget()
    assert stacked_before_text is not None
    stacked_before_text_height = stacked_before_text.height()

    window.rating_actions[4].trigger()
    app.processEvents()

    stacked_after = thumbnail_item_widget(window.thumbnail_list, 0)
    scene_after = thumbnail_item_widget(window.scene_list, 0)

    assert stacked_after.height() == stacked_before_height
    assert scene_after.height() == scene_before_height
    assert stacked_after.meta_label.isVisible() is False
    assert scene_after.meta_label.isVisible() is True
    assert scene_after.name_label.geometry().top() == scene_before_name_top
    stacked_after_text = stacked_after.name_label.parentWidget()
    assert stacked_after_text is not None
    assert stacked_after_text.height() == stacked_before_text_height

    window.close()
    del app


def test_main_window_choose_folder_success_populates_ui(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Successful folder loads should focus the strip for immediate Down
    navigation.
    """
    create_jpeg(tmp_path / 'IMG_9080.JPG', 'dimgray')
    create_jpeg(tmp_path / 'IMG_9081.JPG', 'blue')
    stub_read_exif(monkeypatch, {})
    monkeypatch.setattr(
        QFileDialog,
        'getExistingDirectory',
        lambda *_args, **_kwargs: str(tmp_path),
    )

    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.show()
    app.processEvents()

    window.choose_folder()
    app.processEvents()
    window.activateWindow()
    window.raise_()
    app.processEvents()

    assert window.library.current_folder == tmp_path.resolve()
    assert len(window.library.photos) == 2
    assert window.current_photo_id == 'IMG_9080'
    assert window.thumbnail_list.count() == 2
    assert window.browse_list.count() == 2
    assert window._busy is False
    assert window.progress_overlay.isHidden() is True
    assert window.detect_button.isEnabled() is True
    assert window.organize_button.isEnabled() is True
    assert str(tmp_path.resolve()) in window.folder_label.text()
    assert _list_widget_has_focus(app, window.thumbnail_list) is True

    focus_widget = app.focusWidget()
    assert focus_widget is not None
    QTest.keyClick(focus_widget, Qt.Key_Down)
    app.processEvents()

    assert window.current_photo_id == 'IMG_9081'
    assert window.thumbnail_list.currentRow() == 1

    window.close()
    del app


@pytest.mark.parametrize(
    ('action_key', 'expected_rating', 'expected_stars'),
    [
        pytest.param(1, 1, '★☆☆☆☆', id='key-1'),
        pytest.param(2, 2, '★★☆☆☆', id='key-2'),
        pytest.param(3, 3, '★★★☆☆', id='key-3'),
        pytest.param(4, 4, '★★★★☆', id='key-4'),
        pytest.param(5, 5, '★★★★★', id='key-5'),
    ],
)
def test_rating_shortcut_assigns_correct_value(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        action_key: int,
        expected_rating: int,
        expected_stars: str,
) -> None:
    _desktop_app, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_K100', 'dimgray')],
    )

    photo = window.library.get_photo('IMG_K100')

    window.rating_actions[action_key].trigger()
    app.processEvents()

    assert photo.rating == expected_rating
    assert expected_stars in window.metadata_label.text()
    saved = json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )
    assert saved['IMG_K100']['rating'] == expected_rating

    window.close()
    del app


def test_rating_clear_shortcut_removes_rating(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _desktop_app, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_K110', 'dimgray')],
    )

    photo = window.library.get_photo('IMG_K110')

    window.rating_actions[3].trigger()
    app.processEvents()

    assert photo.rating == 3
    assert '★★★☆☆' in window.metadata_label.text()

    window.rating_actions[None].trigger()
    app.processEvents()

    assert photo.rating is None
    assert '★' not in window.metadata_label.text()
    saved = json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )
    assert saved == {}

    window.close()
    del app


@pytest.mark.parametrize(
    ('action_key', 'expected_label'),
    [
        pytest.param('red', 'red', id='key-6-red'),
        pytest.param('yellow', 'yellow', id='key-7-yellow'),
        pytest.param('green', 'green', id='key-8-green'),
        pytest.param('blue', 'blue', id='key-9-blue'),
    ],
)
def test_color_label_shortcut_assigns_correct_value(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        action_key: str,
        expected_label: str,
) -> None:
    theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_K200', 'dimgray')],
    )

    photo = window.library.get_photo('IMG_K200')

    window.color_label_actions[action_key].trigger()
    app.processEvents()

    assert photo.color_label == expected_label
    assert '●' in window.metadata_label.text()
    assert (
        theme_module.COLOR_LABEL_SWATCHES[expected_label]
        in window.metadata_label.text()
    )
    saved = json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )
    assert saved['IMG_K200']['color_label'] == expected_label

    window.close()
    del app


def test_color_label_clear_shortcut_removes_label(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _desktop_app, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_K210', 'dimgray')],
    )

    photo = window.library.get_photo('IMG_K210')

    window.color_label_actions['green'].trigger()
    app.processEvents()

    assert photo.color_label == 'green'
    assert '●' in window.metadata_label.text()

    window.color_label_actions[None].trigger()
    app.processEvents()

    assert photo.color_label is None
    assert '●' not in window.metadata_label.text()
    saved = json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )
    assert saved == {}

    window.close()
    del app


@pytest.mark.parametrize(
    ('action_key', 'expected_flag', 'expected_symbol'),
    [
        pytest.param('picked', 'picked', '✅', id='key-P-pick'),
        pytest.param('rejected', 'rejected', '❌', id='key-X-reject'),
    ],
)
def test_flag_shortcut_assigns_correct_value(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        action_key: str,
        expected_flag: str,
        expected_symbol: str,
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_K300', 'dimgray')],
    )

    photo = window.library.get_photo('IMG_K300')

    window.flag_actions[action_key].trigger()
    app.processEvents()

    assert photo.flag == expected_flag
    assert expected_symbol in window.metadata_label.text()
    saved = json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )
    assert saved['IMG_K300']['flag'] == expected_flag

    window.close()
    del app


def test_flag_clear_shortcut_removes_flag(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_K310', 'dimgray')],
    )

    photo = window.library.get_photo('IMG_K310')

    window.flag_actions['picked'].trigger()
    app.processEvents()

    assert photo.flag == 'picked'
    assert '✅' in window.metadata_label.text()

    window.flag_actions[None].trigger()
    app.processEvents()

    assert photo.flag is None
    assert '✅' not in window.metadata_label.text()
    assert '❌' not in window.metadata_label.text()
    saved = json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )
    assert saved == {}

    window.close()
    del app


@pytest.mark.parametrize(
    ('category', 'action_key', 'field', 'expected'),
    [
        pytest.param('rating', 1, 'rating', 1, id='menu-rating-1'),
        pytest.param('rating', 2, 'rating', 2, id='menu-rating-2'),
        pytest.param('rating', 3, 'rating', 3, id='menu-rating-3'),
        pytest.param('rating', 4, 'rating', 4, id='menu-rating-4'),
        pytest.param('rating', 5, 'rating', 5, id='menu-rating-5'),
        pytest.param(
            'color_label',
            'red',
            'color_label',
            'red',
            id='menu-color-red',
        ),
        pytest.param(
            'color_label',
            'yellow',
            'color_label',
            'yellow',
            id='menu-color-yellow',
        ),
        pytest.param(
            'color_label',
            'green',
            'color_label',
            'green',
            id='menu-color-green',
        ),
        pytest.param(
            'color_label',
            'blue',
            'color_label',
            'blue',
            id='menu-color-blue',
        ),
        pytest.param(
            'color_label',
            'purple',
            'color_label',
            'purple',
            id='menu-color-purple',
        ),
        pytest.param(
            'flag',
            'picked',
            'flag',
            'picked',
            id='menu-flag-pick',
        ),
        pytest.param(
            'flag',
            'rejected',
            'flag',
            'rejected',
            id='menu-flag-reject',
        ),
    ],
)
def test_menu_action_assigns_correct_metadata_value(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        category: str,
        action_key: int | str,
        field: str,
        expected: int | str,
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_M100', 'dimgray')],
    )

    photo = window.library.get_photo('IMG_M100')
    actions = getattr(window, f'{category}_actions')
    actions[action_key].trigger()
    app.processEvents()

    assert getattr(photo, field) == expected
    saved = json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )
    assert saved['IMG_M100'][field] == expected

    window.close()
    del app


@pytest.mark.parametrize(
    ('category', 'set_key', 'field'),
    [
        pytest.param('rating', 3, 'rating', id='menu-clear-rating'),
        pytest.param(
            'color_label',
            'green',
            'color_label',
            id='menu-clear-color',
        ),
        pytest.param('flag', 'picked', 'flag', id='menu-clear-flag'),
    ],
)
def test_menu_clear_action_removes_metadata_value(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        category: str,
        set_key: int | str,
        field: str,
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_M200', 'dimgray')],
    )

    photo = window.library.get_photo('IMG_M200')
    actions = getattr(window, f'{category}_actions')

    actions[set_key].trigger()
    app.processEvents()
    assert getattr(photo, field) is not None

    actions[None].trigger()
    app.processEvents()
    assert getattr(photo, field) is None
    saved = json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )
    assert saved == {}

    window.close()
    del app


@pytest.mark.parametrize(
    (
        'photo_specs',
        'enter_browse_mode',
        'expected_fit_call_count',
        'expected_viewer_mode',
        'expected_split_view',
        'assert_manual_restore',
    ),
    [
        pytest.param(
            [
                ('IMG_8200', 'dimgray'),
                ('IMG_8201', 'green'),
                ('IMG_8202', 'blue'),
            ],
            True,
            1,
            'single-fit',
            False,
            False,
            id='finish-from-browse',
        ),
        pytest.param(
            [
                ('IMG_8210', 'dimgray'),
                ('IMG_8211', 'green'),
                ('IMG_8212', 'blue'),
            ],
            False,
            0,
            'split',
            True,
            True,
            id='finish-in-split',
        ),
    ],
)
def test_main_window_scene_detection_finish_updates_view_mode_by_entry_state(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        photo_specs: list[tuple[str, str]],
        enter_browse_mode: bool,
        expected_fit_call_count: int,
        expected_viewer_mode: str,
        expected_split_view: bool,
        assert_manual_restore: bool,
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=photo_specs,
    )

    fit_view_calls = record_fit_view_calls(window)
    remembered_scale: float | None = None
    remembered_center: tuple[float, float] | None = None

    if enter_browse_mode:
        window.split_mode_shortcut.activated.emit()
        app.processEvents()
        window.browse_mode_shortcut.activated.emit()
        app.processEvents()
    else:
        window.split_mode_shortcut.activated.emit()
        app.processEvents()
        window.viewer.zoom_step(1.25)
        window.viewer.pan_by(30, -20)
        remembered_scale = window.viewer._current_scale
        remembered_center = window.viewer.normalized_viewport_center()

    set_scene_detection_result(
        window,
        [
            [photo_specs[0][0], photo_specs[1][0]],
            [photo_specs[2][0]],
        ],
    )

    window._handle_scene_finished()
    app.processEvents()

    assert window._browse_mode is False
    assert window.current_photo_id == photo_specs[0][0]
    assert window.browse_list.isVisible() is False
    assert window.content_splitter.isVisible() is True
    assert window.scene_list.isVisible() is True
    assert window.thumbnail_list.count() == 2
    assert window.scene_list.count() == 2
    assert len(fit_view_calls) == expected_fit_call_count
    assert window.viewer._mode == expected_viewer_mode
    assert window.viewer.is_split_view() is expected_split_view

    if assert_manual_restore:
        assert remembered_scale is not None
        assert remembered_center is not None
        assert window.viewer._current_scale == pytest.approx(remembered_scale)
        assert window.viewer.normalized_viewport_center() == pytest.approx(
            remembered_center
        )

    window.close()
    del app


def test_scene_detection_finish_restores_thumbnail_strip_focus(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify scene detection returns focus to the vertical thumbnail strip.

    This covers the completion path that rebuilds the strip into scene stacks
    while preserving the current photo's represented row. The regression test
    is necessary because the newly visible scene strip and re-enabled top-bar
    controls can otherwise steal focus after the progress overlay is dismissed.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8210', 'dimgray'),
            ('IMG_8211', 'green'),
            ('IMG_8212', 'blue'),
        ],
    )
    window.activateWindow()
    window.raise_()
    app.processEvents()

    window.thumbnail_list.setCurrentRow(1)
    window.thumbnail_list.setFocus(Qt.OtherFocusReason)
    app.processEvents()

    assert window.current_photo_id == 'IMG_8211'
    assert _list_widget_has_focus(app, window.thumbnail_list) is True

    set_scene_detection_result(
        window,
        [
            ['IMG_8210'],
            ['IMG_8211', 'IMG_8212'],
        ],
    )

    # Start from the user workflow: a non-first photo is selected and the
    # vertical strip owns keyboard focus before scene detection starts.
    window._scene_thread = object()
    window._handle_scene_finished()
    app.processEvents()

    assert window.thumbnail_list.count() == 2
    assert window.thumbnail_list.currentRow() == 1

    # The real restore opportunity happens after the worker thread is cleared;
    # before that, background-task guards intentionally block focus changes.
    window._clear_scene_worker()
    app.processEvents()

    assert _list_widget_has_focus(app, window.thumbnail_list) is True
    assert app.focusWidget() is not window.theme_toggle
    assert app.focusWidget() is not window.show_af_point_toggle
    assert window.current_photo_id == 'IMG_8211'
    assert window.thumbnail_list.currentRow() == 1

    window.close()
    del app


def test_main_window_open_organizer_dialog_starts_operation_worker(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9100', 'dimgray')],
    )

    class FakeDialog:
        DialogCode = type('DialogCode', (), {'Accepted': 1})

        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        @staticmethod
        def exec() -> int:
            return 1

        @staticmethod
        def selected_result() -> OrganizerDialogResult:
            return OrganizerDialogResult(
                mode='reorganize',
                organize_options=OrganizeFilesOptions(
                    criterion='flag',
                    action='copy',
                    output_parent=tmp_path,
                    include_untagged=False,
                    conflict_policy='fail',
                ),
            )

    started: list[str] = []
    monkeypatch.setattr(workflows_module, 'OrganizerDialog', FakeDialog)
    monkeypatch.setattr(
        QThread,
        'start',
        lambda self: started.append(self.objectName() or 'started'),
    )

    window.open_organizer_dialog()

    assert started == ['started']
    assert window._operation_thread is not None
    assert window._operation_worker is not None
    assert window._busy is True
    assert window.progress_overlay.isVisible() is True

    window.close()
    del app


def test_main_window_finished_dialog_uses_expected_title_and_undo_button(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9190', 'dimgray')],
    )
    captured: dict[str, object] = {}

    def fake_exec(message_box: QMessageBox) -> int:
        captured['title'] = message_box.windowTitle()
        captured['text'] = message_box.text()
        captured['buttons'] = [
            button.text() for button in message_box.buttons()
        ]
        message_box._clicked_button = next(
            button
            for button in message_box.buttons()
            if button.text() == 'Undo'
        )
        return 0

    monkeypatch.setattr(QMessageBox, 'exec', fake_exec)
    monkeypatch.setattr(
        QMessageBox,
        'clickedButton',
        lambda message_box: getattr(message_box, '_clicked_button', None),
    )

    should_undo = window._show_operation_finished_dialog(
        OperationSummary(processed_photos=1, moved_files=2),
        OrganizerDialogResult(
            mode='reorganize',
            organize_options=OrganizeFilesOptions(
                criterion='flag',
                action='move',
                output_parent=tmp_path,
                include_untagged=False,
                conflict_policy='fail',
            ),
        ),
    )

    assert should_undo is True
    assert captured['title'] in {'', 'Photo Organization Finished'}
    assert captured['text'] == 'Photo Organization Finished'
    assert 'Undo' in captured['buttons']
    assert 'Close' in captured['buttons']

    window.close()
    del app


def test_main_window_operation_finished_after_move_reloads_folder_and_shows_dialog(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9200', 'dimgray')],
    )
    reload_calls: list[str] = []
    dialog_calls: list[
        tuple[OperationSummary, OrganizerDialogResult | None]
    ] = []
    monkeypatch.setattr(
        window,
        '_reload_current_folder_after_move',
        lambda: reload_calls.append('reload'),
    )
    monkeypatch.setattr(
        window,
        '_show_operation_finished_dialog',
        lambda summary, request: (
            dialog_calls.append((summary, request)) or False
        ),
    )
    window._operation_kind = 'run'
    window._organizer_request = OrganizerDialogResult(
        mode='reorganize',
        organize_options=OrganizeFilesOptions(
            criterion='flag',
            action='move',
            output_parent=tmp_path,
            include_untagged=False,
            conflict_policy='fail',
        ),
    )
    window._show_progress('Organizing', 50)

    window._handle_operation_finished(
        OperationSummary(
            processed_photos=1,
            moved_files=2,
            undo_plan=UndoPlan(),
        )
    )

    assert reload_calls == ['reload']
    assert window._busy is False
    assert window._operation_kind is None
    assert len(dialog_calls) == 1
    assert dialog_calls[0][0].moved_files == 2
    assert dialog_calls[0][1] is not None
    assert dialog_calls[0][1].mode == 'reorganize'

    window.close()
    del app


def test_main_window_xmp_operation_finished_shows_dialog_without_reload(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9300', 'dimgray')],
    )
    reload_calls: list[str] = []
    dialog_calls: list[
        tuple[OperationSummary, OrganizerDialogResult | None]
    ] = []
    monkeypatch.setattr(
        window,
        '_reload_current_folder_after_move',
        lambda: reload_calls.append('reload'),
    )
    monkeypatch.setattr(
        window,
        '_show_operation_finished_dialog',
        lambda summary, request: (
            dialog_calls.append((summary, request)) or False
        ),
    )
    window._operation_kind = 'run'
    window._organizer_request = OrganizerDialogResult(
        mode='xmp',
        xmp_options=WriteXmpOptions(merge_policy='preserve'),
    )
    window._show_progress('Writing XMP', 50)

    window._handle_operation_finished(
        OperationSummary(
            processed_photos=1,
            written_sidecars=1,
            undo_plan=UndoPlan(),
        )
    )

    assert reload_calls == []
    assert window._busy is False
    assert len(dialog_calls) == 1
    assert dialog_calls[0][0].written_sidecars == 1
    assert dialog_calls[0][1] is not None
    assert dialog_calls[0][1].mode == 'xmp'

    window.close()
    del app


def test_main_window_operation_finished_with_undo_starts_worker_immediately(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9310', 'dimgray')],
    )
    started: list[str] = []
    monkeypatch.setattr(
        window,
        '_show_operation_finished_dialog',
        lambda _summary, _request: True,
    )
    finished_thread = QThread(window)
    monkeypatch.setattr(
        QThread,
        'start',
        lambda self: started.append(self.objectName() or 'started'),
    )
    window._operation_thread = finished_thread
    window._operation_kind = 'run'
    window._organizer_request = OrganizerDialogResult(
        mode='reorganize',
        organize_options=OrganizeFilesOptions(
            criterion='flag',
            action='copy',
            output_parent=tmp_path,
            include_untagged=False,
            conflict_policy='fail',
        ),
    )
    window._show_progress('Organizing', 50)
    undo_plan = UndoPlan()

    window._handle_operation_finished(
        OperationSummary(
            processed_photos=1, copied_files=2, undo_plan=undo_plan
        )
    )

    assert started == ['started']
    assert window._operation_kind == 'undo'
    assert window._busy is True
    assert window.progress_overlay.isVisible() is True
    assert window._operation_thread is not finished_thread

    window._clear_operation_worker(finished_thread, None)

    assert window._operation_kind == 'undo'
    assert window._operation_thread is not None

    window.close()
    del app


def test_main_window_undo_finished_reloads_folder_and_shows_confirmation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9320', 'dimgray')],
    )
    reload_calls: list[str] = []
    info_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        window,
        '_reload_current_folder_after_undo',
        lambda: reload_calls.append('reload'),
    )
    monkeypatch.setattr(
        QMessageBox,
        'information',
        lambda _parent, title, text: info_calls.append((title, text)),
    )
    window._operation_kind = 'undo'
    window._show_progress('Undoing', 50)

    window._handle_operation_finished(None)

    assert reload_calls == ['reload']
    assert window._busy is False
    assert window._operation_kind is None
    assert info_calls == [
        (
            'Undo Complete',
            'The last photo organization operation was undone.',
        )
    ]

    window.close()
    del app


@pytest.mark.parametrize(
    ('operation_request', 'expected_title'),
    [
        pytest.param(
            OrganizerDialogResult(
                mode='reorganize',
                organize_options=OrganizeFilesOptions(
                    criterion='flag',
                    action='copy',
                    output_parent=Path('/tmp'),
                    include_untagged=False,
                    conflict_policy='fail',
                ),
            ),
            'Organize Photos Failed',
            id='reorganize-failure',
        ),
        pytest.param(
            OrganizerDialogResult(
                mode='xmp',
                xmp_options=WriteXmpOptions(merge_policy='preserve'),
            ),
            'Write XMP Failed',
            id='xmp-failure',
        ),
    ],
)
def test_main_window_operation_failed_restores_ui_and_shows_error(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        operation_request: OrganizerDialogResult,
        expected_title: str,
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9400', 'dimgray')],
    )
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        'critical',
        lambda _parent, title, text: errors.append((title, text)),
    )
    window._organizer_request = operation_request
    window._show_progress('Running', 25)

    window._handle_operation_failed('boom')

    assert errors == [(expected_title, 'boom')]
    assert window._busy is False
    assert window.progress_overlay.isHidden() is True
    assert window.organize_button.isEnabled() is True

    window.close()
    del app


def test_main_window_undo_failed_restores_ui_and_shows_error(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9450', 'dimgray')],
    )
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        'critical',
        lambda _parent, title, text: errors.append((title, text)),
    )
    window._operation_kind = 'undo'
    window._show_progress('Undoing', 25)

    window._handle_operation_failed('undo boom')

    assert errors == [('Undo Failed', 'undo boom')]
    assert window._busy is False
    assert window.progress_overlay.isHidden() is True
    assert window.organize_button.isEnabled() is True

    window.close()
    del app
