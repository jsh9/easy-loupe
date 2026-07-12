from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Never

import pytest
from PySide6.QtCore import QItemSelectionModel, QPoint, Qt, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMessageBox

import easy_loupe.ui.main_window.build as build_module
import easy_loupe.ui.main_window.window as main_window_module
import easy_loupe.ui.main_window.workflows as workflows_module
import easy_loupe.ui.theme as theme_module
from easy_loupe.core import exif as core_exif_module
from easy_loupe.core.folder_loading import PHOTO_SORT_MODE_CAPTURE_TIME
from easy_loupe.core.records import METADATA_FILENAME
from easy_loupe.operations.common import OperationSummary, UndoPlan
from easy_loupe.operations.export import FlagOrganizeFilesOptions
from easy_loupe.operations.xmp import WriteXmpOptions
from easy_loupe.ui.main_window.dialogs import OrganizerDialogResult
from easy_loupe.ui.main_window.filters import PhotoFilterSelection
from tests.ui._helpers import (
    assert_choose_folder_idle,
    create_jpeg,
    create_main_window_with_library,
    record_fit_view_calls,
    set_qt_active_window,
    set_scene_detection_result,
    stub_read_exif,
    thumbnail_item_widget,
)


def _list_widget_has_focus(app: QApplication, list_widget: object) -> bool:
    focus_widget = app.focusWidget()
    return focus_widget in {list_widget, list_widget.viewport()}


def _select_list_rows(list_widget: object, rows: list[int]) -> None:
    list_widget.clearSelection()
    first_item = list_widget.item(rows[0])
    assert first_item is not None
    selection_model = list_widget.selectionModel()
    selection_model.setCurrentIndex(
        list_widget.indexFromItem(first_item),
        QItemSelectionModel.SelectionFlag.ClearAndSelect,
    )
    for row in rows[1:]:
        item = list_widget.item(row)
        assert item is not None
        item.setSelected(True)

    list_widget.setFocus(Qt.OtherFocusReason)


def _set_list_item_viewport_top(
        list_widget: object, row: int, desired_top: int
) -> None:
    item = list_widget.item(row)
    assert item is not None
    rect = list_widget.visualItemRect(item)
    scrollbar = list_widget.verticalScrollBar()
    scrollbar.setValue(
        max(
            0,
            min(
                scrollbar.value() + rect.top() - desired_top,
                scrollbar.maximum(),
            ),
        )
    )


def _item_center(list_widget: object, row: int) -> object:
    item = list_widget.item(row)
    assert item is not None
    return list_widget.visualItemRect(item).center()


def _confirm_next_break_scene(
        monkeypatch: pytest.MonkeyPatch,
        *,
        accept: bool,
        captured: dict[str, object] | None = None,
) -> None:
    def fake_exec(message_box: QMessageBox) -> int:
        if captured is not None:
            captured['title'] = message_box.windowTitle()
            captured['text'] = message_box.text()
            captured['informative_text'] = message_box.informativeText()
            default_button = message_box.defaultButton()
            captured['default_button'] = (
                default_button.text().replace('&', '')
                if default_button is not None
                else None
            )
            captured['buttons'] = [
                button.text().replace('&', '')
                for button in message_box.buttons()
            ]

        target_text = 'Break Scene' if accept else 'Cancel'
        message_box._clicked_button = next(
            button
            for button in message_box.buttons()
            if button.text().replace('&', '') == target_text
        )
        return 0

    monkeypatch.setattr(QMessageBox, 'exec', fake_exec)
    monkeypatch.setattr(
        QMessageBox,
        'clickedButton',
        lambda message_box: getattr(message_box, '_clicked_button', None),
    )


def _confirm_next_filtered_scene_merge(
        monkeypatch: pytest.MonkeyPatch,
        *,
        accept: bool,
        captured: dict[str, object] | None = None,
) -> None:
    """
    Capture and answer the filtered-merge QMessageBox.

    Qt can report an empty ``windowTitle()`` before native dialog execution on
    some backends, so this helper records ``setWindowTitle`` directly while
    still using the real method.
    """
    original_set_window_title = QMessageBox.setWindowTitle

    def fake_set_window_title(message_box: QMessageBox, title: str) -> None:
        if captured is not None:
            captured['title'] = title

        original_set_window_title(message_box, title)

    def fake_exec(message_box: QMessageBox) -> int:
        if captured is not None:
            captured['text'] = message_box.text()
            default_button = message_box.defaultButton()
            captured['default_button'] = (
                default_button.text().replace('&', '')
                if default_button is not None
                else None
            )
            captured['buttons'] = [
                button.text().replace('&', '')
                for button in message_box.buttons()
            ]

        target_text = 'Merge Scene' if accept else 'Cancel'
        message_box._clicked_button = next(
            button
            for button in message_box.buttons()
            if button.text().replace('&', '') == target_text
        )
        return 0

    monkeypatch.setattr(QMessageBox, 'setWindowTitle', fake_set_window_title)
    monkeypatch.setattr(QMessageBox, 'exec', fake_exec)
    monkeypatch.setattr(
        QMessageBox,
        'clickedButton',
        lambda message_box: getattr(message_box, '_clicked_button', None),
    )


def _assert_break_scene_filter_warning(app: QApplication, window: Any) -> None:
    """
    Verify filtered break-scene warnings persist until Esc.

    The warning uses the transient overlay rather than a dialog, so tests need
    to prove both the blocking message and its shortcut-based recovery path.
    """
    assert window.transient_message_overlay.isVisible() is True
    assert window.transient_message_label.text() == (
        workflows_module.BREAK_SCENE_FILTER_ACTIVE_MESSAGE
    )
    assert window.transient_message_timer.isActive() is False
    assert window.exit_compare_shortcut.isEnabled() is True

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    assert window.transient_message_overlay.isHidden() is True
    assert window.exit_compare_shortcut.isEnabled() is False


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

        def _after_metadata_change(
                self, changed_photo_ids: list[str] | None = None
        ) -> None:
            assert changed_photo_ids == ['IMG_7100']
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
    QTest.qWait(build_module.INITIAL_FOLDER_PROMPT_GRACE_MS + 20)
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
    """
    Verify abandoned or failed folder loads restore controls without noise.

    The empty-folder dialog is reserved for successful scans that find zero
    photos, so cancel and failure paths must not show it while unwinding.
    """
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
    empty_dialogs: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        'information',
        lambda _parent, title, text, *_args: empty_dialogs.append((
            title,
            text,
        )),
    )

    if load_behavior == 'raise':

        def fail_load_folder(
                _folder: Path,
                *,
                progress_callback: object | None = None,
                progress_reporter: object | None = None,
        ) -> Never:
            del progress_callback, progress_reporter
            raise RuntimeError('boom')

        monkeypatch.setattr(window.library, 'load_folder', fail_load_folder)

    window.choose_folder()

    assert errors == expected_errors
    assert empty_dialogs == []
    assert_choose_folder_idle(window)
    assert window.open_button.isEnabled() is True
    assert window.detect_button.isEnabled() is False

    window.close()
    del app


@pytest.mark.parametrize(
    ('load_recursively', 'nested_photo'),
    [
        pytest.param(True, False, id='recursive-empty-folder'),
        pytest.param(False, True, id='direct-only-ignores-subfolder-photo'),
    ],
)
def test_main_window_choose_folder_empty_load_shows_no_eligible_photos_dialog(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        load_recursively: bool,
        nested_photo: bool,
) -> None:
    """
    Verify manual empty folder loads explain why no photos appeared.

    The dialog is based on the loaded photo count, so it must appear for a
    truly empty recursive scan and for a direct-only scan where eligible files
    exist only in subfolders.
    """
    if nested_photo:
        nested = tmp_path / 'nested'
        nested.mkdir()
        create_jpeg(nested / 'IMG_9000.JPG', 'blue')

    monkeypatch.setattr(
        QFileDialog,
        'getExistingDirectory',
        lambda *_args, **_kwargs: str(tmp_path),
    )
    captured_dialogs: list[dict[str, object]] = []

    def fake_information(
            _parent: object,
            title: str,
            text: str,
            buttons: QMessageBox.StandardButton,
            default_button: QMessageBox.StandardButton,
    ) -> QMessageBox.StandardButton:
        captured_dialogs.append({
            'title': title,
            'text': text,
            'buttons': buttons,
            'default': default_button,
        })
        return default_button

    monkeypatch.setattr(QMessageBox, 'information', fake_information)

    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.library.set_load_recursively(load_recursively)

    window.choose_folder()
    app.processEvents()

    assert captured_dialogs == [
        {
            'title': 'No Eligible Photos',
            'text': 'No supported photos were found in the selected folder.',
            'buttons': QMessageBox.StandardButton.Ok,
            'default': QMessageBox.StandardButton.Ok,
        }
    ]
    assert_choose_folder_idle(window)
    assert window.library.current_folder == tmp_path.resolve()
    assert window.open_button.isEnabled() is True
    assert window.detect_button.isEnabled() is False
    assert window.organize_button.isEnabled() is False

    window.close()
    del app


def test_main_window_empty_choose_folder_progress_reports_zero_total_rows(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify empty folder loads still render completed zero-work stage rows.

    The empty-folder dialog appears after the overlay is hidden, so this
    captures the structured progress state immediately before cleanup. It
    protects the UI from showing fake ``0 of 0`` bars for zero-work stages.
    """
    monkeypatch.setattr(
        QFileDialog,
        'getExistingDirectory',
        lambda *_args, **_kwargs: str(tmp_path),
    )
    monkeypatch.setattr(
        QMessageBox,
        'information',
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.show()
    app.processEvents()
    progress_before_hide: list[
        tuple[set[str], dict[str, bool], bool, bool]
    ] = []
    original_hide_progress = window._hide_progress

    def record_progress_before_hide() -> None:
        rows = window.progress_stage_list._rows
        progress_before_hide.append((
            set(rows),
            {
                stage_id: row.progress_bar.isVisible()
                for stage_id, row in rows.items()
            },
            window.progress_stage_list.isVisible(),
            window.overlay_progress_bar.isVisible(),
        ))
        original_hide_progress()

    monkeypatch.setattr(window, '_hide_progress', record_progress_before_hide)

    window.choose_folder()
    app.processEvents()

    assert len(progress_before_hide) == 1
    stage_ids, row_bar_visibility, stage_list_visible, scalar_bar_visible = (
        progress_before_hide[0]
    )
    assert stage_ids == {
        'scan',
        'metadata',
        'records',
        'thumbnails',
        'browse',
    }
    assert stage_list_visible is True
    assert scalar_bar_visible is False
    assert row_bar_visibility['scan'] is True
    assert row_bar_visibility['metadata'] is False
    assert row_bar_visibility['records'] is False
    assert row_bar_visibility['thumbnails'] is False
    assert row_bar_visibility['browse'] is False
    assert window.progress_overlay.isHidden() is True

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


def test_main_window_detect_scenes_prompts_before_replacing_existing_scenes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_7420', 'dimgray'), ('IMG_7421', 'blue')],
        scene_groups=[['IMG_7420', 'IMG_7421']],
    )
    captured: dict[str, object] = {}
    started: list[str] = []

    def fake_exec(message_box: QMessageBox) -> int:
        captured['title'] = message_box.windowTitle()
        captured['text'] = message_box.text()
        captured['buttons'] = [
            button.text().replace('&', '') for button in message_box.buttons()
        ]
        message_box._clicked_button = None
        return 0

    monkeypatch.setattr(QMessageBox, 'exec', fake_exec)
    monkeypatch.setattr(
        QMessageBox,
        'clickedButton',
        lambda message_box: getattr(message_box, '_clicked_button', None),
    )
    monkeypatch.setattr(
        QThread,
        'start',
        lambda self: started.append(self.objectName() or 'started'),
    )

    window.detect_scenes()

    assert captured['text'] == 'Replace existing scene groups?'
    assert 'Replace' in captured['buttons']
    assert started == []
    assert window._scene_thread is None

    window.close()
    del app


def test_main_window_detect_scenes_replace_starts_worker(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_7430', 'dimgray'), ('IMG_7431', 'blue')],
        scene_groups=[['IMG_7430', 'IMG_7431']],
    )
    started: list[str] = []

    def fake_exec(message_box: QMessageBox) -> int:
        message_box._clicked_button = next(
            button
            for button in message_box.buttons()
            if button.text().replace('&', '') == 'Replace'
        )
        return 0

    monkeypatch.setattr(QMessageBox, 'exec', fake_exec)
    monkeypatch.setattr(
        QMessageBox,
        'clickedButton',
        lambda message_box: getattr(message_box, '_clicked_button', None),
    )
    monkeypatch.setattr(
        QThread,
        'start',
        lambda self: started.append(self.objectName() or 'started'),
    )

    window.detect_scenes()

    assert started == ['started']
    assert window._scene_thread is not None
    assert window._busy is True

    window.close()
    del app


@pytest.mark.parametrize(
    ('initially_running', 'expected_quit_calls'),
    [
        pytest.param(True, 1, id='running'),
        pytest.param(False, 0, id='stopped-slot'),
    ],
)
def test_main_window_close_defers_until_scene_thread_clears(
        initially_running: bool,
        expected_quit_calls: int,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify close hides immediately without deleting active thread wrappers.

    Background scene detection can still have queued Qt cleanup work after the
    user closes the window. The visible window should disappear immediately,
    while final teardown still waits for the normal finished cleanup path. This
    observes ``destroyed`` because visibility is already false before the
    queued final close runs.
    """

    class FakeThread:
        def __init__(self) -> None:
            self.running = initially_running
            self.quit_calls = 0

        def isRunning(self) -> bool:  # noqa: N802 - Qt API
            return self.running

        def quit(self) -> None:
            self.quit_calls += 1

    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_7450', 'dimgray')],
    )
    fake_thread = FakeThread()
    fake_worker = object()
    destroyed: list[str] = []
    # Match production ownership so `destroyed` proves the deferred final close
    # accepted, rather than only proving that the first close hid the window.
    window.setAttribute(Qt.WA_DeleteOnClose, True)
    window.destroyed.connect(lambda *_args: destroyed.append('destroyed'))
    window._scene_thread = fake_thread
    window._scene_worker = fake_worker

    window.close()
    app.processEvents()

    assert window.isVisible() is False
    assert window.progress_overlay.isHidden() is True
    assert window._close_after_background_tasks is True
    assert fake_thread.quit_calls == expected_quit_calls
    assert destroyed == []

    fake_thread.running = False
    window._clear_scene_worker(fake_thread, fake_worker)

    assert window.isVisible() is False
    assert window._close_after_background_tasks is False
    assert destroyed == []

    # The cleanup path posts a zero-delay close, and Qt delivers deletion on a
    # later event turn. Drain both turns so the assertion observes teardown.
    for _ in range(2):
        app.processEvents()

    assert destroyed == ['destroyed']
    del app


