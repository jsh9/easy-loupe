"""
Behavior tests for main-window navigation and selection workflows.

``easy_cull.ui.main_window.selection`` is intentionally covered here through
the real ``MainWindow`` because selection resolution depends on live Qt list
widgets, scene-strip rebuilding, hidden selections, and shortcut routing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Never

import pytest
from PySide6.QtCore import QEvent, QItemSelectionModel, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import easy_cull.ui.folder_access as folder_access_module
import easy_cull.ui.main_window.build as build_module
import easy_cull.ui.main_window.window as main_window_module
from easy_cull.core.folder_loading import PHOTO_SORT_MODE_FILENAME
from easy_cull.core.photo_library import PhotoLibrary
from tests.ui._helpers import (
    create_jpeg,
    create_main_window_with_library,
    stub_read_exif,
    trigger_scene_shortcut,
)


def _list_widget_has_focus(app: object, list_widget: object) -> bool:
    focus_widget = app.focusWidget()
    return focus_widget in {list_widget, list_widget.viewport()}


def _record_method_calls(window: object, method_name: str) -> list[tuple]:
    calls: list[tuple] = []
    original = getattr(window, method_name)

    def wrapper(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    setattr(window, method_name, wrapper)
    return calls


def _ctrl_click_item(list_widget: object, row: int) -> None:
    item = list_widget.item(row)
    assert item is not None
    item_rect = list_widget.visualItemRect(item)
    QTest.mouseClick(
        list_widget.viewport(),
        Qt.LeftButton,
        Qt.ControlModifier,
        item_rect.center(),
    )


def _collect_photo_ids_from_selected_items(list_widget: object) -> list[str]:
    """Return selected photo IDs in visible row order for assertions."""
    return [
        str(item.data(Qt.UserRole))
        for item in sorted(list_widget.selectedItems(), key=list_widget.row)
    ]


def _select_rows_preserving_current(
        list_widget: object,
        rows: list[int],
) -> None:
    """
    Select rows while keeping the last row as Qt's current navigation row.
    """
    list_widget.clearSelection()
    for row in rows:
        item = list_widget.item(row)
        assert item is not None
        item.setSelected(True)

    current_item = list_widget.item(rows[-1])
    assert current_item is not None
    list_widget.selectionModel().setCurrentIndex(
        list_widget.indexFromItem(current_item),
        QItemSelectionModel.SelectionFlag.NoUpdate,
    )


def _create_sort_navigation_window(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> tuple[object, object, object]:
    """
    Build a shown scene-mode window with sort orders that differ visibly.

    The sticky-selection regression needs real Qt focus and selection state, so
    these tests use a displayed ``MainWindow`` rather than a fake object.
    """
    for photo_id, color in [
        ('IMG_2402', 'blue'),
        ('IMG_2400', 'green'),
        ('IMG_2403', 'purple'),
        ('IMG_2401', 'red'),
    ]:
        create_jpeg(tmp_path / f'{photo_id}.JPG', color)

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
        [['IMG_2402'], ['IMG_2400'], ['IMG_2403'], ['IMG_2401']],
        scene_source='manual',
    )

    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.library = library
    window.current_photo_id = 'IMG_2400'
    window._populate_thumbnail_list()
    window._populate_browse_list()
    window._populate_scene_list()
    window._display_current_photo()
    window._refresh_ui()
    window.show()
    app.processEvents()
    return app, library, window


def test_main_window_uses_viewer_preview_for_central_image() -> None:
    """
    Request the cached viewer-sized preview for the main image display.

    This protects the contract that central-photo rendering uses the viewer
    pipeline rather than thumbnail or full-size preview kinds.
    """

    class FakeLibrary:
        def __init__(self) -> None:
            self.preview_requests: list[tuple[str, str]] = []

        @staticmethod
        def get_photo(photo_id: str) -> object:
            return type(
                'Photo',
                (),
                {'photo_id': photo_id, 'focus_point': (0.25, 0.75)},
            )()

        def get_preview_path(self, photo_id: str, kind: str) -> Path:
            self.preview_requests.append((photo_id, kind))
            return Path('/tmp/fake-preview.jpg')

    class FakeViewer:
        @staticmethod
        def should_preserve_zoom() -> bool:
            return False

        @staticmethod
        def normalized_viewport_center() -> Never:
            raise AssertionError(
                'normalized_viewport_center should not be called when zoom is not preserved'
            )

        def set_photo(
                self,
                image_path: Path,
                focus_point: tuple[float, float],
                *,
                focus_point_pending: bool,
                preserve_zoom: bool,
                preserved_center: tuple[float, float] | None,
        ) -> None:
            self.image_path = image_path
            self.focus_point = focus_point
            self.focus_point_pending = focus_point_pending
            self.preserve_zoom = preserve_zoom
            self.preserved_center = preserved_center

        @staticmethod
        def clear_photo() -> Never:
            raise AssertionError(
                'clear_photo should not be called when a photo is selected'
            )

    fake_window = type(
        'FakeWindow',
        (),
        {
            'current_photo_id': 'IMG_7000',
            'library': FakeLibrary(),
            'viewer': FakeViewer(),
        },
    )()

    main_window_module.MainWindow._display_current_photo(fake_window)

    assert fake_window.library.preview_requests == [('IMG_7000', 'viewer')]
    assert fake_window.viewer.image_path == Path('/tmp/fake-preview.jpg')
    assert fake_window.viewer.focus_point == (0.25, 0.75)
    assert fake_window.viewer.focus_point_pending is False
    assert fake_window.viewer.preserve_zoom is False
    assert fake_window.viewer.preserved_center is None


def test_main_window_browse_mode_toggles_grid_and_space_behavior(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Toggle browse mode with shortcuts and preserve ``Space`` semantics.

    This keeps browse-mode entry and exit behavior stable while ensuring
    ``Space`` still controls focus zoom only outside browse mode.
    """
    _desktop_app, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8000', 'dimgray'), ('IMG_8001', 'blue')],
    )

    focus_zoom_calls: list[str] = []
    window.viewer.toggle_focus_zoom = lambda: focus_zoom_calls.append('toggle')

    assert window._browse_mode is False
    assert window.content_splitter.isVisible() is True
    assert window.browse_list.isVisible() is False

    window.space_shortcut.activated.emit()
    app.processEvents()

    assert focus_zoom_calls == ['toggle']

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._browse_mode is True
    assert window.browse_list.isVisible() is True
    assert window.content_splitter.isVisible() is False
    assert window.scene_list.isVisible() is False
    assert window.split_mode_shortcut.isEnabled() is False

    window.space_shortcut.activated.emit()
    app.processEvents()

    assert focus_zoom_calls == ['toggle']
    assert window._browse_mode is False
    assert window.browse_list.isVisible() is False
    assert window.content_splitter.isVisible() is True
    assert window.split_mode_shortcut.isEnabled() is True

    window.close()