def test_scene_detection_clears_stale_manual_scene_undo_history(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Do not let Ctrl+Z restore manual scene groups after detection reruns.

    The test creates a manual scene edit, simulates a new detection result, and
    then triggers undo. The detected groups should remain in place because the
    old scene edit history was cleared.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7432', 'dimgray'),
            ('IMG_7433', 'blue'),
            ('IMG_7434', 'green'),
            ('IMG_7435', 'white'),
        ],
    )
    window._enter_browse_mode()
    _select_list_rows(window.browse_list, [0, 1])
    app.processEvents()

    window.merge_scene_action.trigger()
    app.processEvents()

    assert any(
        isinstance(edit, workflows_module.SceneEdit)
        for edit in window._metadata_undo_stack
    )

    detected_groups = [
        ['IMG_7432'],
        ['IMG_7433', 'IMG_7434'],
        ['IMG_7435'],
    ]
    set_scene_detection_result(window, detected_groups)
    window._handle_scene_finished()
    app.processEvents()

    assert [
        edit
        for edit in window._metadata_undo_stack
        if isinstance(edit, workflows_module.SceneEdit)
    ] == []
    window.undo_metadata_action.trigger()
    app.processEvents()

    assert [scene.photo_ids for scene in window.library.scenes] == (
        detected_groups
    )

    window.close()
    del app


def test_merge_selected_photos_from_browse_saves_and_undoes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Keep browse-mode focus on the browse grid after scene edits.

    Merging or undoing scenes rebuilds the lists. In browse mode, the thumbnail
    strip is hidden, so keyboard focus must return to the visible browse grid.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7440', 'dimgray'),
            ('IMG_7441', 'blue'),
            ('IMG_7442', 'green'),
        ],
    )
    # This test asserts Qt focus ownership. Earlier UI tests can leave the
    # shared QApplication with no active window, so make this the Qt-active
    # window without asking the desktop to focus or raise it.
    set_qt_active_window(window)
    app.processEvents()
    if not window.isActiveWindow():
        pytest.skip('Window activation is not available in this Qt session')

    window._enter_browse_mode()
    _select_list_rows(window.browse_list, [0, 1])
    app.processEvents()

    assert window.merge_scene_action.isEnabled() is True

    window.merge_scene_action.trigger()
    app.processEvents()

    assert window.library.scene_source == 'manual'
    assert window._scene_merge_selection_source == 'browse'
    assert _list_widget_has_focus(app, window.browse_list)
    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7440', 'IMG_7441'],
        ['IMG_7442'],
    ]
    data = json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )
    assert data['scenes'] == {
        'groups': [['IMG_7440', 'IMG_7441'], ['IMG_7442']],
        'source': 'manual',
    }

    window.undo_metadata_action.trigger()
    app.processEvents()

    assert window.library.scene_detection_done is False
    assert window.library.scenes == []
    assert window._scene_merge_selection_source == 'browse'
    assert _list_widget_has_focus(app, window.browse_list)
    data = json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )
    assert 'scenes' not in data

    window.redo_metadata_action.trigger()
    app.processEvents()

    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7440', 'IMG_7441'],
        ['IMG_7442'],
    ]

    window.close()
    del app


def test_merge_selected_scene_strip_subset_shows_notice_without_splitting(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Reject partial scene-strip merges even with vertical stacks selected.

    Scene-strip selection is exact photo selection inside one existing scene.
    Selecting only part of that strip would require splitting the current scene
    before merging, so the action should show the split warning and avoid
    saving metadata or creating undo history.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7450', 'dimgray'),
            ('IMG_7451', 'blue'),
            ('IMG_7452', 'green'),
            ('IMG_7453', 'white'),
        ],
        scene_groups=[['IMG_7450', 'IMG_7451', 'IMG_7452'], ['IMG_7453']],
    )
    _select_list_rows(window.thumbnail_list, [0, 1])
    app.processEvents()
    _select_list_rows(window.scene_list, [1, 2])
    app.processEvents()

    save_calls = []
    original_save_metadata = window.library.save_metadata

    def save_metadata_spy() -> None:
        save_calls.append(None)
        original_save_metadata()

    monkeypatch.setattr(window.library, 'save_metadata', save_metadata_spy)

    window.merge_scene_action.trigger()
    app.processEvents()

    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7450', 'IMG_7451', 'IMG_7452'],
        ['IMG_7453'],
    ]
    assert save_calls == []
    assert not (tmp_path / METADATA_FILENAME).exists()
    assert window._metadata_undo_stack == []
    assert window.transient_message_overlay.isVisible() is True
    assert window.transient_message_label.text() == (
        'Cannot split an existing scene group.\n'
        'Press Ctrl+Z to undo and group again.'
    )
    assert (
        window.transient_message_timer.interval()
        == workflows_module.TRANSIENT_MESSAGE_TIMEOUT_MS
    )
    assert window.exit_compare_shortcut.isEnabled() is True

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is False
    assert window.transient_message_overlay.isHidden() is True
    assert window.exit_compare_shortcut.isEnabled() is False

    window.close()
    del app


def test_merge_full_scene_strip_selection_combines_vertical_stacks(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Merge a full scene-strip selection together with vertical stacks.

    This covers the manual workflow where the user selects other scene rows in
    the vertical strip, selects every photo in the active horizontal scene, and
    presses Ctrl+Shift+M. A full strip selection means "include this scene",
    not "attempt to split this scene", so it must merge with the selected
    vertical stacks.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7454', 'dimgray'),
            ('IMG_7455', 'blue'),
            ('IMG_7456', 'green'),
            ('IMG_7457', 'white'),
        ],
        scene_groups=[
            ['IMG_7454'],
            ['IMG_7455', 'IMG_7456'],
            ['IMG_7457'],
        ],
    )
    _select_list_rows(window.thumbnail_list, [0, 1])
    second_stack = window.thumbnail_list.item(1)
    assert second_stack is not None
    window.thumbnail_list.selectionModel().setCurrentIndex(
        window.thumbnail_list.indexFromItem(second_stack),
        QItemSelectionModel.SelectionFlag.NoUpdate,
    )
    app.processEvents()

    _select_list_rows(window.scene_list, [0, 1])
    app.processEvents()

    assert window._scene_merge_selection_source == 'scene'
    assert window._mergeable_scene_photo_ids() == [
        'IMG_7454',
        'IMG_7455',
        'IMG_7456',
    ]

    window.merge_scene_action.trigger()
    app.processEvents()

    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7454', 'IMG_7455', 'IMG_7456'],
        ['IMG_7457'],
    ]
    assert window._metadata_undo_stack
    assert (tmp_path / METADATA_FILENAME).exists()

    window.close()
    del app


def test_merge_selected_scene_stacks_uses_whole_stack_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7460', 'dimgray'),
            ('IMG_7461', 'blue'),
            ('IMG_7462', 'green'),
            ('IMG_7463', 'white'),
        ],
        scene_groups=[['IMG_7460', 'IMG_7461'], ['IMG_7462', 'IMG_7463']],
    )
    _select_list_rows(window.thumbnail_list, [0, 1])
    app.processEvents()

    window.merge_scene_action.trigger()
    app.processEvents()

    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7460', 'IMG_7461', 'IMG_7462', 'IMG_7463']
    ]

    window.close()
    del app


def test_filtered_merge_warns_and_includes_hidden_photos(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify filtered scene merges include hidden photos after confirmation.

    The visible selection can skip photos hidden by the active filter. The
    merge must warn before passing those hidden range IDs to the exact-ID
    library merge API.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7464', 'dimgray'),
            ('IMG_7465', 'blue'),
            ('IMG_7466', 'green'),
            ('IMG_7467', 'white'),
        ],
    )
    window.library.get_photo('IMG_7464').flag = 'picked'
    window.library.get_photo('IMG_7465').flag = 'rejected'
    window.library.get_photo('IMG_7466').flag = 'picked'
    window.library.get_photo('IMG_7467').flag = 'picked'
    window._apply_photo_filter(
        PhotoFilterSelection(allowed_flags=frozenset({'picked'}))
    )
    app.processEvents()
    _select_list_rows(window.thumbnail_list, [0, 1])
    app.processEvents()
    captured: dict[str, object] = {}
    _confirm_next_filtered_scene_merge(
        monkeypatch, accept=True, captured=captured
    )

    assert window.merge_scene_action.isEnabled() is True

    window.merge_scene_action.trigger()
    app.processEvents()

    assert captured['title'] == 'Merge Includes Hidden Photos'
    assert (
        captured['text'] == workflows_module.FILTERED_SCENE_MERGE_WARNING_TEXT
    )
    assert captured['default_button'] == 'Cancel'
    buttons = captured['buttons']
    assert isinstance(buttons, list)
    assert set(buttons) == {'Merge Scene', 'Cancel'}
    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7464', 'IMG_7465', 'IMG_7466'],
        ['IMG_7467'],
    ]
    assert window._metadata_undo_stack
    assert json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )['scenes'] == {
        'groups': [
            ['IMG_7464', 'IMG_7465', 'IMG_7466'],
            ['IMG_7467'],
        ],
        'source': 'manual',
    }

    window.close()
    del app


def test_filtered_merge_existing_scene_stack_shows_selection_notice(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Avoid hidden-photo confirmation when expansion is already a full scene.

    A filtered scene stack can expose only some members of one existing scene.
    Expanding that one visible stack may recreate the exact current group, so
    the UI should show the selection warning instead of asking users to confirm
    a no-op merge.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_2400', 'dimgray'),
            ('IMG_2401', 'blue'),
            ('IMG_2402', 'green'),
        ],
        scene_groups=[['IMG_2400', 'IMG_2401', 'IMG_2402']],
    )
    window.library.get_photo('IMG_2400').flag = 'picked'
    window.library.get_photo('IMG_2401').flag = 'rejected'
    window.library.get_photo('IMG_2402').flag = 'picked'
    window._apply_photo_filter(
        PhotoFilterSelection(allowed_flags=frozenset({'picked'}))
    )
    app.processEvents()
    original_groups = window.library.scene_group_photo_ids()
    _select_list_rows(window.thumbnail_list, [0])
    app.processEvents()
    confirmation_calls: list[str] = []
    monkeypatch.setattr(
        window,
        '_confirm_filtered_scene_merge',
        lambda: confirmation_calls.append('confirm') or True,
    )

    window.merge_scene_action.trigger()
    app.processEvents()

    assert confirmation_calls == []
    assert window.library.scene_group_photo_ids() == original_groups
    assert window._metadata_undo_stack == []
    assert not (tmp_path / METADATA_FILENAME).exists()
    assert window.transient_message_overlay.isVisible() is True
    assert window.transient_message_label.text() == (
        workflows_module.MERGE_REQUIRES_SELECTION_MESSAGE
    )
    assert window.transient_message_timer.isActive() is False
    assert window.exit_compare_shortcut.isEnabled() is True

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    assert window.transient_message_overlay.isHidden() is True
    assert window.exit_compare_shortcut.isEnabled() is False

    window.close()
    del app