def test_main_window_system_open_enters_photo_viewer_and_browse_grid(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Open a file into photo-viewer mode and transition into browse mode.

    The title assertions protect the viewer-only native title state, which must
    follow arrow navigation and reset when the user enters the grid.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    create_jpeg(tmp_path / 'C.JPG', 'purple')
    stub_read_exif(monkeypatch, {})
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.show()
    monkeypatch.setattr(
        window.folder_access_manager,
        'ensure_access_for_file',
        lambda _path, _parent: True,
    )
    monkeypatch.setattr(window, '_start_viewer_prefetch', lambda: None)
    monkeypatch.setattr(
        window, '_start_folder_hydration', lambda _folder: None
    )

    window.open_file_from_system(tmp_path / 'B.JPG')
    app.processEvents()

    assert window._photo_viewer_mode is True
    assert window.current_photo_id == 'B'
    assert window.windowTitle() == 'EasyCull - B.JPG (2 / 3)'
    assert window.top_bar_widget.isHidden() is True
    assert window.thumbnail_list.isHidden() is True
    assert window.browse_list.isHidden() is True
    assert window.viewer.single_viewer._mode == 'fit'

    window._navigate_photo_viewer(1)
    assert window.current_photo_id == 'C'
    assert window.windowTitle() == 'EasyCull - C.JPG (3 / 3)'
    window._navigate_photo_viewer(-1)
    assert window.current_photo_id == 'B'
    assert window.windowTitle() == 'EasyCull - B.JPG (2 / 3)'

    window._handle_browse_mode_shortcut()

    assert window._photo_viewer_mode is False
    assert window._browse_mode is True
    assert window.windowTitle() == 'EasyCull'
    assert window.browse_list.isVisible() is True
    assert window.browse_list.currentRow() == window._browse_photo_rows['B']
    window.close()


def test_main_window_photo_viewer_title_prefers_opened_file_extension(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Prefer the opened file suffix when rendering the viewer title.

    This guards grouped JPEG+RAW records, where the preview source may be a
    JPEG but the title should still reflect that the user opened the RAW file.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    (tmp_path / 'B.CR3').write_bytes(b'raw')
    create_jpeg(tmp_path / 'C.JPG', 'purple')
    stub_read_exif(monkeypatch, {})
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.show()
    monkeypatch.setattr(
        window.folder_access_manager,
        'ensure_access_for_file',
        lambda _path, _parent: True,
    )
    monkeypatch.setattr(window, '_start_viewer_prefetch', lambda: None)
    monkeypatch.setattr(
        window, '_start_folder_hydration', lambda _folder: None
    )

    window.open_file_from_system(tmp_path / 'B.CR3')
    app.processEvents()

    assert window.current_photo_id == 'B'
    assert window.windowTitle() == 'EasyCull - B.CR3 (2 / 3)'

    window._navigate_photo_viewer(1)

    assert window.current_photo_id == 'C'
    assert window.windowTitle() == 'EasyCull - C.JPG (3 / 3)'
    window.close()


def test_main_window_photo_viewer_exif_result_updates_focus_point(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Apply a current-photo EXIF result without blocking first display.

    Photo-viewer startup intentionally shows the image before EXIF is ready, so
    this verifies the later result updates both the record and the active
    viewer focus target while the AF marker checkbox remains presentation-only.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2000, 1500))
    stub_read_exif(monkeypatch, {})
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.resize(1000, 720)
    window.show()
    monkeypatch.setattr(
        window.folder_access_manager,
        'ensure_access_for_file',
        lambda _path, _parent: True,
    )
    monkeypatch.setattr(
        window, '_start_photo_viewer_exif_refresh', lambda: None
    )
    monkeypatch.setattr(window, '_start_viewer_prefetch', lambda: None)
    monkeypatch.setattr(
        window, '_start_folder_hydration', lambda _folder: None
    )

    window.open_file_from_system(tmp_path / 'A.JPG')
    app.processEvents()

    photo = window.library.get_photo('A')
    assert photo.focus_point == (0.5, 0.5)
    assert photo.focus_point_pending is True
    assert window.viewer._current_focus_point == (0.5, 0.5)
    assert window.viewer.single_viewer._focus_point_pending is True
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is False

    window.space_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer.single_viewer.normalized_viewport_center() == (
        pytest.approx(0.5),
        pytest.approx(0.5),
    )
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is False

    window.viewer.set_fit_view()
    window._photo_viewer_exif_request_id = 12
    window._handle_photo_viewer_exif_finished(12, 'A', (0.4, 0.6))
    window.space_shortcut.activated.emit()
    app.processEvents()

    assert photo.focus_point == (0.4, 0.6)
    assert photo.focus_point_pending is False
    assert window.viewer._current_focus_point == (0.4, 0.6)
    assert window.viewer.single_viewer._focus_point_pending is False
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is True
    assert window.viewer.single_viewer.normalized_viewport_center() == (
        pytest.approx(0.4),
        pytest.approx(0.6),
    )
    window.close()


def test_main_window_photo_viewer_ignores_stale_exif_result(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Ignore late EXIF results from superseded photo-viewer requests.

    The active photo can change while ExifTool is still running; applying a
    stale result would move the visible marker or focus zoom to the wrong
    photo's autofocus point.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    stub_read_exif(monkeypatch, {})
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.show()
    monkeypatch.setattr(
        window.folder_access_manager,
        'ensure_access_for_file',
        lambda _path, _parent: True,
    )
    monkeypatch.setattr(
        window, '_start_photo_viewer_exif_refresh', lambda: None
    )
    monkeypatch.setattr(window, '_start_viewer_prefetch', lambda: None)
    monkeypatch.setattr(
        window, '_start_folder_hydration', lambda _folder: None
    )

    window.open_file_from_system(tmp_path / 'A.JPG')
    app.processEvents()
    window.current_photo_id = 'B'
    window._display_current_photo(force_fit=True)
    window._photo_viewer_exif_request_id = 2

    window._handle_photo_viewer_exif_finished(1, 'A', (0.2, 0.3))

    assert window.library.get_photo('A').focus_point == (0.5, 0.5)
    assert window.library.get_photo('A').focus_point_pending is True
    assert window.library.get_photo('B').focus_point == (0.5, 0.5)
    assert window.library.get_photo('B').focus_point_pending is True
    assert window.viewer._current_focus_point == (0.5, 0.5)
    assert window.viewer.single_viewer._focus_point_pending is True
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is False
    window.close()


def test_main_window_photo_viewer_minimap_tracks_manual_zoom(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Show a floating minimap only while photo-viewer mode is zoomed.

    Photo-viewer mode hides the normal thumbnail strip, so this regression test
    verifies the replacement overlay tracks zoom/pan state and clears when the
    viewer returns to fit or leaves photo-viewer mode.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2000, 1500))
    stub_read_exif(monkeypatch, {})
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.resize(1000, 720)
    window.show()
    monkeypatch.setattr(
        window.folder_access_manager,
        'ensure_access_for_file',
        lambda _path, _parent: True,
    )
    monkeypatch.setattr(window, '_start_viewer_prefetch', lambda: None)
    monkeypatch.setattr(
        window, '_start_folder_hydration', lambda _folder: None
    )

    window.open_file_from_system(tmp_path / 'A.JPG')
    app.processEvents()

    assert window._photo_viewer_mode is True
    assert window.photo_viewer_minimap.isHidden() is True
    assert window.photo_viewer_minimap.visible_region_overlay() is None

    window.space_shortcut.activated.emit()
    app.processEvents()

    zoom_overlay = window.photo_viewer_minimap.visible_region_overlay()

    assert window.photo_viewer_minimap.isVisible() is True
    assert zoom_overlay is not None
    assert zoom_overlay == pytest.approx(window.viewer.visible_region_rect())

    window.viewer.pan_by(80, -40)
    app.processEvents()

    pan_overlay = window.photo_viewer_minimap.visible_region_overlay()

    assert pan_overlay is not None
    assert pan_overlay != pytest.approx(zoom_overlay)
    assert pan_overlay == pytest.approx(window.viewer.visible_region_rect())

    window.space_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer.visible_region_rect() is None
    assert window.photo_viewer_minimap.isHidden() is True
    assert window.photo_viewer_minimap.visible_region_overlay() is None

    window.space_shortcut.activated.emit()
    app.processEvents()
    assert window.photo_viewer_minimap.isVisible() is True

    window._handle_browse_mode_shortcut()
    app.processEvents()

    assert window._photo_viewer_mode is False
    assert window.photo_viewer_minimap.isHidden() is True
    assert window.photo_viewer_minimap.visible_region_overlay() is None
    window.close()


def test_main_window_late_file_open_cancels_initial_folder_prompt(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'A.JPG', 'green')
    stub_read_exif(monkeypatch, {})
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    choose_calls: list[str] = []
    window.choose_folder = lambda: choose_calls.append('choose')
    monkeypatch.setattr(build_module.sys, 'platform', 'darwin')
    monkeypatch.setattr(
        window.folder_access_manager,
        'ensure_access_for_file',
        lambda _path, _parent: True,
    )
    monkeypatch.setattr(window, '_start_viewer_prefetch', lambda: None)
    monkeypatch.setattr(
        window, '_start_folder_hydration', lambda _folder: None
    )

    window.show()
    app.processEvents()
    assert window._initial_folder_prompt_timer.isActive() is True

    window.open_file_from_system(tmp_path / 'A.JPG')
    QTest.qWait(build_module.INITIAL_FOLDER_PROMPT_GRACE_MS + 20)
    app.processEvents()

    assert choose_calls == []
    assert window._photo_viewer_mode is True
    assert window.current_photo_id == 'A'
    window.close()


def test_main_window_canceled_photo_viewer_access_opens_single_photo_only(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Denied folder access keeps photo-viewer mode scoped to the opened file.

    The title should count the single loaded record, matching disabled adjacent
    navigation and blocked browse-grid entry.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    stub_read_exif(monkeypatch, {})
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.show()
    monkeypatch.setattr(
        window.folder_access_manager,
        'ensure_access_for_file',
        lambda _path, _parent: False,
    )
    monkeypatch.setattr(window, '_start_viewer_prefetch', lambda: None)
    monkeypatch.setattr(
        window, '_start_folder_hydration', lambda _folder: None
    )

    window.open_file_from_system(tmp_path / 'B.JPG')
    app.processEvents()

    assert window._photo_viewer_mode is True
    assert window._photo_viewer_folder_access_granted is False
    assert [photo.photo_id for photo in window.library.photos] == ['B']
    assert window.windowTitle() == 'EasyCull - B.JPG (1 / 1)'

    window._navigate_photo_viewer(-1)
    assert window.current_photo_id == 'B'

    window._handle_browse_mode_shortcut()
    assert window._browse_mode is False
    window.close()


def test_main_window_photo_viewer_hydration_keeps_scene_strip_hidden(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Keep culling chrome hidden when background hydration loads scenes.

    Existing ``easy-cull.json`` scene groups can arrive after photo-viewer
    startup; they should be ready for culling mode without revealing the
    horizontal scene strip before the user presses ``G`` or ``Enter``.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    stub_read_exif(monkeypatch, {})
    hydrated_library = PhotoLibrary(cache_dir=tmp_path / '.hydrated-cache')
    hydrated_library.load_folder(tmp_path)
    hydrated_library.set_scene_group_photo_ids(
        [['A', 'B']], scene_source='manual'
    )
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.show()
    monkeypatch.setattr(
        window.folder_access_manager,
        'ensure_access_for_file',
        lambda _path, _parent: True,
    )
    monkeypatch.setattr(
        window, '_start_photo_viewer_exif_refresh', lambda: None
    )
    monkeypatch.setattr(window, '_start_viewer_prefetch', lambda: None)
    monkeypatch.setattr(
        window, '_start_folder_hydration', lambda _folder: None
    )

    window.open_file_from_system(tmp_path / 'A.JPG')
    app.processEvents()
    window._handle_folder_hydration_finished(hydrated_library)
    app.processEvents()

    assert window._photo_viewer_mode is True
    assert window.top_bar_widget.isHidden() is True
    assert window.thumbnail_list.isHidden() is True
    assert window.browse_list.isHidden() is True
    assert window.scene_list.isHidden() is True
    assert window.library.scene_detection_done is True
    assert window.library.get_photo('A').focus_point_pending is False
    assert window.viewer.single_viewer._focus_point_pending is False
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is True

    window._handle_browse_mode_shortcut()
    app.processEvents()

    assert window._photo_viewer_mode is False
    assert window._browse_mode is True
    assert window.browse_list.isVisible() is True
    assert window.browse_list.currentRow() == window._browse_photo_rows['A']
    window.close()


def test_main_window_denied_cloud_storage_access_opens_single_photo_only(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Keep denied CloudStorage access in selected-photo-only viewer mode.

    This verifies the File Provider prompt path has the same safe fallback as
    Desktop/Documents/Downloads when macOS does not grant folder scanning.
    """
    home = tmp_path / 'home'
    root = home / 'Library' / 'CloudStorage' / 'Dropbox'
    (root / 'Shoot').mkdir(parents=True)
    create_jpeg(root / 'Shoot' / 'A.JPG', 'green')
    create_jpeg(root / 'Shoot' / 'B.JPG', 'blue')
    stub_read_exif(monkeypatch, {})
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.show()
    monkeypatch.setattr(folder_access_module.sys, 'platform', 'darwin')
    monkeypatch.setattr(folder_access_module.Path, 'home', lambda: home)
    monkeypatch.setattr(
        window.folder_access_manager,
        '_confirm_access_root',
        lambda _parent, path: path == root,
    )
    monkeypatch.setattr(
        window.folder_access_manager,
        '_probe_folder_access',
        lambda _path: False,
    )
    monkeypatch.setattr(window, '_start_viewer_prefetch', lambda: None)
    monkeypatch.setattr(
        window, '_start_folder_hydration', lambda _folder: None
    )

    window.open_file_from_system(root / 'Shoot' / 'B.JPG')
    app.processEvents()

    assert window._photo_viewer_mode is True
    assert window._photo_viewer_folder_access_granted is False
    assert [photo.photo_id for photo in window.library.photos] == ['B']
    assert window.windowTitle() == 'EasyCull - B.JPG (1 / 1)'
    window.close()


def test_main_window_cloud_storage_retry_uses_macos_permission_prompt(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Show the macOS-permission retry path for CloudStorage roots.

    The retry dialog should not steer File Provider folders back to the native
    folder chooser wording because the first recovery attempt is another OS
    permission probe.
    """
    root = tmp_path / 'home' / 'Library' / 'CloudStorage' / 'OneDrive'
    photo = root / 'Shoot' / 'IMG_1000.JPG'
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b'jpg')
    captured: dict[str, object] = {}
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    monkeypatch.setattr(
        window.folder_access_manager,
        'suggest_access_root',
        lambda _file_path: root,
    )
    monkeypatch.setattr(
        window.folder_access_manager,
        'is_macos_promptable_root',
        lambda path: path == root,
    )
    monkeypatch.setattr(
        window.folder_access_manager,
        'request_access_for_file',
        lambda _file_path, _parent: True,
    )

    def fake_exec(message_box: QMessageBox) -> int:
        captured['informative_text'] = message_box.informativeText()
        captured['buttons'] = [
            button.text().replace('&', '') for button in message_box.buttons()
        ]
        message_box._clicked_button = next(
            button
            for button in message_box.buttons()
            if button.text().replace('&', '') == 'Try macOS Permission Again'
        )
        return 0

    monkeypatch.setattr(QMessageBox, 'exec', fake_exec)
    monkeypatch.setattr(
        QMessageBox,
        'clickedButton',
        lambda message_box: getattr(message_box, '_clicked_button', None),
    )

    assert window._retry_photo_viewer_folder_access(photo) is True

    assert 'again' in str(captured['informative_text'])
    assert 'Try macOS Permission Again' in captured['buttons']
    assert 'Choose Folder' not in captured['buttons']
    window.close()


def test_main_window_permission_error_regrant_reloads_full_folder(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    stub_read_exif(monkeypatch, {})
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.show()
    load_calls: list[bool] = []
    original_load_viewer_folder = window.library.load_viewer_folder

    def load_viewer_folder(path: Path, *, allow_folder_scan: bool) -> None:
        load_calls.append(allow_folder_scan)
        if len(load_calls) == 1:
            raise PermissionError('blocked')

        original_load_viewer_folder(path, allow_folder_scan=allow_folder_scan)

    window.library.load_viewer_folder = load_viewer_folder
    monkeypatch.setattr(
        window.folder_access_manager,
        'ensure_access_for_file',
        lambda _path, _parent: True,
    )
    monkeypatch.setattr(
        window,
        '_retry_photo_viewer_folder_access',
        lambda _path: True,
    )
    monkeypatch.setattr(window, '_start_viewer_prefetch', lambda: None)
    monkeypatch.setattr(
        window, '_start_folder_hydration', lambda _folder: None
    )

    window.open_file_from_system(tmp_path / 'B.JPG')
    app.processEvents()

    assert load_calls == [True, True]
    assert window._photo_viewer_folder_access_granted is True
    assert [photo.photo_id for photo in window.library.photos] == ['A', 'B']
    window.close()


def test_main_window_permission_error_cancel_regrant_opens_selected_photo_only(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    stub_read_exif(monkeypatch, {})
    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.show()
    load_calls: list[bool] = []
    original_load_viewer_folder = window.library.load_viewer_folder

    def load_viewer_folder(path: Path, *, allow_folder_scan: bool) -> None:
        load_calls.append(allow_folder_scan)
        if len(load_calls) == 1:
            raise PermissionError('blocked')

        original_load_viewer_folder(path, allow_folder_scan=allow_folder_scan)

    window.library.load_viewer_folder = load_viewer_folder
    monkeypatch.setattr(
        window.folder_access_manager,
        'ensure_access_for_file',
        lambda _path, _parent: True,
    )
    monkeypatch.setattr(
        window,
        '_retry_photo_viewer_folder_access',
        lambda _path: False,
    )
    monkeypatch.setattr(window, '_start_viewer_prefetch', lambda: None)
    monkeypatch.setattr(
        window, '_start_folder_hydration', lambda _folder: None
    )

    window.open_file_from_system(tmp_path / 'B.JPG')
    app.processEvents()

    assert load_calls == [True, False]
    assert window._photo_viewer_folder_access_granted is False
    assert [photo.photo_id for photo in window.library.photos] == ['B']
    window.close()


def test_main_window_stops_photo_viewer_background_threads() -> None:
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    calls: list[str] = []

    class Worker:
        @staticmethod
        def cancel() -> None:
            calls.append('cancel')

    class Thread:
        @staticmethod
        def quit() -> None:
            calls.append('quit')

        @staticmethod
        def isRunning() -> bool:  # noqa: N802 - Qt naming in fake
            return True

        @staticmethod
        def wait() -> None:
            calls.append('wait')

    window._viewer_prefetch_worker = Worker()
    window._viewer_prefetch_thread = Thread()
    window._folder_hydration_worker = Worker()
    window._folder_hydration_thread = Thread()
    window._photo_viewer_exif_worker = Worker()
    window._photo_viewer_exif_thread = Thread()
    window._pending_browse_after_hydration = True

    window._stop_photo_viewer_background_tasks()

    assert calls == [
        'cancel',
        'quit',
        'wait',
        'cancel',
        'quit',
        'wait',
        'cancel',
        'quit',
        'wait',
    ]
    assert window._photo_viewer_exif_worker is None
    assert window._photo_viewer_exif_thread is None
    assert window._viewer_prefetch_worker is None
    assert window._viewer_prefetch_thread is None
    assert window._folder_hydration_worker is None
    assert window._folder_hydration_thread is None
    assert window._pending_browse_after_hydration is False
    window.close()


def test_main_window_photo_viewer_browse_waits_for_hydration(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _theme, _app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('A', 'green'), ('B', 'blue')],
    )
    window._set_photo_viewer_mode(active=True)
    window._photo_viewer_folder_access_granted = True
    window._folder_hydration_thread = object()
    window._folder_hydration_message = 'Loading folder...'
    window._folder_hydration_progress = 42

    window._handle_browse_mode_shortcut()

    assert window._pending_browse_after_hydration is True
    assert window._busy is True
    assert window.overlay_message_label.text() == 'Loading folder...'
    window._folder_hydration_thread = None
    window._hide_progress()
    assert window._browse_mode is False


def test_main_window_browse_mode_keeps_photo_selection_and_shows_all_photos(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Keep exact photo selection while browse mode shows every photo card.

    This covers the core browse-mode contract when scene stacks are active: the
    grid shows individual photos while hidden strip selections stay in sync.
    """
    theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8100', 'dimgray'),
            ('IMG_8101', 'green'),
            ('IMG_8102', 'blue'),
        ],
        scene_groups=[['IMG_8100', 'IMG_8101'], ['IMG_8102']],
    )

    assert window.thumbnail_list.count() == 2
    assert window.browse_list.count() == 3
    assert window.scene_list.count() == 2
    assert window.current_photo_id == 'IMG_8100'

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._browse_mode is True
    assert (
        window.browse_list.currentItem().data(theme_module.PHOTO_ID_ROLE)
        == 'IMG_8100'
    )

    window.browse_list.setCurrentRow(1)
    app.processEvents()

    assert window.current_photo_id == 'IMG_8101'
    assert (
        window.thumbnail_list.currentItem().data(theme_module.PHOTO_ID_ROLE)
        == 'IMG_8100'
    )
    assert (
        window.scene_list.currentItem().data(theme_module.PHOTO_ID_ROLE)
        == 'IMG_8101'
    )
    assert window.scene_list.isVisible() is False

    window.space_shortcut.activated.emit()
    app.processEvents()

    assert window._browse_mode is False
    assert window.current_photo_id == 'IMG_8101'
    assert (
        window.thumbnail_list.currentItem().data(theme_module.PHOTO_ID_ROLE)
        == 'IMG_8100'
    )
    assert (
        window.scene_list.currentItem().data(theme_module.PHOTO_ID_ROLE)
        == 'IMG_8101'
    )
    assert window.scene_list.isVisible() is True

    window.close()


@pytest.mark.parametrize(
    (
        'target_row',
        'expected_current_photo_id',
        'expected_left_photo_id',
        'expected_scene_photo_id',
        'expected_scene_populate_calls',
    ),
    [
        pytest.param(
            1,
            'IMG_8111',
            'IMG_8110',
            'IMG_8111',
            0,
            id='within-scene',
        ),
        pytest.param(
            2,
            'IMG_8112',
            'IMG_8112',
            'IMG_8112',
            1,
            id='cross-scene-boundary',
        ),
    ],
)
def test_browse_navigation_updates_hidden_state_with_fast_path(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        target_row: int,
        expected_current_photo_id: str,
        expected_left_photo_id: str,
        expected_scene_photo_id: str,
        expected_scene_populate_calls: int,
) -> None:
    """
    Keep browse navigation lightweight while maintaining hidden state.

    This guards the performance fix directly: browse-row changes must skip
    hidden viewer work and only rebuild the hidden scene strip on scene
    changes.
    """
    theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8110', 'dimgray'),
            ('IMG_8111', 'green'),
            ('IMG_8112', 'blue'),
        ],
        scene_groups=[['IMG_8110', 'IMG_8111'], ['IMG_8112']],
    )
    window.browse_mode_shortcut.activated.emit()
    app.processEvents()

    display_calls = _record_method_calls(window, '_display_current_photo')
    refresh_calls = _record_method_calls(window, '_refresh_ui')
    scene_populate_calls = _record_method_calls(window, '_populate_scene_list')

    window.browse_list.setCurrentRow(target_row)
    app.processEvents()

    assert window.current_photo_id == expected_current_photo_id
    assert len(display_calls) == 0
    assert len(refresh_calls) == 0
    assert len(scene_populate_calls) == expected_scene_populate_calls
    assert (
        window.thumbnail_list.currentItem().data(theme_module.PHOTO_ID_ROLE)
        == expected_left_photo_id
    )
    assert (
        window.scene_list.currentItem().data(theme_module.PHOTO_ID_ROLE)
        == expected_scene_photo_id
    )

    window.close()


def test_main_window_browse_exit_from_split_returns_to_single_fit(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Exit browse mode from split view into a single fit-view layout.

    This prevents browse-mode transitions from accidentally restoring split
    presentation when the product contract requires a fit-view reset.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8180', 'dimgray'), ('IMG_8181', 'green')],
    )

    window.split_mode_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer.is_split_view() is True

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._browse_mode is True
    assert window.content_splitter.isVisible() is False
    assert window.split_mode_shortcut.isEnabled() is False

    window.space_shortcut.activated.emit()
    app.processEvents()

    assert window._browse_mode is False
    assert window.viewer.is_split_view() is False
    assert window.viewer._mode == 'single-fit'
    assert window.split_mode_shortcut.isEnabled() is True

    window.close()


def test_main_mode_navigation_skips_full_refresh_and_full_list_restyle(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Update main-mode selection without triggering full UI refresh passes.

    This protects the shared navigation fast path so moving the left strip does
    not restyle unrelated hidden lists.
    """
    _theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8190', 'dimgray'), ('IMG_8191', 'green')],
    )

    refresh_calls = _record_method_calls(window, '_refresh_ui')
    style_calls = _record_method_calls(window, '_refresh_item_styles')

    window.thumbnail_list.setCurrentRow(1)
    app.processEvents()

    assert window.current_photo_id == 'IMG_8191'
    assert len(refresh_calls) == 0
    assert len(style_calls) == 0

    window.close()


@pytest.mark.parametrize(
    (
        'photo_specs',
        'scene_groups',
        'clicked_row',
        'expected_current_photo_id',
        'expected_left_photo_id',
        'expected_scene_visible',
        'assert_manual_restore',
    ),
    [
        pytest.param(
            [
                ('IMG_8400', 'dimgray'),
                ('IMG_8401', 'green'),
                ('IMG_8402', 'blue'),
            ],
            None,
            2,
            'IMG_8402',
            'IMG_8402',
            False,
            True,
            id='double-click-plain-photo',
        ),
        pytest.param(
            [
                ('IMG_8500', 'dimgray'),
                ('IMG_8501', 'green'),
                ('IMG_8502', 'blue'),
            ],
            [['IMG_8500', 'IMG_8501'], ['IMG_8502']],
            1,
            'IMG_8501',
            'IMG_8500',
            True,
            False,
            id='double-click-scene-photo',
        ),
    ],
)
def test_main_window_browse_mode_double_click_opens_target_photo_in_main_mode(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        photo_specs: list[tuple[str, str]],
        scene_groups: list[list[str]] | None,
        clicked_row: int,
        expected_current_photo_id: str,
        expected_left_photo_id: str,
        expected_scene_visible: bool,
        assert_manual_restore: bool,
) -> None:
    """
    Open the clicked browse-grid photo and restore main-mode presentation.

    This preserves the browse double-click contract for plain photos and
    scene-backed photos, including deferred restoration of remembered manual
    zoom.
    """
    theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=photo_specs,
        scene_groups=scene_groups,
    )

    remembered_scale: float | None = None
    remembered_center: tuple[float, float] | None = None
    if assert_manual_restore:
        window.thumbnail_list.setCurrentRow(2)
        app.processEvents()
        window.viewer.toggle_focus_zoom()
        window.viewer.zoom_step(1.25)
        window.viewer.pan_by(30, -20)
        remembered_scale = window.viewer._current_scale
        remembered_center = window.viewer.normalized_viewport_center()
        window.thumbnail_list.setCurrentRow(0)
        app.processEvents()

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()

    target_item = window.browse_list.item(clicked_row)
    window.browse_list.itemDoubleClicked.emit(target_item)
    app.processEvents()

    assert window._browse_mode is False
    assert window.browse_list.isVisible() is False
    assert window.content_splitter.isVisible() is True
    assert window.scene_list.isVisible() is expected_scene_visible
    assert window.current_photo_id == expected_current_photo_id
    assert (
        window.thumbnail_list.currentItem().data(theme_module.PHOTO_ID_ROLE)
        == expected_left_photo_id
    )
    assert window.viewer._mode == 'single-fit'

    if scene_groups is not None:
        assert (
            window.scene_list.currentItem().data(theme_module.PHOTO_ID_ROLE)
            == expected_current_photo_id
        )

    if assert_manual_restore:
        assert remembered_scale is not None
        assert remembered_center is not None
        window.space_shortcut.activated.emit()
        app.processEvents()

        assert window.viewer._mode == 'single-manual'
        assert window.viewer._current_scale == pytest.approx(remembered_scale)
        assert window.viewer.normalized_viewport_center() == pytest.approx(
            remembered_center
        )

    window.close()


@pytest.mark.parametrize(
    ('scene_groups', 'enter_browse_mode', 'expected_focus_attr'),
    [
        pytest.param(None, False, 'thumbnail_list', id='plain-view'),
        pytest.param(None, True, 'browse_list', id='browse-mode'),
        pytest.param(
            [['IMG_8700', 'IMG_8701']], False, 'scene_list', id='scene-view'
        ),
    ],
)
def test_restore_active_navigation_focus_targets_active_list(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        scene_groups: list[list[str]] | None,
        enter_browse_mode: bool,
        expected_focus_attr: str,
) -> None:
    """
    Restore focus to the list that owns keyboard navigation in each mode.

    This is needed because keyboard-driven browsing depends on focus returning
    to the active list after window activation and similar transitions.
    """
    _theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8700', 'dimgray'), ('IMG_8701', 'blue')],
        scene_groups=scene_groups,
    )
    window.activateWindow()
    window.raise_()
    app.processEvents()
    if not window.isActiveWindow():
        pytest.skip('Window activation is not available in this Qt session')

    if enter_browse_mode:
        window._enter_browse_mode()
        app.processEvents()

    window.open_button.setFocus(Qt.OtherFocusReason)
    app.processEvents()

    def fail_window_activation(*_args: object, **_kwargs: object) -> Never:
        raise AssertionError(
            'navigation focus restore must not activate or raise the window'
        )

    monkeypatch.setattr(window, 'activateWindow', fail_window_activation)
    monkeypatch.setattr(window, 'raise_', fail_window_activation)

    window._restore_active_navigation_focus()
    app.processEvents()

    assert _list_widget_has_focus(app, getattr(window, expected_focus_attr))

    window.close()


def test_restore_active_navigation_focus_ignores_inactive_window(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Ignore stale deferred focus restores after EasyCull loses activation.

    Window activation schedules navigation-focus restoration through a
    zero-delay timer. During an AltTab
    (https://github.com/lwouis/alt-tab-macos) switch away from EasyCull, that
    queued callback can run after another window has already been raised. In
    that case EasyCull must not move focus, select a navigation item, or do
    anything that could help pull its window back to the front.
    """
    _theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8800', 'dimgray'), ('IMG_8801', 'blue')],
    )
    window.activateWindow()
    window.raise_()
    app.processEvents()

    window.open_button.setFocus(Qt.OtherFocusReason)
    window.thumbnail_list.setCurrentRow(-1)
    app.processEvents()

    monkeypatch.setattr(window, 'isActiveWindow', lambda: False)

    window._restore_active_navigation_focus()
    app.processEvents()

    assert app.focusWidget() is window.open_button
    assert window.thumbnail_list.currentRow() == -1

    window.close()


@pytest.mark.parametrize(
    'shortcut_name',
    [
        pytest.param('Right', id='right'),
        pytest.param('Left', id='left'),
    ],
)
def test_scene_navigation_does_nothing_when_no_scenes_detected(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        shortcut_name: str,
) -> None:
    """
    Ignore each scene navigation shortcut until scene detection is available.

    This prevents left/right arrow handling from mutating selection before the
    scene-strip workflow is active.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9100', 'dimgray'), ('IMG_9101', 'blue')],
    )

    assert window.library.scene_detection_done is False

    trigger_scene_shortcut(window, shortcut_name)
    app.processEvents()

    assert window.current_photo_id == 'IMG_9100'

    window.close()


def test_main_window_scene_navigation_shortcuts_move_within_current_scene(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Move within the current scene and stop at scene boundaries.

    This protects the scene-strip keyboard contract so left/right arrows
    navigate within a scene without leaking into global navigation.
    """
    theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7600', 'dimgray'),
            ('IMG_7601', 'green'),
            ('IMG_7602', 'blue'),
        ],
        scene_groups=[['IMG_7600', 'IMG_7601'], ['IMG_7602']],
    )

    trigger_scene_shortcut(window, 'Right')
    app.processEvents()

    assert window.current_photo_id == 'IMG_7601'
    assert (
        window.scene_list.currentItem().data(theme_module.PHOTO_ID_ROLE)
        == 'IMG_7601'
    )

    trigger_scene_shortcut(window, 'Right')
    app.processEvents()

    assert window.current_photo_id == 'IMG_7601'

    trigger_scene_shortcut(window, 'Left')
    app.processEvents()

    assert window.current_photo_id == 'IMG_7600'
    assert (
        window.scene_list.currentItem().data(theme_module.PHOTO_ID_ROLE)
        == 'IMG_7600'
    )

    window.close()


def test_scene_navigation_within_scene_skips_full_refresh_and_rebuild(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Keep same-scene navigation on the fast path without rebuild work.

    This ensures scene-strip selection changes do not trigger full UI refreshes
    or scene-strip repopulation while staying within the active scene.
    """
    theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7620', 'dimgray'),
            ('IMG_7621', 'green'),
            ('IMG_7622', 'blue'),
        ],
        scene_groups=[['IMG_7620', 'IMG_7621'], ['IMG_7622']],
    )

    refresh_calls = _record_method_calls(window, '_refresh_ui')
    style_calls = _record_method_calls(window, '_refresh_item_styles')
    scene_populate_calls = _record_method_calls(window, '_populate_scene_list')

    trigger_scene_shortcut(window, 'Right')
    app.processEvents()

    assert window.current_photo_id == 'IMG_7621'
    assert len(refresh_calls) == 0
    assert len(style_calls) == 0
    assert len(scene_populate_calls) == 0
    assert (
        window.scene_list.currentItem().data(theme_module.PHOTO_ID_ROLE)
        == 'IMG_7621'
    )

    window.close()


def test_scene_list_up_and_down_keys_navigate_global_scene_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Route scene-list up/down keys to global scene-stack navigation.

    This verifies the custom scene-list widget behavior that connects vertical
    key presses to left-strip scene-stack movement.
    """
    theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7610', 'dimgray'),
            ('IMG_7611', 'green'),
            ('IMG_7612', 'blue'),
        ],
        scene_groups=[['IMG_7610', 'IMG_7611'], ['IMG_7612']],
    )
    window.scene_list.setCurrentRow(1)
    app.processEvents()

    down_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
    window.scene_list.keyPressEvent(down_event)
    app.processEvents()

    assert down_event.isAccepted() is True
    assert window.current_photo_id == 'IMG_7612'
    assert (
        window.thumbnail_list.currentItem().data(theme_module.PHOTO_ID_ROLE)
        == 'IMG_7612'
    )

    up_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Up, Qt.NoModifier)
    window.scene_list.keyPressEvent(up_event)
    app.processEvents()

    assert up_event.isAccepted() is True
    assert window.current_photo_id == 'IMG_7610'
    assert (
        window.thumbnail_list.currentItem().data(theme_module.PHOTO_ID_ROLE)
        == 'IMG_7610'
    )

    window.close()


def test_scene_list_down_after_sort_change_clears_restored_multi_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify plain scene-strip navigation unsticks sort-restored selections.

    Sort changes intentionally preserve a multi-selection, but the first plain
    Down key should behave like a fresh navigation action and select only the
    target row.
    """
    app, _library, window = _create_sort_navigation_window(
        tmp_path, monkeypatch
    )
    _select_rows_preserving_current(window.thumbnail_list, [0, 1])

    window.photo_sort_buttons[PHOTO_SORT_MODE_FILENAME].click()
    app.processEvents()

    assert _collect_photo_ids_from_selected_items(window.thumbnail_list) == [
        'IMG_2400',
        'IMG_2402',
    ]

    down_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
    window.scene_list.keyPressEvent(down_event)
    app.processEvents()

    assert down_event.isAccepted() is True
    assert window.current_photo_id == 'IMG_2401'
    assert _collect_photo_ids_from_selected_items(window.thumbnail_list) == [
        'IMG_2401'
    ]
    assert _collect_photo_ids_from_selected_items(window.scene_list) == [
        'IMG_2401'
    ]

    window.close()


def test_scene_list_down_after_reverse_sort_clears_restored_multi_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify plain scene-strip navigation unsticks reverse-sort selections.

    The Reverse checkbox uses the same immediate-selection restoration path as
    sort-mode changes, so its first plain Down key should also collapse to one
    selected row.
    """
    app, _library, window = _create_sort_navigation_window(
        tmp_path, monkeypatch
    )
    _select_rows_preserving_current(window.thumbnail_list, [0, 1])

    window.photo_sort_reverse_checkbox.setChecked(True)
    app.processEvents()

    assert _collect_photo_ids_from_selected_items(window.thumbnail_list) == [
        'IMG_2400',
        'IMG_2402',
    ]

    down_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
    window.scene_list.keyPressEvent(down_event)
    app.processEvents()

    assert down_event.isAccepted() is True
    assert window.current_photo_id == 'IMG_2402'
    assert _collect_photo_ids_from_selected_items(window.thumbnail_list) == [
        'IMG_2402'
    ]
    assert _collect_photo_ids_from_selected_items(window.scene_list) == [
        'IMG_2402'
    ]

    window.close()


def test_scene_list_shift_down_after_sort_change_still_extends_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify the sticky-selection fix preserves intentional Shift extension.

    Only plain up/down should collapse sort-restored selection; holding Shift
    should keep the existing selected photos and add the next scene row.
    """
    app, _library, window = _create_sort_navigation_window(
        tmp_path, monkeypatch
    )
    _select_rows_preserving_current(window.thumbnail_list, [0, 1])

    window.photo_sort_buttons[PHOTO_SORT_MODE_FILENAME].click()
    app.processEvents()

    down_event = QKeyEvent(
        QEvent.KeyPress,
        Qt.Key_Down,
        Qt.ShiftModifier,
    )
    window.scene_list.keyPressEvent(down_event)
    app.processEvents()

    assert down_event.isAccepted() is True
    assert window.current_photo_id == 'IMG_2401'
    assert window._resolved_selection_photo_ids() == [
        'IMG_2400',
        'IMG_2401',
        'IMG_2402',
    ]

    window.close()


def test_scene_list_down_crosses_scene_without_full_refresh(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Cross scene boundaries from the scene list without full refresh work.

    This covers the fast path for global scene navigation, where a scene change
    may repopulate the strip once but should still avoid broad refresh passes.
    """
    theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7630', 'dimgray'),
            ('IMG_7631', 'green'),
            ('IMG_7632', 'blue'),
        ],
        scene_groups=[['IMG_7630', 'IMG_7631'], ['IMG_7632']],
    )
    window.scene_list.setCurrentRow(1)
    app.processEvents()

    refresh_calls = _record_method_calls(window, '_refresh_ui')
    style_calls = _record_method_calls(window, '_refresh_item_styles')
    scene_populate_calls = _record_method_calls(window, '_populate_scene_list')

    down_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
    window.scene_list.keyPressEvent(down_event)
    app.processEvents()

    assert down_event.isAccepted() is True
    assert window.current_photo_id == 'IMG_7632'
    assert len(refresh_calls) == 0
    assert len(style_calls) == 0
    assert len(scene_populate_calls) == 1
    assert (
        window.thumbnail_list.currentItem().data(theme_module.PHOTO_ID_ROLE)
        == 'IMG_7632'
    )

    window.close()


def test_scene_mode_shift_up_down_selects_only_scene_cover_rows(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify vertical range selection keeps scene-stack rows as cover photos.

    The vertical strip represents whole scene groups, but shift-selecting those
    rows is still an exact row selection. This prevents compare and metadata
    actions from unexpectedly expanding a selected scene cover to every photo
    in that group.
    """
    theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7640', 'dimgray'),
            ('IMG_7641', 'green'),
            ('IMG_7642', 'blue'),
        ],
        scene_groups=[['IMG_7640', 'IMG_7641'], ['IMG_7642']],
    )
    window.thumbnail_list.setFocus(Qt.OtherFocusReason)
    window.thumbnail_list.viewport().setFocus(Qt.OtherFocusReason)

    QTest.keyClick(window.thumbnail_list, Qt.Key_Down, Qt.ShiftModifier)
    app.processEvents()

    assert [
        item.data(theme_module.PHOTO_ID_ROLE)
        for item in window.thumbnail_list.selectedItems()
    ] == ['IMG_7640', 'IMG_7642']
    assert window._resolved_selection_photo_ids() == [
        'IMG_7640',
        'IMG_7642',
    ]

    window.close()


def test_thumbnail_shift_down_then_up_releases_rows_below_current(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify downward Shift range selection shrinks when reversing upward.

    Qt's default extended selection can leave rows below the current item
    selected after a direction reversal. The app-owned thumbnail range handler
    should keep only the anchor-to-current rows selected.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7643', 'dimgray'),
            ('IMG_7644', 'green'),
            ('IMG_7645', 'blue'),
            ('IMG_7646', 'yellow'),
        ],
        scene_groups=[
            ['IMG_7643'],
            ['IMG_7644'],
            ['IMG_7645'],
            ['IMG_7646'],
        ],
    )
    window.thumbnail_list.setFocus(Qt.OtherFocusReason)
    window.thumbnail_list.viewport().setFocus(Qt.OtherFocusReason)

    QTest.keyClick(window.thumbnail_list, Qt.Key_Down, Qt.ShiftModifier)
    app.processEvents()
    QTest.keyClick(window.thumbnail_list, Qt.Key_Down, Qt.ShiftModifier)
    app.processEvents()

    assert _collect_photo_ids_from_selected_items(window.thumbnail_list) == [
        'IMG_7643',
        'IMG_7644',
        'IMG_7645',
    ]

    QTest.keyClick(window.thumbnail_list, Qt.Key_Up, Qt.ShiftModifier)
    app.processEvents()

    assert window.current_photo_id == 'IMG_7644'
    assert _collect_photo_ids_from_selected_items(window.thumbnail_list) == [
        'IMG_7643',
        'IMG_7644',
    ]

    window.close()