def test_filtered_merge_blocks_sparse_visible_photo_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify filtered merges reject visible selections with skipped rows.

    Hidden photos can be included for one continuous visible range, but a
    sparse selection must not silently pull in visible photos that the user
    intentionally left unselected.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7488', 'dimgray'),
            ('IMG_7489', 'blue'),
            ('IMG_7490', 'green'),
            ('IMG_7491', 'white'),
        ],
    )
    window.library.get_photo('IMG_7488').flag = 'picked'
    window.library.get_photo('IMG_7489').flag = 'picked'
    window.library.get_photo('IMG_7490').flag = 'rejected'
    window.library.get_photo('IMG_7491').flag = 'picked'
    window._apply_photo_filter(
        PhotoFilterSelection(allowed_flags=frozenset({'picked'}))
    )
    app.processEvents()
    _select_list_rows(window.thumbnail_list, [0, 2])
    app.processEvents()
    confirmation_calls: list[str] = []
    monkeypatch.setattr(
        window,
        '_confirm_filtered_scene_merge',
        lambda: confirmation_calls.append('confirm') or True,
    )

    window.merge_scene_action.trigger()
    app.processEvents()

    assert confirmation_calls == []
    assert window.library.scene_group_photo_ids() == []
    assert window._metadata_undo_stack == []
    assert not (tmp_path / METADATA_FILENAME).exists()
    assert window.transient_message_overlay.isVisible() is True
    assert window.transient_message_label.text() == (
        workflows_module.FILTERED_SCENE_MERGE_REQUIRES_RANGE_MESSAGE
    )
    assert window.transient_message_timer.isActive() is False
    assert window.exit_compare_shortcut.isEnabled() is True

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    assert window.transient_message_overlay.isHidden() is True
    assert window.exit_compare_shortcut.isEnabled() is False

    window.close()
    del app


def test_filtered_merge_expands_visible_stack_to_hidden_scene_range(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify filtered scene-stack merges keep hidden scene members together.

    A visible scene stack can be only part of an underlying scene. Selecting
    that visible stack must expand to the full original scene before computing
    the merge range, otherwise hidden leading or trailing scene members can be
    split away without appearing in the selection UI.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7478', 'dimgray'),
            ('IMG_7479', 'blue'),
            ('IMG_7480', 'green'),
            ('IMG_7481', 'white'),
            ('IMG_7482', 'purple'),
        ],
        scene_groups=[
            ['IMG_7478', 'IMG_7479', 'IMG_7480', 'IMG_7481'],
            ['IMG_7482'],
        ],
    )
    window.library.get_photo('IMG_7478').flag = 'rejected'
    window.library.get_photo('IMG_7479').flag = 'rejected'
    window.library.get_photo('IMG_7480').flag = 'picked'
    window.library.get_photo('IMG_7481').flag = 'rejected'
    window.library.get_photo('IMG_7482').flag = 'picked'
    window._apply_photo_filter(
        PhotoFilterSelection(allowed_flags=frozenset({'picked'}))
    )
    app.processEvents()
    _select_list_rows(window.thumbnail_list, [0, 1])
    app.processEvents()
    _confirm_next_filtered_scene_merge(monkeypatch, accept=True)

    window.merge_scene_action.trigger()
    app.processEvents()

    assert [scene.photo_ids for scene in window.library.scenes] == [
        [
            'IMG_7478',
            'IMG_7479',
            'IMG_7480',
            'IMG_7481',
            'IMG_7482',
        ],
    ]
    assert json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )['scenes'] == {
        'groups': [
            [
                'IMG_7478',
                'IMG_7479',
                'IMG_7480',
                'IMG_7481',
                'IMG_7482',
            ],
        ],
        'source': 'manual',
    }

    window.close()
    del app


def test_filtered_merge_blocks_sparse_visible_scene_stack_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify filtered scene-stack merges reject skipped visible stacks.

    Continuous visible stack ranges may expand to hidden scene members. Sparse
    visible stack selections must stop before expansion so an unselected
    visible stack is not merged just because it sits between the selected
    endpoints.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7493', 'dimgray'),
            ('IMG_7494', 'blue'),
            ('IMG_7495', 'green'),
            ('IMG_7496', 'white'),
            ('IMG_7497', 'purple'),
        ],
        scene_groups=[
            ['IMG_7493', 'IMG_7494'],
            ['IMG_7495'],
            ['IMG_7496', 'IMG_7497'],
        ],
    )
    window.library.get_photo('IMG_7493').flag = 'picked'
    window.library.get_photo('IMG_7494').flag = 'rejected'
    window.library.get_photo('IMG_7495').flag = 'picked'
    window.library.get_photo('IMG_7496').flag = 'picked'
    window.library.get_photo('IMG_7497').flag = 'rejected'
    window._apply_photo_filter(
        PhotoFilterSelection(allowed_flags=frozenset({'picked'}))
    )
    app.processEvents()
    original_groups = window.library.scene_group_photo_ids()
    _select_list_rows(window.thumbnail_list, [0, 2])
    app.processEvents()
    confirmation_calls: list[str] = []
    monkeypatch.setattr(
        window,
        '_confirm_filtered_scene_merge',
        lambda: confirmation_calls.append('confirm') or True,
    )

    window.merge_scene_action.trigger()
    app.processEvents()

    assert confirmation_calls == []
    assert window.library.scene_group_photo_ids() == original_groups
    assert window._metadata_undo_stack == []
    assert not (tmp_path / METADATA_FILENAME).exists()
    assert window.transient_message_label.text() == (
        workflows_module.FILTERED_SCENE_MERGE_REQUIRES_RANGE_MESSAGE
    )

    window.close()
    del app


def test_filtered_merge_cancel_keeps_scene_state(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify cancelling the filtered hidden-photo warning leaves scenes alone.

    Disabled actions are no longer the filter guard, so the modal cancellation
    path must prevent metadata writes, undo history, and scene mutation.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7468', 'dimgray'),
            ('IMG_7469', 'blue'),
            ('IMG_7470', 'green'),
        ],
    )
    window.library.get_photo('IMG_7468').flag = 'picked'
    window.library.get_photo('IMG_7469').flag = 'rejected'
    window.library.get_photo('IMG_7470').flag = 'picked'
    window._apply_photo_filter(
        PhotoFilterSelection(allowed_flags=frozenset({'picked'}))
    )
    app.processEvents()
    _select_list_rows(window.thumbnail_list, [0, 1])
    app.processEvents()
    captured: dict[str, object] = {}
    _confirm_next_filtered_scene_merge(
        monkeypatch, accept=False, captured=captured
    )

    window.merge_scene_action.trigger()
    app.processEvents()

    assert captured['title'] == 'Merge Includes Hidden Photos'
    assert window.library.scene_group_photo_ids() == []
    assert window._metadata_undo_stack == []
    assert not (tmp_path / METADATA_FILENAME).exists()

    window.close()
    del app


def test_merge_shortcut_with_too_few_visible_photos_shows_persistent_notice(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify insufficient filtered merge selections explain how to dismiss.

    The menu and shortcut share one QAction, so real key dispatch should reach
    the guarded merge handler and show a persistent Esc-dismissable overlay
    instead of silently doing nothing.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7483', 'dimgray'),
            ('IMG_7484', 'blue'),
        ],
    )
    window.library.get_photo('IMG_7483').flag = 'picked'
    window.library.get_photo('IMG_7484').flag = 'rejected'
    window._apply_photo_filter(
        PhotoFilterSelection(allowed_flags=frozenset({'picked'}))
    )
    app.processEvents()
    original_groups = window.library.scene_group_photo_ids()
    set_qt_active_window(window)
    app.processEvents()

    QTest.keyClick(
        window,
        Qt.Key_M,
        Qt.ControlModifier | Qt.ShiftModifier,
    )
    app.processEvents()

    assert window.library.scene_group_photo_ids() == original_groups
    assert window._metadata_undo_stack == []
    assert not (tmp_path / METADATA_FILENAME).exists()
    assert window.transient_message_overlay.isVisible() is True
    assert window.transient_message_label.text() == (
        workflows_module.MERGE_REQUIRES_SELECTION_MESSAGE
    )
    assert window.transient_message_timer.isActive() is False
    assert window.exit_compare_shortcut.isEnabled() is True

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    assert window.transient_message_overlay.isHidden() is True
    assert window.exit_compare_shortcut.isEnabled() is False

    window.close()
    del app


def test_filtered_merge_without_hidden_gap_skips_confirmation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify filtered merges ask only when hidden photos would be added.

    Hidden photos outside the selected endpoints do not need a warning because
    they are not included in the manual merge.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7471', 'dimgray'),
            ('IMG_7472', 'blue'),
            ('IMG_7473', 'green'),
        ],
    )
    window.library.get_photo('IMG_7471').flag = 'picked'
    window.library.get_photo('IMG_7472').flag = 'picked'
    window.library.get_photo('IMG_7473').flag = 'rejected'
    window._apply_photo_filter(
        PhotoFilterSelection(allowed_flags=frozenset({'picked'}))
    )
    app.processEvents()
    _select_list_rows(window.thumbnail_list, [0, 1])
    app.processEvents()
    confirmation_calls: list[str] = []
    monkeypatch.setattr(
        window,
        '_confirm_filtered_scene_merge',
        lambda: confirmation_calls.append('confirm') or True,
    )

    window.merge_scene_action.trigger()
    app.processEvents()

    assert confirmation_calls == []
    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7471', 'IMG_7472'],
        ['IMG_7473'],
    ]
    assert window._metadata_undo_stack

    window.close()
    del app


def test_filtered_scene_strip_subset_still_shows_split_notice(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Reject filtered partial scene-strip merges before hidden-photo expansion.

    Selecting only part of the visible scene strip would still split the
    currently visible scene group, so it keeps the existing split warning and
    does not open the filtered hidden-photo confirmation.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7474', 'dimgray'),
            ('IMG_7475', 'blue'),
            ('IMG_7476', 'green'),
            ('IMG_7477', 'white'),
        ],
        scene_groups=[
            ['IMG_7474', 'IMG_7475', 'IMG_7476', 'IMG_7477'],
        ],
    )
    window.library.get_photo('IMG_7474').flag = 'picked'
    window.library.get_photo('IMG_7475').flag = 'rejected'
    window.library.get_photo('IMG_7476').flag = 'picked'
    window.library.get_photo('IMG_7477').flag = 'picked'
    window._apply_photo_filter(
        PhotoFilterSelection(allowed_flags=frozenset({'picked'}))
    )
    app.processEvents()
    _select_list_rows(window.scene_list, [0, 1])
    app.processEvents()
    save_calls: list[str] = []
    confirmation_calls: list[str] = []
    monkeypatch.setattr(
        window.library,
        'save_metadata',
        lambda: save_calls.append('save'),
    )
    monkeypatch.setattr(
        window,
        '_confirm_filtered_scene_merge',
        lambda: confirmation_calls.append('confirm') or True,
    )

    window.merge_scene_action.trigger()
    app.processEvents()

    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7474', 'IMG_7475', 'IMG_7476', 'IMG_7477'],
    ]
    assert save_calls == []
    assert confirmation_calls == []
    assert window._metadata_undo_stack == []
    assert window.transient_message_label.text() == (
        'Cannot split an existing scene group.\n'
        'Press Ctrl+Z to undo and group again.'
    )

    window.close()
    del app


def test_break_scene_from_vertical_context_menu_saves_and_undoes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7484', 'dimgray'),
            ('IMG_7485', 'blue'),
            ('IMG_7486', 'green'),
            ('IMG_7487', 'white'),
        ],
        scene_groups=[
            ['IMG_7484', 'IMG_7485', 'IMG_7486'],
            ['IMG_7487'],
        ],
    )
    _confirm_next_break_scene(monkeypatch, accept=True)

    scene = window._context_scene_from_thumbnail_position(
        _item_center(window.thumbnail_list, 0)
    )
    assert scene is not None
    assert scene.photo_ids == ['IMG_7484', 'IMG_7485', 'IMG_7486']

    window._break_scene_into_singletons(scene.scene_id)
    app.processEvents()

    assert window.library.scene_source == 'manual'
    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7484'],
        ['IMG_7485'],
        ['IMG_7486'],
        ['IMG_7487'],
    ]
    assert window.thumbnail_list.currentRow() == 0
    assert json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )['scenes'] == {
        'groups': [
            ['IMG_7484'],
            ['IMG_7485'],
            ['IMG_7486'],
            ['IMG_7487'],
        ],
        'source': 'manual',
    }

    window.undo_metadata_action.trigger()
    app.processEvents()

    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7484', 'IMG_7485', 'IMG_7486'],
        ['IMG_7487'],
    ]

    window.redo_metadata_action.trigger()
    app.processEvents()

    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7484'],
        ['IMG_7485'],
        ['IMG_7486'],
        ['IMG_7487'],
    ]

    window.close()
    del app


@pytest.mark.parametrize(
    'menu_source',
    [
        pytest.param('thumbnail', id='vertical-thumbnail-strip'),
        pytest.param('scene-strip', id='horizontal-scene-strip'),
    ],
)
def test_break_scene_context_menu_defers_break_until_menu_closes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, menu_source: str
) -> None:
    """
    Run scene breaking after the context-menu handler has returned.

    Rebuilding the scene lists during native menu action dispatch can leave
    macOS focus stale. The menu handler therefore waits for ``QMenu.exec`` to
    return, then schedules the break on the event loop.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7484', 'dimgray'),
            ('IMG_7485', 'blue'),
            ('IMG_7486', 'green'),
            ('IMG_7487', 'white'),
        ],
        scene_groups=[
            ['IMG_7484', 'IMG_7485', 'IMG_7486'],
            ['IMG_7487'],
        ],
    )
    handler_returned = {'value': False}
    break_calls: list[str] = []

    class FakeAction:
        def __init__(self, text: str) -> None:
            self._text = text

        def text(self) -> str:
            return self._text

    class FakeMenu:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.actions: list[FakeAction] = []

        def addAction(self, text: str) -> FakeAction:  # noqa: N802 - Qt API
            action = FakeAction(text)
            self.actions.append(action)
            return action

        def exec(self, *_args: object, **_kwargs: object) -> FakeAction:
            assert len(self.actions) == 1
            assert self.actions[0].text() == 'Break Scene into Single Photos'
            return self.actions[0]

    def record_break_scene(scene_id: str) -> None:
        assert handler_returned['value'] is True
        break_calls.append(scene_id)

    monkeypatch.setattr(workflows_module, 'QMenu', FakeMenu)
    monkeypatch.setattr(
        window, '_break_scene_into_singletons', record_break_scene
    )

    if menu_source == 'thumbnail':
        scene = window._context_scene_from_thumbnail_position(
            _item_center(window.thumbnail_list, 0)
        )
        assert scene is not None
        expected_scene_id = scene.scene_id

        window._show_thumbnail_context_menu(
            _item_center(window.thumbnail_list, 0)
        )
    else:
        scene = window._context_scene_from_scene_strip()
        assert scene is not None
        expected_scene_id = scene.scene_id

        window._show_scene_context_menu(_item_center(window.scene_list, 0))

    assert break_calls == []
    handler_returned['value'] = True
    app.processEvents()

    assert break_calls == [expected_scene_id]

    window.close()
    del app


@pytest.mark.parametrize(
    'menu_source',
    [
        pytest.param('thumbnail', id='vertical-thumbnail-strip'),
        pytest.param('scene-strip', id='horizontal-scene-strip'),
    ],
)
def test_filtered_break_scene_context_menu_shows_warning(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, menu_source: str
) -> None:
    """
    Verify filtered break-scene right-clicks explain the blocked edit.

    These menu paths used to stop at the active-filter guard without feedback.
    Both visible scene surfaces must now show the persistent warning while
    skipping the confirmation dialog and preserving hidden scene members.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7484', 'dimgray'),
            ('IMG_7485', 'blue'),
            ('IMG_7486', 'green'),
            ('IMG_7487', 'white'),
        ],
        scene_groups=[
            ['IMG_7484', 'IMG_7485', 'IMG_7486'],
            ['IMG_7487'],
        ],
    )
    window.library.get_photo('IMG_7484').flag = 'picked'
    window.library.get_photo('IMG_7485').flag = 'picked'
    window.library.get_photo('IMG_7486').flag = 'rejected'
    window.library.get_photo('IMG_7487').flag = 'picked'
    window._apply_photo_filter(
        PhotoFilterSelection(allowed_flags=frozenset({'picked'}))
    )
    app.processEvents()
    original_groups = window.library.scene_group_photo_ids()
    confirmation_calls: list[str] = []
    save_calls: list[str] = []

    def fail_menu(*_args: object, **_kwargs: object) -> Never:
        pytest.fail('filtered break-scene warning should not open a menu')

    monkeypatch.setattr(workflows_module, 'QMenu', fail_menu)
    monkeypatch.setattr(
        window,
        '_confirm_break_scene',
        lambda: confirmation_calls.append('confirm') or True,
    )
    monkeypatch.setattr(
        window.library,
        'save_metadata',
        lambda: save_calls.append('save'),
    )

    if menu_source == 'thumbnail':
        window._show_thumbnail_context_menu(
            _item_center(window.thumbnail_list, 0)
        )
    else:
        window._show_scene_context_menu(_item_center(window.scene_list, 0))

    app.processEvents()

    assert window.library.scene_group_photo_ids() == original_groups
    assert confirmation_calls == []
    assert save_calls == []
    assert window._metadata_undo_stack == []
    assert not (tmp_path / METADATA_FILENAME).exists()
    _assert_break_scene_filter_warning(app, window)

    window.close()
    del app


def test_filtered_break_scene_direct_guard_shows_warning(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify direct scene-break calls under filters warn without mutation.

    Non-menu entry points bypass right-click target checks, so the mutation
    helper needs its own active-filter guard to preserve hidden scene members
    and explain why the scene edit was blocked.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7484', 'dimgray'),
            ('IMG_7485', 'blue'),
            ('IMG_7486', 'green'),
        ],
        scene_groups=[['IMG_7484', 'IMG_7485', 'IMG_7486']],
    )
    window.library.get_photo('IMG_7484').flag = 'picked'
    window.library.get_photo('IMG_7485').flag = 'picked'
    window.library.get_photo('IMG_7486').flag = 'rejected'
    window._apply_photo_filter(
        PhotoFilterSelection(allowed_flags=frozenset({'picked'}))
    )
    app.processEvents()
    original_groups = window.library.scene_group_photo_ids()
    confirmation_calls: list[str] = []
    save_calls: list[str] = []
    monkeypatch.setattr(
        window,
        '_confirm_break_scene',
        lambda: confirmation_calls.append('confirm') or True,
    )
    monkeypatch.setattr(
        window.library,
        'save_metadata',
        lambda: save_calls.append('save'),
    )

    window._break_scene_into_singletons(window.library.scenes[0].scene_id)
    app.processEvents()

    assert window.library.scene_group_photo_ids() == original_groups
    assert confirmation_calls == []
    assert save_calls == []
    assert window._metadata_undo_stack == []
    assert not (tmp_path / METADATA_FILENAME).exists()
    _assert_break_scene_filter_warning(app, window)

    window.close()
    del app


def test_break_scene_from_horizontal_context_menu_uses_current_scene(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7488', 'dimgray'),
            ('IMG_7489', 'blue'),
            ('IMG_7490', 'green'),
            ('IMG_7491', 'white'),
        ],
        scene_groups=[
            ['IMG_7488'],
            ['IMG_7489', 'IMG_7490', 'IMG_7491'],
        ],
    )
    window.thumbnail_list.setCurrentRow(1)
    app.processEvents()
    _confirm_next_break_scene(monkeypatch, accept=True)

    scene = window._context_scene_from_scene_strip()
    assert scene is not None
    assert scene.photo_ids == ['IMG_7489', 'IMG_7490', 'IMG_7491']

    window._break_scene_into_singletons(scene.scene_id)
    app.processEvents()

    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7488'],
        ['IMG_7489'],
        ['IMG_7490'],
        ['IMG_7491'],
    ]
    assert window.current_photo_id == 'IMG_7489'

    window.close()
    del app