def test_thumbnail_shift_up_then_down_releases_rows_above_current(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify upward Shift range selection shrinks when reversing downward.

    This is the opposite traversal of the sticky-selection regression. It
    guards the same anchor-to-current contract when the user starts from a
    lower row, extends upward, then moves back down while still holding Shift.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7647', 'dimgray'),
            ('IMG_7648', 'green'),
            ('IMG_7649', 'blue'),
            ('IMG_7650', 'yellow'),
        ],
        scene_groups=[
            ['IMG_7647'],
            ['IMG_7648'],
            ['IMG_7649'],
            ['IMG_7650'],
        ],
    )
    window.thumbnail_list.setCurrentRow(3)
    app.processEvents()
    window.thumbnail_list.setFocus(Qt.OtherFocusReason)
    window.thumbnail_list.viewport().setFocus(Qt.OtherFocusReason)

    QTest.keyClick(window.thumbnail_list, Qt.Key_Up, Qt.ShiftModifier)
    app.processEvents()
    QTest.keyClick(window.thumbnail_list, Qt.Key_Up, Qt.ShiftModifier)
    app.processEvents()

    assert _collect_photo_ids_from_selected_items(window.thumbnail_list) == [
        'IMG_7648',
        'IMG_7649',
        'IMG_7650',
    ]

    QTest.keyClick(window.thumbnail_list, Qt.Key_Down, Qt.ShiftModifier)
    app.processEvents()

    assert window.current_photo_id == 'IMG_7649'
    assert _collect_photo_ids_from_selected_items(window.thumbnail_list) == [
        'IMG_7649',
        'IMG_7650',
    ]

    window.close()