def test_break_visible_scene_stack_preserves_strip_position(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Keep the split scene cover in place after expanding it to singletons.

    Scene splitting rebuilds the vertical strip with more rows than before. The
    rebuild must preserve the visible cover row position so the first split
    photo does not jump to the bottom of the viewport.
    """
    scene_groups = [[f'IMG_{index:04d}'] for index in range(10)]
    scene_groups.append([f'IMG_{index:04d}' for index in range(10, 15)])
    scene_groups.extend([[f'IMG_{index:04d}'] for index in range(15, 40)])
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[(f'IMG_{index:04d}', 'dimgray') for index in range(40)],
        scene_groups=scene_groups,
    )
    window.resize(1200, 800)
    app.processEvents()
    _confirm_next_break_scene(monkeypatch, accept=True)

    scene = window._scene_for_photo_id('IMG_0010')
    assert scene is not None
    target_row = window._thumbnail_row_for_photo('IMG_0010')
    assert target_row is not None

    scrollbar = window.thumbnail_list.verticalScrollBar()
    assert scrollbar.maximum() > 0
    _set_list_item_viewport_top(window.thumbnail_list, target_row, 160)
    app.processEvents()

    cover_item = window.thumbnail_list.item(target_row)
    assert cover_item is not None
    before_top = window.thumbnail_list.visualItemRect(cover_item).top()
    assert 0 <= before_top < window.thumbnail_list.viewport().height()

    window._break_scene_into_singletons(scene.scene_id)
    app.processEvents()

    assert window.current_photo_id == 'IMG_0010'
    assert window.thumbnail_list.currentRow() == target_row
    split_item = window.thumbnail_list.item(target_row)
    assert split_item is not None
    after_top = window.thumbnail_list.visualItemRect(split_item).top()
    assert abs(after_top - before_top) <= 1
    assert [scene.photo_ids for scene in window.library.scenes][10:15] == [
        ['IMG_0010'],
        ['IMG_0011'],
        ['IMG_0012'],
        ['IMG_0013'],
        ['IMG_0014'],
    ]

    window.close()
    del app


def test_break_scene_cancel_leaves_scene_state_unchanged(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7492', 'dimgray'),
            ('IMG_7493', 'blue'),
            ('IMG_7494', 'green'),
        ],
        scene_groups=[['IMG_7492', 'IMG_7493'], ['IMG_7494']],
    )
    captured: dict[str, object] = {}
    _confirm_next_break_scene(
        monkeypatch,
        accept=False,
        captured=captured,
    )

    scene = window._context_scene_from_thumbnail_position(
        _item_center(window.thumbnail_list, 0)
    )
    assert scene is not None
    window._break_scene_into_singletons(scene.scene_id)
    app.processEvents()

    assert captured['text'] == 'Break this scene into individual photos?'
    assert (
        captured['informative_text']
        == 'You can press Ctrl+Z to undo this action.'
    )
    assert captured['default_button'] == 'Cancel'
    assert captured['buttons'] == ['Break Scene', 'Cancel']
    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7492', 'IMG_7493'],
        ['IMG_7494'],
    ]
    assert window._metadata_undo_stack == []
    assert not (tmp_path / METADATA_FILENAME).exists()

    window.close()
    del app


def test_break_scene_context_menu_is_hidden_for_singletons_and_blank_strip(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7495', 'dimgray'),
            ('IMG_7496', 'blue'),
        ],
        scene_groups=[['IMG_7495'], ['IMG_7496']],
    )
    assert (
        window._context_scene_from_thumbnail_position(
            _item_center(window.thumbnail_list, 0)
        )
        is None
    )
    assert (
        window._context_scene_from_thumbnail_position(QPoint(-100, -100))
        is None
    )
    assert window._context_scene_from_scene_strip() is None
    app.processEvents()

    window.close()
    del app


def test_merge_selected_photos_can_create_multiple_manual_groups(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7470', 'dimgray'),
            ('IMG_7471', 'blue'),
            ('IMG_7472', 'green'),
            ('IMG_7473', 'white'),
        ],
    )
    window._enter_browse_mode()
    _select_list_rows(window.browse_list, [0, 1])
    app.processEvents()

    window.merge_scene_action.trigger()
    app.processEvents()

    _select_list_rows(window.browse_list, [2, 3])
    app.processEvents()

    assert window.merge_scene_action.isEnabled() is True

    window.merge_scene_action.trigger()
    app.processEvents()

    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7470', 'IMG_7471'],
        ['IMG_7472', 'IMG_7473'],
    ]

    window.close()
    del app


def test_merge_selected_photos_can_create_multiple_vertical_groups(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7474', 'dimgray'),
            ('IMG_7475', 'blue'),
            ('IMG_7476', 'green'),
            ('IMG_7477', 'white'),
        ],
    )
    _select_list_rows(window.thumbnail_list, [0, 1])
    app.processEvents()

    window.merge_scene_action.trigger()
    app.processEvents()

    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7474', 'IMG_7475'],
        ['IMG_7476'],
        ['IMG_7477'],
    ]
    assert window._scene_merge_selection_source == 'thumbnail'
    assert window.thumbnail_list.currentRow() == 0

    window._restore_photo_selection(['IMG_7476', 'IMG_7477'])
    window._scene_merge_selection_source = 'thumbnail'
    app.processEvents()

    assert window._mergeable_scene_photo_ids() == ['IMG_7476', 'IMG_7477']
    assert window.merge_scene_action.isEnabled() is True

    window.merge_scene_action.trigger()
    app.processEvents()

    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7474', 'IMG_7475'],
        ['IMG_7476', 'IMG_7477'],
    ]

    window.close()
    del app


def test_merge_vertical_selection_expands_scene_stack_and_singleton(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7478', 'dimgray'),
            ('IMG_7479', 'blue'),
            ('IMG_7480', 'green'),
            ('IMG_7481', 'white'),
        ],
        scene_groups=[['IMG_7478'], ['IMG_7479', 'IMG_7480'], ['IMG_7481']],
    )
    _select_list_rows(window.thumbnail_list, [0, 1])
    app.processEvents()

    assert window._mergeable_scene_photo_ids() == [
        'IMG_7478',
        'IMG_7479',
        'IMG_7480',
    ]

    window.merge_scene_action.trigger()
    app.processEvents()

    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7478', 'IMG_7479', 'IMG_7480'],
        ['IMG_7481'],
    ]

    window.close()
    del app


def test_merge_visible_vertical_cover_preserves_strip_position(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[(f'IMG_{index:04d}', 'dimgray') for index in range(40)],
    )
    window.resize(1200, 800)
    app.processEvents()

    cover_row = 12
    _select_list_rows(window.thumbnail_list, [cover_row, cover_row + 1])
    app.processEvents()

    scrollbar = window.thumbnail_list.verticalScrollBar()
    assert scrollbar.maximum() > 0
    _set_list_item_viewport_top(window.thumbnail_list, cover_row, 160)
    app.processEvents()

    cover_item = window.thumbnail_list.item(cover_row)
    assert cover_item is not None
    before_top = window.thumbnail_list.visualItemRect(cover_item).top()
    assert 0 <= before_top < window.thumbnail_list.viewport().height()

    window.merge_scene_action.trigger()
    app.processEvents()

    assert window.thumbnail_list.currentRow() == cover_row
    merged_item = window.thumbnail_list.item(cover_row)
    assert merged_item is not None
    after_top = window.thumbnail_list.visualItemRect(merged_item).top()
    assert abs(after_top - before_top) <= 1
    assert [scene.photo_ids for scene in window.library.scenes][cover_row] == [
        'IMG_0012',
        'IMG_0013',
    ]

    window.close()
    del app


def test_merge_offscreen_vertical_cover_scrolls_new_scene_to_top(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[(f'IMG_{index:04d}', 'dimgray') for index in range(40)],
    )
    window.resize(1200, 800)
    app.processEvents()

    cover_row = 4
    top_item = window.thumbnail_list.item(0)
    assert top_item is not None
    expected_top = window.thumbnail_list.visualItemRect(top_item).top()

    _select_list_rows(window.thumbnail_list, [cover_row, cover_row + 1])
    app.processEvents()

    scrollbar = window.thumbnail_list.verticalScrollBar()
    assert scrollbar.maximum() > 0
    scrollbar.setValue(scrollbar.maximum())
    app.processEvents()

    cover_item = window.thumbnail_list.item(cover_row)
    assert cover_item is not None
    assert window.thumbnail_list.visualItemRect(cover_item).bottom() < 0

    window.merge_scene_action.trigger()
    app.processEvents()

    assert window.thumbnail_list.currentRow() == cover_row
    merged_item = window.thumbnail_list.item(cover_row)
    assert merged_item is not None
    after_top = window.thumbnail_list.visualItemRect(merged_item).top()
    assert abs(after_top - expected_top) <= 1
    assert [scene.photo_ids for scene in window.library.scenes][cover_row] == [
        'IMG_0004',
        'IMG_0005',
    ]

    window.close()
    del app


def test_merge_selected_scene_stacks_ignores_stale_scene_strip_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7480', 'dimgray'),
            ('IMG_7481', 'blue'),
            ('IMG_7482', 'green'),
            ('IMG_7483', 'white'),
        ],
    )
    _select_list_rows(window.thumbnail_list, [0, 1])
    app.processEvents()

    window.merge_scene_action.trigger()
    app.processEvents()

    assert [
        window.scene_list.row(item)
        for item in window.scene_list.selectedItems()
    ] == [0]

    window._restore_photo_selection(['IMG_7482', 'IMG_7483'])
    window._scene_merge_selection_source = 'thumbnail'
    app.processEvents()

    assert window._mergeable_scene_photo_ids() == ['IMG_7482', 'IMG_7483']

    window.merge_scene_action.trigger()
    app.processEvents()

    assert [scene.photo_ids for scene in window.library.scenes] == [
        ['IMG_7480', 'IMG_7481'],
        ['IMG_7482', 'IMG_7483'],
    ]

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
    set_qt_active_window(window)
    app.processEvents()

    window.thumbnail_list.setFocus(Qt.OtherFocusReason)
    app.processEvents()

    window._show_progress('Loading', 50)

    assert window._busy is True
    assert app.focusWidget() is not window.show_af_point_toggle
    assert app.focusWidget() is not window.show_clipping_toggle
    assert window.menuBar().isEnabled() is False
    assert window.open_button.isEnabled() is False
    assert window.organize_button.isEnabled() is False
    assert window.theme_toggle.isEnabled() is False
    assert window.show_af_point_toggle.isEnabled() is False
    assert window.show_clipping_toggle.isEnabled() is False
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
    assert window.show_clipping_toggle.isEnabled() is True
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


def test_main_window_progress_snapshot_renders_stage_rows(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify structured progress shows stage rows with workflow count text.

    This protects the blocking overlay from showing the old aggregate bar and
    protects metadata batch counts from looking like photo totals while other
    folder-load stages keep the generic item-count wording.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_7420', 'dimgray')],
    )
    reporter = window._folder_load_progress_reporter()

    reporter.start_stage('scan', overall_progress=5)
    reporter.update_stage(
        'metadata',
        label='Loading EXIF data (20 photos per batch)',
        current=1,
        total=2,
        overall_progress=25,
    )
    app.processEvents()

    metadata_label_texts = {
        label.text()
        for label in window.progress_stage_list.findChildren(QLabel)
    }
    assert window.progress_overlay.isVisible() is True
    assert window.overlay_progress_bar.isVisible() is False
    assert window.progress_stage_list.isVisible() is True
    assert 'Loading EXIF data (20 photos per batch)' in metadata_label_texts
    assert 'Batch 1 of 2' in metadata_label_texts

    reporter.update_stage('records', current=4, total=37, overall_progress=50)
    app.processEvents()

    record_label_texts = {
        label.text()
        for label in window.progress_stage_list.findChildren(QLabel)
    }
    assert 'Building photo list' in record_label_texts
    assert '4 of 37' in record_label_texts

    window._hide_progress()
    assert window.progress_stage_list.isHidden() is True

    window.close()
    del app


def test_main_window_structured_scene_progress_does_not_show_scalar_bar(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify structured scene progress keeps the stage-row overlay visible.

    Scene detection reporters emit legacy tuples for compatibility. The worker
    route must suppress those paired tuples so scalar progress does not clear
    the structured rows and flash the old aggregate bar.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_7425', 'dimgray')],
    )

    class StructuredSceneLibrary:
        @staticmethod
        def detect_scenes(
                *,
                progress_callback: Any,
                progress_snapshot_callback: Any = None,
        ) -> None:
            reporter = workflows_module.ProgressReporter(
                'Detecting scenes',
                (
                    workflows_module.ProgressStageDefinition(
                        'features', 'Extracting preview features'
                    ),
                ),
                progress_callback=progress_callback,
                snapshot_callback=progress_snapshot_callback,
            )
            reporter.update_stage(
                'features',
                current=1,
                total=2,
                overall_progress=50,
            )

    worker = workflows_module.SceneDetectionWorker(StructuredSceneLibrary())
    worker.progress.connect(window._handle_scene_progress)
    worker.progress_snapshot.connect(window._handle_scene_progress_snapshot)

    window._show_progress('Preparing scene detection...', 0)
    worker.run()
    app.processEvents()

    label_texts = {
        label.text()
        for label in window.progress_stage_list.findChildren(QLabel)
    }
    assert window.progress_overlay.isVisible() is True
    assert window.progress_stage_list.isVisible() is True
    assert window.overlay_progress_bar.isVisible() is False
    assert 'Extracting preview features' in label_texts
    assert '1 of 2' in label_texts

    window.close()
    del app


def test_scene_detection_finish_preserves_structured_progress_rows(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify scene-finish list rebuilds do not flash the scalar progress bar.

    Scene detection uses structured progress rows, then completion rebuilds the
    thumbnail, browse, and scene lists before hiding the overlay. The finish
    path must keep those rows active until cleanup instead of clearing them
    with the legacy scalar progress UI.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7435', 'dimgray'),
            ('IMG_7436', 'blue'),
        ],
    )
    reporter = workflows_module.ProgressReporter(
        'Detecting scenes',
        (
            workflows_module.ProgressStageDefinition(
                'features', 'Extracting preview features'
            ),
            workflows_module.ProgressStageDefinition(
                'grouping', 'Grouping scenes'
            ),
        ),
    )
    snapshot = reporter.update_stage(
        'grouping',
        current=2,
        total=2,
        overall_progress=99,
        complete=True,
    )
    window._handle_scene_progress_snapshot(snapshot)
    app.processEvents()

    set_scene_detection_result(window, [['IMG_7435', 'IMG_7436']])
    # Capture the transient overlay state immediately before cleanup hides it.
    # Once the method returns, the flash-prone state is gone.
    overlay_state_before_hide: list[tuple[bool, bool, str, set[str]]] = []
    original_hide_progress = window._hide_progress

    def record_overlay_state_before_hide() -> None:
        label_texts = {
            label.text()
            for label in window.progress_stage_list.findChildren(QLabel)
        }
        overlay_state_before_hide.append((
            window.progress_stage_list.isVisible(),
            window.overlay_progress_bar.isVisible(),
            window.overlay_message_label.text(),
            label_texts,
        ))
        original_hide_progress()

    monkeypatch.setattr(
        window, '_hide_progress', record_overlay_state_before_hide
    )

    window._handle_scene_finished()
    app.processEvents()

    assert len(overlay_state_before_hide) == 1
    stage_list_visible, scalar_bar_visible, message, label_texts = (
        overlay_state_before_hide[0]
    )
    assert stage_list_visible is True
    assert scalar_bar_visible is False
    assert message == 'Scene detection finished'
    assert 'Grouping scenes' in label_texts
    assert '2 of 2' in label_texts
    assert window.progress_overlay.isHidden() is True

    window.close()
    del app


def test_main_window_list_progress_counts_completed_preview_rows(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify list progress advances only after preview-backed row creation.

    Thumbnail rendering happens inside ``_add_photo_item``. This regression
    test protects the overlay from reporting ``N of N`` before the final
    preview load has actually returned.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7430', 'dimgray'),
            ('IMG_7431', 'darkgray'),
        ],
    )
    snapshots = []
    reporter = workflows_module.ProgressReporter(
        'Loading folder',
        workflows_module.LOAD_WORKFLOW_PROGRESS_STAGES,
        snapshot_callback=snapshots.append,
    )
    original_get_preview_path = window.library.get_preview_path
    active_stage = {'stage_id': 'thumbnails'}
    progress_before_preview: list[tuple[str, int | None]] = []

    def latest_stage_current(stage_id: str) -> int | None:
        stage = next(
            stage
            for stage in snapshots[-1].stages
            if stage.stage_id == stage_id
        )
        return stage.current

    def record_get_preview_path(photo_id: str, kind: str) -> Path:
        if kind == 'thumb':
            progress_before_preview.append((
                photo_id,
                latest_stage_current(active_stage['stage_id']),
            ))

        return original_get_preview_path(photo_id, kind)

    monkeypatch.setattr(
        window.library, 'get_preview_path', record_get_preview_path
    )

    window._populate_thumbnail_list(
        show_progress=True,
        scroll_current_item_into_view=False,
        progress_reporter=reporter,
    )

    assert progress_before_preview == [('IMG_7430', 0), ('IMG_7431', 1)]
    thumbnail_stage = next(
        stage
        for stage in snapshots[-1].stages
        if stage.stage_id == 'thumbnails'
    )
    assert thumbnail_stage.count_text() == '2 of 2'
    assert thumbnail_stage.status == 'complete'

    progress_before_preview.clear()
    active_stage['stage_id'] = 'browse'
    window._populate_browse_list(
        show_progress=True,
        scroll_current_item_into_view=False,
        progress_reporter=reporter,
    )

    assert progress_before_preview == [('IMG_7430', 0), ('IMG_7431', 1)]
    browse_stage = next(
        stage for stage in snapshots[-1].stages if stage.stage_id == 'browse'
    )
    assert browse_stage.count_text() == '2 of 2'
    assert browse_stage.status == 'complete'

    window.close()
    del app


def test_main_window_scene_stack_progress_counts_scene_rows(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify scene-stack progress counts rendered scene rows, not photos.

    Scene mode renders one thumbnail row per scene stack. Progress should
    therefore advance from completed scene rows instead of the number of photos
    contained in those scenes.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_9200', 'dimgray'),
            ('IMG_9201', 'darkgray'),
            ('IMG_9202', 'blue'),
        ],
        scene_groups=[['IMG_9200', 'IMG_9201'], ['IMG_9202']],
    )
    snapshots = []
    reporter = workflows_module.ProgressReporter(
        'Loading folder',
        workflows_module.LOAD_WORKFLOW_PROGRESS_STAGES,
        snapshot_callback=snapshots.append,
    )
    original_get_preview_path = window.library.get_preview_path
    progress_before_preview: list[tuple[str, int | None]] = []

    def latest_thumbnail_current() -> int | None:
        stage = next(
            stage
            for stage in snapshots[-1].stages
            if stage.stage_id == 'thumbnails'
        )
        return stage.current

    def record_get_preview_path(photo_id: str, kind: str) -> Path:
        if kind == 'thumb':
            progress_before_preview.append((
                photo_id,
                latest_thumbnail_current(),
            ))

        return original_get_preview_path(photo_id, kind)

    monkeypatch.setattr(
        window.library, 'get_preview_path', record_get_preview_path
    )

    window._populate_thumbnail_list(
        show_progress=True,
        scroll_current_item_into_view=False,
        progress_reporter=reporter,
    )

    thumbnail_stage = next(
        stage
        for stage in snapshots[-1].stages
        if stage.stage_id == 'thumbnails'
    )
    assert progress_before_preview == [('IMG_9200', 0), ('IMG_9202', 1)]
    assert thumbnail_stage.label == 'Preparing scene stacks'
    assert thumbnail_stage.count_text() == '2 of 2'
    assert thumbnail_stage.status == 'complete'

    window.close()
    del app


def test_main_window_handle_scene_failed_and_clear_worker_restore_ui(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify scene-failure UI recovery waits for matching worker cleanup.

    The failed signal restores the error/progress state, but the action buttons
    stay guarded until the finished cleanup clears the exact thread slot.
    """
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
    scene_thread = object()
    scene_worker = object()
    window._scene_thread = scene_thread
    window._scene_worker = scene_worker
    window._show_progress('Preparing scenes', 10)

    window._handle_scene_failed('boom')

    assert errors == [('Scene Detection Failed', 'boom')]
    assert window._busy is False
    assert window.progress_overlay.isHidden() is True
    assert window.detect_button.isEnabled() is True
    assert window.organize_button.isEnabled() is False

    window._clear_scene_worker(scene_thread, scene_worker)

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
        'photos': {
            'IMG_7500': {
                'rating': 5,
                'color_label': 'purple',
                'flag': 'picked',
            }
        }
    }

    window.rating_actions[None].trigger()
    window.color_label_actions[None].trigger()
    window.flag_actions[None].trigger()
    app.processEvents()

    assert photo.rating is None
    assert photo.color_label is None
    assert photo.flag is None
    assert json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    ) == {'photos': {}}
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

    set_qt_active_window(window)
    app.processEvents()
    window.thumbnail_list.setFocus(Qt.OtherFocusReason)
    app.processEvents()
    QTest.keyClick(window.thumbnail_list.viewport(), Qt.Key_QuoteLeft)
    app.processEvents()

    assert photo.color_label is None
    assert json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    ) == {'photos': {}}
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
    Successful folder loads should focus the strip without an empty dialog.

    This protects the normal load path from the empty-folder warning while
    keeping immediate Down-key navigation on the thumbnail strip.
    """
    create_jpeg(tmp_path / 'IMG_9080.JPG', 'dimgray')
    create_jpeg(tmp_path / 'IMG_9081.JPG', 'blue')
    stub_read_exif(monkeypatch, {})
    monkeypatch.setattr(
        QFileDialog,
        'getExistingDirectory',
        lambda *_args, **_kwargs: str(tmp_path),
    )
    empty_dialogs: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        'information',
        lambda _parent, title, text, *_args: empty_dialogs.append((
            title,
            text,
        )),
    )

    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.show()
    set_qt_active_window(window)
    app.processEvents()

    window.choose_folder()
    app.processEvents()
    if not window.isActiveWindow():
        pytest.skip('Window activation is not available in this Qt session')

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
    assert empty_dialogs == []

    focus_widget = app.focusWidget()
    assert focus_widget is not None
    QTest.keyClick(focus_widget, Qt.Key_Down)
    app.processEvents()

    assert window.current_photo_id == 'IMG_9081'
    assert window.thumbnail_list.currentRow() == 1

    window.close()
    del app


def test_main_window_choose_folder_progress_reports_all_load_stages(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify real folder-open progress reaches every structured load stage.

    Helper-level tests cover the reporter and list loops separately. This
    integration check keeps ``choose_folder`` wired to the shared reporter
    through folder loading, thumbnail rows, and browse-grid rows.
    """
    create_jpeg(tmp_path / 'IMG_9090.JPG', 'dimgray')
    create_jpeg(tmp_path / 'IMG_9091.JPG', 'blue')
    monkeypatch.setattr(
        QFileDialog,
        'getExistingDirectory',
        lambda *_args, **_kwargs: str(tmp_path),
    )

    def fake_read_exif_metadata(
            files: list[Path],
            *,
            batch_size: int,
            batch_progress_callback: Any,
    ) -> dict[str, dict[str, Any]]:
        del batch_size
        batch_progress_callback(1, 1, 20)
        return {path.name: {} for path in files}

    monkeypatch.setattr(
        core_exif_module, 'read_exif_metadata', fake_read_exif_metadata
    )
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.show()
    app.processEvents()
    progress_before_hide: list[
        tuple[
            set[str],
            dict[str, tuple[int, int, bool]],
            set[str],
            bool,
            bool,
        ]
    ] = []
    original_hide_progress = window._hide_progress

    def record_progress_before_hide() -> None:
        rows = window.progress_stage_list._rows
        progress_before_hide.append((
            set(rows),
            {
                stage_id: (
                    row.progress_bar.value(),
                    row.progress_bar.maximum(),
                    row.progress_bar.isVisible(),
                )
                for stage_id, row in rows.items()
            },
            {
                label.text()
                for label in window.progress_stage_list.findChildren(QLabel)
                if label.text()
            },
            window.progress_stage_list.isVisible(),
            window.overlay_progress_bar.isVisible(),
        ))
        original_hide_progress()

    monkeypatch.setattr(window, '_hide_progress', record_progress_before_hide)

    window.choose_folder()
    app.processEvents()

    assert len(progress_before_hide) == 1
    (
        stage_ids,
        stage_progress,
        label_texts,
        stage_list_visible,
        scalar_bar_visible,
    ) = progress_before_hide[0]
    assert stage_ids == {
        'scan',
        'metadata',
        'records',
        'thumbnails',
        'browse',
    }
    assert stage_list_visible is True
    assert scalar_bar_visible is False
    assert stage_progress == {
        'scan': (100, 100, True),
        'metadata': (1, 1, True),
        'records': (2, 2, True),
        'thumbnails': (2, 2, True),
        'browse': (2, 2, True),
    }
    assert {
        'Scanning folder',
        'Loading EXIF data (20 photos per batch)',
        'Batch 1 of 1',
        'Building photo list',
        'Preparing thumbnails',
        'Preparing browse grid',
        '2 of 2',
    } <= label_texts
    assert window.progress_overlay.isHidden() is True
    assert window.library.current_folder == tmp_path.resolve()
    assert len(window.library.photos) == 2

    window.close()
    del app


def test_main_window_undo_reload_progress_reports_all_load_stages(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify post-undo folder reloads keep structured progress wired.

    Undo completion should reuse the same multi-stage load/list reporter as a
    manual folder open instead of falling back to stale scalar operation text.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_9120', 'dimgray'),
            ('IMG_9121', 'blue'),
        ],
    )

    def fake_read_exif_metadata(
            files: list[Path],
            *,
            batch_size: int,
            batch_progress_callback: Any,
    ) -> dict[str, dict[str, Any]]:
        batch_progress_callback(1, 1, batch_size)
        return {path.name: {} for path in files}

    monkeypatch.setattr(
        core_exif_module, 'read_exif_metadata', fake_read_exif_metadata
    )
    # This helper keeps its preview cache under ``tmp_path``. Direct loading
    # keeps the reload assertion focused on the visible photo set instead of
    # recursively discovering test-generated cache JPEGs.
    window.library.set_load_recursively(False)
    window._show_progress('Operation complete', 50)

    window._reload_current_folder_after_undo()
    app.processEvents()

    rows = window.progress_stage_list._rows
    stage_progress = {
        stage_id: (
            row.progress_bar.value(),
            row.progress_bar.maximum(),
            row.progress_bar.isVisible(),
        )
        for stage_id, row in rows.items()
    }
    label_texts = {
        label.text()
        for label in window.progress_stage_list.findChildren(QLabel)
        if label.text()
    }

    assert set(rows) == {
        'scan',
        'metadata',
        'records',
        'thumbnails',
        'browse',
    }
    assert window.progress_stage_list.isVisible() is True
    assert window.overlay_progress_bar.isVisible() is False
    assert stage_progress == {
        'scan': (100, 100, True),
        'metadata': (1, 1, True),
        'records': (2, 2, True),
        'thumbnails': (2, 2, True),
        'browse': (2, 2, True),
    }
    assert {
        'Building photo list',
        'Preparing thumbnails',
        'Preparing browse grid',
        '2 of 2',
    } <= label_texts

    window._hide_progress()
    window.close()
    del app


def test_main_window_undo_reload_replaces_structured_undo_progress(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify undo reload progress replaces stale undo stage rows immediately.

    The undo workflow switches directly from structured undo progress to
    structured folder-load progress. Stale undo rows must be hidden before the
    Qt deferred-delete pass so their text cannot overlap load rows.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_9125', 'dimgray'),
            ('IMG_9126', 'blue'),
        ],
    )

    def fake_read_exif_metadata(
            files: list[Path],
            *,
            batch_size: int,
            batch_progress_callback: Any,
    ) -> dict[str, dict[str, Any]]:
        batch_progress_callback(1, 1, batch_size)
        return {path.name: {} for path in files}

    monkeypatch.setattr(
        core_exif_module, 'read_exif_metadata', fake_read_exif_metadata
    )
    window.library.set_load_recursively(False)
    reporter = workflows_module.ProgressReporter(
        'Undoing photo organization',
        (
            workflows_module.ProgressStageDefinition(
                'undo', 'Undoing photo organization'
            ),
        ),
    )
    undo_snapshot = reporter.update_stage(
        'undo',
        current=1,
        total=2,
        overall_progress=50,
    )
    window._show_progress_snapshot(undo_snapshot)
    undo_row = window.progress_stage_list._rows['undo']

    window._reload_current_folder_after_undo()
    app.processEvents()

    rows = window.progress_stage_list._rows
    label_texts = {
        label.text()
        for label in window.progress_stage_list.findChildren(QLabel)
        if label.text()
    }

    assert set(rows) == {
        'scan',
        'metadata',
        'records',
        'thumbnails',
        'browse',
    }
    assert undo_row.isHidden() is True
    assert undo_row.parentWidget() is None
    assert 'Undoing photo organization' not in label_texts
    assert {'Building photo list', 'Preparing browse grid', '2 of 2'} <= (
        label_texts
    )

    window._hide_progress()
    window.close()
    del app