def test_scene_mode_shift_left_right_extends_selection_inside_scene(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify horizontal range selection chooses exact in-scene photos.

    Users select non-cover photos from the scene strip with shift-left/right.
    This keeps that shortcut path distinct from vertical scene-stack selection.
    """
    theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7650', 'dimgray'),
            ('IMG_7651', 'green'),
            ('IMG_7652', 'blue'),
        ],
        scene_groups=[['IMG_7650', 'IMG_7651', 'IMG_7652']],
    )

    trigger_scene_shortcut(window, 'Shift+Right')
    app.processEvents()
    trigger_scene_shortcut(window, 'Shift+Right')
    app.processEvents()

    assert [
        item.data(theme_module.PHOTO_ID_ROLE)
        for item in window.scene_list.selectedItems()
    ] == ['IMG_7650', 'IMG_7651', 'IMG_7652']
    assert window.current_photo_id == 'IMG_7652'
    assert window._resolved_selection_photo_ids() == [
        'IMG_7650',
        'IMG_7651',
        'IMG_7652',
    ]

    window.close()


def test_scene_mode_plain_left_right_clears_prior_shift_range_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7653', 'dimgray'),
            ('IMG_7654', 'green'),
            ('IMG_7655', 'blue'),
            ('IMG_7656', 'yellow'),
        ],
        scene_groups=[['IMG_7653', 'IMG_7654', 'IMG_7655', 'IMG_7656']],
    )

    trigger_scene_shortcut(window, 'Shift+Right')
    app.processEvents()
    trigger_scene_shortcut(window, 'Shift+Right')
    app.processEvents()

    assert [
        item.data(theme_module.PHOTO_ID_ROLE)
        for item in window.scene_list.selectedItems()
    ] == ['IMG_7653', 'IMG_7654', 'IMG_7655']

    trigger_scene_shortcut(window, 'Right')
    app.processEvents()

    assert window.current_photo_id == 'IMG_7656'
    assert [
        item.data(theme_module.PHOTO_ID_ROLE)
        for item in window.scene_list.selectedItems()
    ] == ['IMG_7656']
    assert window._resolved_selection_photo_ids() == ['IMG_7656']

    window.close()


def test_scene_mode_shift_down_from_scene_strip_preserves_mixed_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Preserve exact mixed selections when shift-moving out of a scene strip.

    This follows the keyboard workflow used for Compare mode: select vertical
    scene rows, extend into a scene with Shift+Right, then keep holding Shift
    and move down to the next vertical scene row. The in-scene photo that is no
    longer visible must remain part of the logical selection.
    """
    theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7660', 'dimgray'),
            ('IMG_7661', 'green'),
            ('IMG_7662', 'blue'),
            ('IMG_7663', 'yellow'),
        ],
        scene_groups=[
            ['IMG_7660'],
            ['IMG_7661', 'IMG_7662'],
            ['IMG_7663'],
        ],
    )
    window.thumbnail_list.setFocus(Qt.OtherFocusReason)
    window.thumbnail_list.viewport().setFocus(Qt.OtherFocusReason)

    QTest.keyClick(window.thumbnail_list, Qt.Key_Down, Qt.ShiftModifier)
    app.processEvents()
    trigger_scene_shortcut(window, 'Shift+Right')
    app.processEvents()

    assert window.current_photo_id == 'IMG_7662'
    assert window._resolved_selection_photo_ids() == [
        'IMG_7660',
        'IMG_7661',
        'IMG_7662',
    ]

    down_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.ShiftModifier)
    window.scene_list.keyPressEvent(down_event)
    app.processEvents()

    assert down_event.isAccepted() is True
    assert window.current_photo_id == 'IMG_7663'
    assert [
        item.data(theme_module.PHOTO_ID_ROLE)
        for item in window.thumbnail_list.selectedItems()
    ] == ['IMG_7660', 'IMG_7661', 'IMG_7663']
    assert [
        item.data(theme_module.PHOTO_ID_ROLE)
        for item in window.scene_list.selectedItems()
    ] == ['IMG_7663']
    assert window._resolved_selection_photo_ids() == [
        'IMG_7660',
        'IMG_7661',
        'IMG_7662',
        'IMG_7663',
    ]

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.compare_viewer.photo_ids() == [
        'IMG_7660',
        'IMG_7661',
        'IMG_7662',
        'IMG_7663',
    ]

    window.close()