def test_main_window_recursive_reload_progress_reports_all_load_stages(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify Include-subfolders reloads keep structured progress wired.

    The recursive preference path reloads the current folder through a separate
    helper from manual opens and post-operation reloads. Capture the overlay
    immediately before cleanup so a scalar-progress regression cannot pass
    unnoticed after the rows are hidden.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_9130', 'dimgray'),
            ('IMG_9131', 'blue'),
        ],
    )

    def fake_read_exif_metadata(
            files: list[Path],
            *,
            batch_size: int,
            batch_progress_callback: Any,
    ) -> dict[str, dict[str, Any]]:
        batch_progress_callback(1, 1, batch_size)
        return {path.name: {} for path in files}

    monkeypatch.setattr(
        core_exif_module, 'read_exif_metadata', fake_read_exif_metadata
    )
    progress_before_hide: list[
        tuple[
            set[str],
            dict[str, tuple[int, int, bool]],
            set[str],
            bool,
            bool,
        ]
    ] = []
    original_hide_progress = window._hide_progress

    def record_progress_before_hide() -> None:
        rows = window.progress_stage_list._rows
        progress_before_hide.append((
            set(rows),
            {
                stage_id: (
                    row.progress_bar.value(),
                    row.progress_bar.maximum(),
                    row.progress_bar.isVisible(),
                )
                for stage_id, row in rows.items()
            },
            {
                label.text()
                for label in window.progress_stage_list.findChildren(QLabel)
                if label.text()
            },
            window.progress_stage_list.isVisible(),
            window.overlay_progress_bar.isVisible(),
        ))
        original_hide_progress()

    monkeypatch.setattr(window, '_hide_progress', record_progress_before_hide)

    window._reload_current_folder_after_recursive_preference_change(
        load_recursively=False
    )
    app.processEvents()

    assert len(progress_before_hide) == 1
    (
        stage_ids,
        stage_progress,
        label_texts,
        stage_list_visible,
        scalar_bar_visible,
    ) = progress_before_hide[0]
    assert stage_ids == {
        'scan',
        'metadata',
        'records',
        'thumbnails',
        'browse',
    }
    assert stage_list_visible is True
    assert scalar_bar_visible is False
    assert stage_progress == {
        'scan': (100, 100, True),
        'metadata': (1, 1, True),
        'records': (2, 2, True),
        'thumbnails': (2, 2, True),
        'browse': (2, 2, True),
    }
    assert {
        'Building photo list',
        'Preparing thumbnails',
        'Preparing browse grid',
        '2 of 2',
    } <= label_texts
    assert window.library.load_recursively is False
    assert window.progress_overlay.isHidden() is True

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
    assert saved['photos']['IMG_K100']['rating'] == expected_rating

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
    assert saved == {'photos': {}}

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
    assert saved['photos']['IMG_K200']['color_label'] == expected_label

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
    assert saved == {'photos': {}}

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
    assert saved['photos']['IMG_K300']['flag'] == expected_flag

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
    assert saved == {'photos': {}}

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
    assert saved['photos']['IMG_M100'][field] == expected

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
    assert saved == {'photos': {}}

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
    set_qt_active_window(window)
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
    scene_thread = object()
    scene_worker = object()
    window._scene_thread = scene_thread
    window._scene_worker = scene_worker
    window._handle_scene_finished()
    app.processEvents()

    assert window.thumbnail_list.count() == 2
    assert window.thumbnail_list.currentRow() == 1

    # The real restore opportunity happens after the worker thread is cleared;
    # before that, background-task guards intentionally block focus changes.
    window._clear_scene_worker(scene_thread, scene_worker)
    app.processEvents()

    assert _list_widget_has_focus(app, window.thumbnail_list) is True
    assert app.focusWidget() is not window.theme_toggle
    assert app.focusWidget() is not window.show_af_point_toggle
    assert app.focusWidget() is not window.show_clipping_toggle
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
                organize_options=FlagOrganizeFilesOptions(
                    criterion='flag',
                    action='copy',
                    output_parent=tmp_path,
                    flag_folder_mode='picked_rejected',
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


def test_main_window_operation_worker_legacy_progress_updates_overlay(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify operation workers still wire scalar progress into the overlay.

    Structured progress is the normal organizer path, but legacy-only worker
    callables must not leave the UI stuck on the initial preparation message.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9105', 'dimgray')],
    )
    monkeypatch.setattr(QThread, 'start', lambda _thread: None)
    request = OrganizerDialogResult(
        mode='reorganize',
        organize_options=FlagOrganizeFilesOptions(
            criterion='flag',
            action='copy',
            output_parent=tmp_path,
            flag_folder_mode='picked_rejected',
            conflict_policy='fail',
        ),
    )

    window._start_organizer_request(request)
    assert window._operation_worker is not None

    window._operation_worker.progress.emit('Legacy operation progress', 42)
    app.processEvents()

    assert window.overlay_message_label.text() == 'Legacy operation progress'
    assert window.overlay_progress_bar.isVisible() is True
    assert window.overlay_progress_bar.value() == 42

    finished_thread = window._operation_thread
    finished_worker = window._operation_worker
    window._clear_operation_worker(finished_thread, finished_worker)
    window.close()
    del app


def test_main_window_structured_organizer_progress_updates_overlay(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify organizer snapshot progress renders stage rows in MainWindow.

    Worker-level tests cover callback routing; this checks the actual main
    window signal connection used by organizer operations.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9110', 'dimgray')],
    )
    monkeypatch.setattr(QThread, 'start', lambda _thread: None)
    request = OrganizerDialogResult(
        mode='reorganize',
        organize_options=FlagOrganizeFilesOptions(
            criterion='flag',
            action='copy',
            output_parent=tmp_path,
            flag_folder_mode='picked_rejected',
            conflict_policy='fail',
        ),
    )
    reporter = workflows_module.ProgressReporter(
        'Organizing photos',
        (
            workflows_module.ProgressStageDefinition(
                'organize', 'Organizing photo files'
            ),
        ),
    )
    snapshot = reporter.update_stage(
        'organize',
        current=1,
        total=2,
        overall_progress=50,
    )

    window._start_organizer_request(request)
    assert window._operation_worker is not None

    window._operation_worker.progress_snapshot.emit(snapshot)
    app.processEvents()

    label_texts = {
        label.text()
        for label in window.progress_stage_list.findChildren(QLabel)
    }
    assert window.progress_overlay.isVisible() is True
    assert window.progress_stage_list.isVisible() is True
    assert window.overlay_progress_bar.isVisible() is False
    assert 'Organizing photo files' in label_texts
    assert '1 of 2' in label_texts

    finished_thread = window._operation_thread
    finished_worker = window._operation_worker
    window._clear_operation_worker(finished_thread, finished_worker)
    window.close()
    del app


def test_main_window_structured_undo_progress_updates_overlay(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify undo snapshot progress renders stage rows in MainWindow.

    Undo uses a separate worker setup path from organizer runs, so this keeps
    its structured progress signal connected to the overlay.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9115', 'dimgray')],
    )
    monkeypatch.setattr(QThread, 'start', lambda _thread: None)
    reporter = workflows_module.ProgressReporter(
        'Undoing photo organization',
        (
            workflows_module.ProgressStageDefinition(
                'undo', 'Undoing photo organization'
            ),
        ),
    )
    snapshot = reporter.update_stage(
        'undo',
        current=1,
        total=3,
        overall_progress=33,
    )

    window._start_undo_operation(UndoPlan())
    assert window._operation_worker is not None

    window._operation_worker.progress_snapshot.emit(snapshot)
    app.processEvents()

    label_texts = {
        label.text()
        for label in window.progress_stage_list.findChildren(QLabel)
    }
    assert window.progress_overlay.isVisible() is True
    assert window.progress_stage_list.isVisible() is True
    assert window.overlay_progress_bar.isVisible() is False
    assert 'Undoing photo organization' in label_texts
    assert '1 of 3' in label_texts

    finished_thread = window._operation_thread
    finished_worker = window._operation_worker
    window._clear_operation_worker(finished_thread, finished_worker)
    window.close()
    del app


@pytest.mark.parametrize(
    ('initially_running', 'expected_quit_calls'),
    [
        pytest.param(True, 1, id='running'),
        pytest.param(False, 0, id='stopped-slot'),
    ],
)
def test_main_window_close_defers_until_operation_thread_clears(
        initially_running: bool,
        expected_quit_calls: int,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify close hides while organizer/undo thread cleanup is pending.

    File-operation workers may drain after the user closes the window. The
    visible culling window should disappear immediately, while final teardown
    still waits for stored Qt wrapper cleanup. This observes ``destroyed``
    because visibility is already false before the queued final close runs.
    """

    class FakeThread:
        def __init__(self) -> None:
            self.running = initially_running
            self.quit_calls = 0

        def isRunning(self) -> bool:  # noqa: N802 - Qt API
            return self.running

        def quit(self) -> None:
            self.quit_calls += 1

    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9110', 'dimgray')],
    )
    fake_thread = FakeThread()
    fake_worker = object()
    destroyed: list[str] = []
    # Match production ownership so `destroyed` proves the deferred final close
    # accepted, rather than only proving that the first close hid the window.
    window.setAttribute(Qt.WA_DeleteOnClose, True)
    window.destroyed.connect(lambda *_args: destroyed.append('destroyed'))
    window._operation_thread = fake_thread
    window._operation_worker = fake_worker

    window.close()
    app.processEvents()

    assert window.isVisible() is False
    assert window.progress_overlay.isHidden() is True
    assert window._close_after_background_tasks is True
    assert fake_thread.quit_calls == expected_quit_calls
    assert destroyed == []

    fake_thread.running = False
    window._clear_operation_worker(fake_thread, fake_worker)

    assert window.isVisible() is False
    assert window._close_after_background_tasks is False
    assert destroyed == []

    # The cleanup path posts a zero-delay close, and Qt delivers deletion on a
    # later event turn. Drain both turns so the assertion observes teardown.
    for _ in range(2):
        app.processEvents()

    assert destroyed == ['destroyed']
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
            organize_options=FlagOrganizeFilesOptions(
                criterion='flag',
                action='move',
                output_parent=tmp_path,
                flag_folder_mode='picked_rejected',
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


def test_main_window_operation_finished_after_move_skips_reload_and_shows_dialog(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify move completion freezes the workspace without reloading.

    This guards the subtle post-move state where loaded records may point at
    old paths: the finished dialog still appears, but navigation and tagging
    must remain blocked until Open Folder or immediate Undo recovers the UI.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9200', 'dimgray'), ('IMG_9201', 'navy')],
    )
    reload_calls: list[str] = []
    dialog_calls: list[
        tuple[OperationSummary, OrganizerDialogResult | None]
    ] = []
    monkeypatch.setattr(
        window.library,
        'load_folder',
        lambda *_args, **_kwargs: reload_calls.append('reload'),
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
        organize_options=FlagOrganizeFilesOptions(
            criterion='flag',
            action='move',
            output_parent=tmp_path,
            flag_folder_mode='picked_rejected',
            conflict_policy='fail',
        ),
    )
    window._show_progress('Organizing', 50)
    assert window.current_photo_id == 'IMG_9200'

    window._handle_operation_finished(
        OperationSummary(
            processed_photos=1,
            moved_files=2,
            undo_plan=UndoPlan(),
        )
    )

    assert reload_calls == []
    assert window.current_photo_id == 'IMG_9200'
    assert window._main_view_frozen_after_move_organize is True
    assert window.move_organize_frozen_overlay.isVisible() is True
    assert window.move_organize_frozen_title_label.text() == 'Photos moved'
    assert window.move_organize_frozen_detail_label.text() == (
        'Open another folder to continue.'
    )
    assert window.open_button.isEnabled() is True
    assert window.open_action.isEnabled() is True
    assert window.theme_toggle.isEnabled() is True
    assert window.menuBar().isEnabled() is True
    assert window.detect_button.isEnabled() is False
    assert window.organize_button.isEnabled() is False
    assert window.organize_action.isEnabled() is False
    assert window.filter_button.isEnabled() is False
    assert window.photo_load_recursively_checkbox.isEnabled() is False
    assert window.photo_sort_reverse_checkbox.isEnabled() is False
    assert all(
        button.isEnabled() is False
        for button in window.photo_sort_buttons.values()
    )
    assert window.thumbnail_list.isEnabled() is False
    assert window.browse_list.isEnabled() is False
    assert window.scene_list.isEnabled() is False
    assert window.viewer.isEnabled() is False
    assert window.compare_viewer.isEnabled() is False
    assert window.browse_mode_shortcut.isEnabled() is False
    assert window.compare_mode_shortcut.isEnabled() is False
    assert all(
        action.isEnabled() is False for action in window._assignment_actions
    )
    assert all(
        shortcut.isEnabled() is False
        for shortcut in window._assignment_shortcuts
    )
    assert window._busy is False
    assert window._operation_kind is None
    assert len(dialog_calls) == 1
    assert dialog_calls[0][0].moved_files == 2
    assert dialog_calls[0][1] is not None
    assert dialog_calls[0][1].mode == 'reorganize'

    window.close()
    del app


def test_main_window_move_frozen_overlay_panel_fits_message(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify the post-move frozen overlay message is not clipped.

    The frozen overlay explains why navigation and tagging are disabled, so
    this regression test checks the label geometry directly instead of only
    asserting that the overlay is visible.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9230', 'dimgray')],
    )
    window.resize(640, 360)
    app.processEvents()

    window._set_main_view_frozen_after_move_organize(frozen=True)
    app.processEvents()

    panel = window.move_organize_frozen_panel
    title = window.move_organize_frozen_title_label
    detail = window.move_organize_frozen_detail_label
    margins = panel.layout().contentsMargins()
    # Word-wrapped QLabel height depends on the final resolved width.
    # heightForWidth() catches the clipped two-line body that caused the
    # frozen overlay to regress visually.
    expected_min_height = (
        margins.top()
        + title.sizeHint().height()
        + panel.layout().spacing()
        + detail.heightForWidth(detail.width())
        + margins.bottom()
    )

    assert panel.width() <= build_module.MOVE_ORGANIZE_FROZEN_PANEL_MAX_WIDTH
    assert panel.height() >= expected_min_height
    assert panel.rect().contains(title.geometry())
    assert panel.rect().contains(detail.geometry())
    assert title.height() >= title.sizeHint().height()
    assert detail.height() >= detail.heightForWidth(detail.width())

    window.close()
    del app


def test_main_window_operation_finished_after_copy_keeps_view_interactive(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify copy completion leaves the existing workspace interactive.

    Copies do not invalidate source photo paths, so this prevents the move-only
    freeze from leaking into the safe organizer path.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9250', 'dimgray')],
    )
    reload_calls: list[str] = []
    dialog_calls: list[
        tuple[OperationSummary, OrganizerDialogResult | None]
    ] = []
    monkeypatch.setattr(
        window.library,
        'load_folder',
        lambda *_args, **_kwargs: reload_calls.append('reload'),
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
        organize_options=FlagOrganizeFilesOptions(
            criterion='flag',
            action='copy',
            output_parent=tmp_path,
            flag_folder_mode='picked_rejected',
            conflict_policy='fail',
        ),
    )
    window._show_progress('Organizing', 50)

    window._handle_operation_finished(
        OperationSummary(
            processed_photos=1,
            copied_files=2,
            undo_plan=UndoPlan(),
        )
    )

    assert reload_calls == []
    assert window._main_view_frozen_after_move_organize is False
    assert window.move_organize_frozen_overlay.isHidden() is True
    assert window.current_photo_id == 'IMG_9250'
    assert window.open_button.isEnabled() is True
    assert window.organize_button.isEnabled() is True
    assert window.filter_button.isEnabled() is True
    assert window.thumbnail_list.isEnabled() is True
    assert window.viewer.isEnabled() is True
    assert all(
        action.isEnabled() is True for action in window._assignment_actions
    )
    assert len(dialog_calls) == 1
    assert dialog_calls[0][0].copied_files == 2
    assert dialog_calls[0][1] is not None
    assert dialog_calls[0][1].mode == 'reorganize'

    window.close()
    del app


def test_main_window_move_frozen_state_blocks_workspace_actions(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify frozen workspaces block direct and UI-routed photo actions.

    Disabled widgets alone do not protect programmatic QAction, shortcut, or
    helper calls, so this regression test exercises the central guard paths.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9260', 'dimgray'), ('IMG_9261', 'navy')],
    )
    _select_list_rows(window.thumbnail_list, [0, 1])
    progress_calls: list[str] = []
    organizer_calls: list[str] = []
    monkeypatch.setattr(
        window,
        '_show_progress',
        lambda message, *_args, **_kwargs: progress_calls.append(message),
    )
    monkeypatch.setattr(
        window,
        '_start_organizer_request',
        lambda _request: organizer_calls.append('organize'),
    )
    photo = window.library.get_photo('IMG_9260')
    previous_sort_mode = window.library.sort_mode
    previous_recursive = window.library.load_recursively

    window._set_main_view_frozen_after_move_organize(frozen=True)
    window.rating_actions[5].trigger()
    window.color_label_actions['purple'].trigger()
    window.flag_actions['picked'].trigger()
    window._assignment_shortcuts[0].activated.emit()
    window._apply_photo_filter(
        PhotoFilterSelection(allowed_flags=frozenset({'picked'}))
    )
    window._set_photo_sort_mode(PHOTO_SORT_MODE_CAPTURE_TIME, persist=True)
    window._set_photo_load_recursively(not previous_recursive, persist=True)
    window.detect_scenes()
    window.open_organizer_dialog()
    window._enter_browse_mode()
    window._enter_compare_mode()
    window.thumbnail_list.setCurrentRow(1)
    app.processEvents()

    assert photo.rating is None
    assert photo.color_label is None
    assert photo.flag is None
    assert window._photo_filter_selection == PhotoFilterSelection.default()
    assert window.library.sort_mode == previous_sort_mode
    assert window.library.load_recursively is previous_recursive
    assert progress_calls == []
    assert organizer_calls == []
    assert window._browse_mode is False
    assert window._compare_mode is False
    assert window.current_photo_id == 'IMG_9260'

    window.close()
    del app


def test_main_window_move_frozen_state_blocks_shortcut_help(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify frozen workspaces do not open shortcut help.

    The post-move overlay is the recovery explanation for stale source paths.
    Opening shortcut help above it would advertise Esc dismissal while frozen
    shortcuts are disabled, so the help action must wait for recovery.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9266', 'dimgray')],
    )
    window._set_main_view_frozen_after_move_organize(frozen=True)

    window.shortcut_help_action.trigger()
    app.processEvents()

    assert window.shortcut_help_overlay.isHidden() is True
    assert window.move_organize_frozen_overlay.isVisible() is True

    window.close()
    del app


def test_main_window_move_frozen_state_blocks_scene_edits(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify frozen workspaces block direct scene mutation helpers.

    Scene edit helpers can be called by actions, context menus, and tests. They
    need their own frozen-state guard so future entry points cannot edit saved
    scene metadata while loaded photo records may point at moved paths.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_9262', 'dimgray'),
            ('IMG_9263', 'navy'),
            ('IMG_9264', 'green'),
            ('IMG_9265', 'white'),
        ],
        scene_groups=[
            ['IMG_9262', 'IMG_9263'],
            ['IMG_9264'],
            ['IMG_9265'],
        ],
    )
    _select_list_rows(window.thumbnail_list, [1, 2])
    original_groups = window.library.scene_group_photo_ids()
    confirmation_calls: list[str] = []
    save_calls: list[str] = []
    monkeypatch.setattr(
        window,
        '_confirm_break_scene',
        lambda: confirmation_calls.append('break') or True,
    )
    monkeypatch.setattr(
        window.library,
        'save_metadata',
        lambda: save_calls.append('save'),
    )

    window._set_main_view_frozen_after_move_organize(frozen=True)
    window._break_scene_into_singletons(window.library.scenes[0].scene_id)
    window._merge_selected_photos_into_scene()
    app.processEvents()

    assert window.library.scene_group_photo_ids() == original_groups
    assert confirmation_calls == []
    assert save_calls == []
    assert window._metadata_undo_stack == []

    window.close()
    del app


def test_main_window_open_folder_success_clears_move_frozen_state(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify a successful folder open unfreezes the post-move workspace.

    Open Folder is the intentional recovery path from moved source files, so it
    must remain available while frozen and restore normal controls after load.
    """
    initial_folder = tmp_path / 'initial'
    next_folder = tmp_path / 'next'
    initial_folder.mkdir()
    next_folder.mkdir()
    create_jpeg(initial_folder / 'IMG_9270.JPG', 'dimgray')
    create_jpeg(next_folder / 'IMG_9271.JPG', 'navy')
    _, app, window = create_main_window_with_library(
        initial_folder,
        monkeypatch,
        photo_specs=[],
    )
    monkeypatch.setattr(
        QFileDialog,
        'getExistingDirectory',
        lambda *_args, **_kwargs: str(next_folder),
    )
    window._set_main_view_frozen_after_move_organize(frozen=True)

    window.choose_folder()

    assert window._main_view_frozen_after_move_organize is False
    assert window.move_organize_frozen_overlay.isHidden() is True
    assert window.library.current_folder == next_folder
    assert window.current_photo_id == 'IMG_9271'
    assert window.thumbnail_list.isEnabled() is True
    assert window.organize_button.isEnabled() is True

    window.close()
    del app


def test_main_window_open_folder_cancel_keeps_move_frozen_state(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify cancelling Open Folder leaves the workspace frozen.

    A cancelled picker does not replace stale moved-file records, so the UI
    must keep blocking navigation and tagging after the dialog closes.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9272', 'dimgray')],
    )
    monkeypatch.setattr(
        QFileDialog,
        'getExistingDirectory',
        lambda *_args, **_kwargs: '',
    )
    window._set_main_view_frozen_after_move_organize(frozen=True)

    window.choose_folder()

    assert window._main_view_frozen_after_move_organize is True
    assert window.move_organize_frozen_overlay.isVisible() is True
    assert window.thumbnail_list.isEnabled() is False
    assert window.open_button.isEnabled() is True

    window.close()
    del app


def test_main_window_open_folder_failure_keeps_move_frozen_state(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify a failed folder open leaves the workspace frozen.

    Failed recovery still leaves the old moved-file records loaded, so controls
    must stay blocked even after the error dialog restores normal busy state.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9273', 'dimgray')],
    )
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QFileDialog,
        'getExistingDirectory',
        lambda *_args, **_kwargs: str(tmp_path),
    )
    monkeypatch.setattr(
        window.library,
        'load_folder',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('boom')),
    )
    monkeypatch.setattr(
        QMessageBox,
        'critical',
        lambda _parent, title, text: errors.append((title, text)),
    )
    window._set_main_view_frozen_after_move_organize(frozen=True)

    window.choose_folder()

    assert errors == [('Failed to Open Folder', 'boom')]
    assert window._main_view_frozen_after_move_organize is True
    assert window.move_organize_frozen_overlay.isVisible() is True
    assert window.thumbnail_list.isEnabled() is False
    assert window.open_button.isEnabled() is True

    window.close()
    del app