def test_scene_mode_ctrl_click_preserves_hidden_scene_selection_for_compare(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Preserve in-scene Ctrl-click selections after moving to another scene row.

    Ctrl-clicking a vertical thumbnail can rebuild the horizontal scene strip.
    Non-cover photos selected in the previous strip must stay in the logical
    selection so Compare mode receives the exact selected photos.
    """
    theme_module, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7670', 'dimgray'),
            ('IMG_7671', 'green'),
            ('IMG_7672', 'blue'),
            ('IMG_7673', 'yellow'),
        ],
        scene_groups=[
            ['IMG_7670', 'IMG_7671', 'IMG_7672'],
            ['IMG_7673'],
        ],
    )

    _ctrl_click_item(window.scene_list, 1)
    app.processEvents()
    _ctrl_click_item(window.scene_list, 2)
    app.processEvents()

    assert window._resolved_selection_photo_ids() == [
        'IMG_7670',
        'IMG_7671',
        'IMG_7672',
    ]

    _ctrl_click_item(window.thumbnail_list, 1)
    app.processEvents()

    assert window.current_photo_id == 'IMG_7673'
    assert [
        item.data(theme_module.PHOTO_ID_ROLE)
        for item in window.thumbnail_list.selectedItems()
    ] == ['IMG_7670', 'IMG_7673']
    assert [
        item.data(theme_module.PHOTO_ID_ROLE)
        for item in window.scene_list.selectedItems()
    ] == ['IMG_7673']
    assert window._resolved_selection_photo_ids() == [
        'IMG_7670',
        'IMG_7671',
        'IMG_7672',
        'IMG_7673',
    ]

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.compare_viewer.photo_ids() == [
        'IMG_7670',
        'IMG_7671',
        'IMG_7672',
        'IMG_7673',
    ]

    window.close()


def test_scene_mode_ctrl_click_then_shift_down_preserves_hidden_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Preserve Ctrl-clicked in-scene photos through later Shift navigation.

    This covers the hybrid selection workflow where mouse and keyboard
    extension are mixed before entering Compare mode.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_7680', 'dimgray'),
            ('IMG_7681', 'green'),
            ('IMG_7682', 'blue'),
        ],
        scene_groups=[
            ['IMG_7680', 'IMG_7681'],
            ['IMG_7682'],
        ],
    )

    _ctrl_click_item(window.scene_list, 1)
    app.processEvents()

    down_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.ShiftModifier)
    window.scene_list.keyPressEvent(down_event)
    app.processEvents()

    assert window.current_photo_id == 'IMG_7682'
    assert window._resolved_selection_photo_ids() == [
        'IMG_7680',
        'IMG_7681',
        'IMG_7682',
    ]

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.compare_viewer.photo_ids() == [
        'IMG_7680',
        'IMG_7681',
        'IMG_7682',
    ]

    window.close()