def test_main_window_xmp_operation_finished_shows_dialog_without_reload(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify XMP completion skips reload and keeps the workspace interactive.

    XMP writes update sidecars rather than photo paths, so this protects the
    move-only freeze boundary from metadata-sidecar workflows.
    """
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
        window.library,
        'load_folder',
        lambda *_args, **_kwargs: reload_calls.append('reload'),
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
    assert window._main_view_frozen_after_move_organize is False
    assert window.move_organize_frozen_overlay.isHidden() is True
    assert window.current_photo_id == 'IMG_9300'
    assert window.organize_button.isEnabled() is True
    assert window.filter_button.isEnabled() is True
    assert window.thumbnail_list.isEnabled() is True
    assert window.viewer.isEnabled() is True
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
        organize_options=FlagOrganizeFilesOptions(
            criterion='flag',
            action='copy',
            output_parent=tmp_path,
            flag_folder_mode='picked_rejected',
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
    """
    Verify successful organizer undo clears the post-move frozen state.

    Undo reloads the folder after restoring moved files, so the old stale path
    risk is gone and the normal workspace controls should be re-enabled.
    """
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
    window._set_main_view_frozen_after_move_organize(frozen=True)
    window._operation_kind = 'undo'
    window._show_progress('Undoing', 50)

    window._handle_operation_finished(None)

    assert reload_calls == ['reload']
    assert window._main_view_frozen_after_move_organize is False
    assert window.move_organize_frozen_overlay.isHidden() is True
    assert window.thumbnail_list.isEnabled() is True
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


def test_main_window_undo_reload_failure_keeps_move_frozen_state(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify undo reload failure preserves the frozen post-move workspace.

    The file operation may have undone, but a failed reload means the visible
    UI may still reference stale records, so controls must remain blocked.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9321', 'dimgray')],
    )
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(
        window,
        '_reload_current_folder_after_undo',
        lambda: (_ for _ in ()).throw(RuntimeError('reload boom')),
    )
    monkeypatch.setattr(
        QMessageBox,
        'critical',
        lambda _parent, title, text: errors.append((title, text)),
    )
    window._set_main_view_frozen_after_move_organize(frozen=True)
    window._operation_kind = 'undo'
    window._show_progress('Undoing', 50)

    window._handle_operation_finished(None)

    assert window._main_view_frozen_after_move_organize is True
    assert window.move_organize_frozen_overlay.isVisible() is True
    assert window.thumbnail_list.isEnabled() is False
    assert all(
        action.isEnabled() is False for action in window._assignment_actions
    )
    assert all(
        shortcut.isEnabled() is False
        for shortcut in window._assignment_shortcuts
    )
    assert window._busy is False
    assert window._operation_kind is None
    assert errors == [
        (
            'Folder Reload Failed',
            (
                'Undo completed, but the folder could not be reloaded:\n'
                'reload boom'
            ),
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
                organize_options=FlagOrganizeFilesOptions(
                    criterion='flag',
                    action='copy',
                    output_parent=Path('/tmp'),
                    flag_folder_mode='picked_rejected',
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
