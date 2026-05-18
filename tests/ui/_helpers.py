from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeySequence
from PySide6.QtWidgets import QApplication

import easy_cull.core.exif as core_exif_module
import easy_cull.ui.main_window.window as main_window_module
import easy_cull.ui.theme as theme_module
from easy_cull.core.photo_library import PhotoLibrary
from easy_cull.core.records import SceneGroup

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def stub_read_exif(
        monkeypatch: pytest.MonkeyPatch,
        exif_map: dict[str, dict[str, Any]],
) -> None:
    monkeypatch.setattr(
        core_exif_module, 'read_exif_metadata', lambda _files: exif_map
    )


def create_jpeg(path: Path, color: str) -> None:
    Image.new('RGB', (640, 480), color=color).save(path, format='JPEG')


def make_photo_record(
        photo_id: str,
        rating: int | None,
        color_label: str | None,
        flag: str | None,
) -> Any:
    return type(
        'PhotoLike',
        (),
        {
            'photo_id': photo_id,
            'rating': rating,
            'color_label': color_label,
            'flag': flag,
        },
    )()


def create_main_window_with_library(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        photo_specs: list[tuple[str, str]],
        scene_groups: list[list[str]] | None = None,
) -> tuple[Any, Any, Any]:
    for photo_id, color in photo_specs:
        create_jpeg(tmp_path / f'{photo_id}.JPG', color)

    stub_read_exif(monkeypatch, {})
    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    if scene_groups is not None:
        library.scenes = [
            SceneGroup(
                scene_id=f'scene-{index:04d}', photo_ids=list(photo_ids)
            )
            for index, photo_ids in enumerate(scene_groups, start=1)
        ]
        for scene in library.scenes:
            for photo_id in scene.photo_ids:
                library.get_photo(photo_id).scene_id = scene.scene_id

        library.scene_detection_done = True

    app = QApplication.instance() or QApplication([])
    window = main_window_module.MainWindow()
    window._initial_folder_prompt_pending = False
    window.library = library
    window.current_photo_id = (
        library.photos[0].photo_id if library.photos else None
    )
    window._populate_thumbnail_list()
    window._populate_browse_list()
    window._populate_scene_list()
    window._display_current_photo()
    window._refresh_ui()
    window.show()
    app.processEvents()
    return theme_module, app, window


def trigger_viewer_shortcut(window: Any, key_text: str) -> None:
    for shortcut in window._viewer_shortcuts:
        if shortcut.key().toString(QKeySequence.PortableText) == key_text:
            shortcut.activated.emit()
            return

    raise AssertionError(f'Missing viewer shortcut for {key_text!r}')


def trigger_scene_shortcut(window: Any, key_text: str) -> None:
    for shortcut in window._scene_nav_shortcuts:
        if shortcut.key().toString(QKeySequence.PortableText) == key_text:
            shortcut.activated.emit()
            return

    raise AssertionError(f'Missing scene shortcut for {key_text!r}')


def thumbnail_overlay(
        list_widget: Any, row: int
) -> tuple[float, float, float, float] | None:
    item = list_widget.item(row)
    assert item is not None
    widget = list_widget.itemWidget(item)
    assert widget is not None
    return widget.visible_region_overlay()


def thumbnail_item_widget(list_widget: Any, row: int) -> Any:
    item = list_widget.item(row)
    assert item is not None
    widget = list_widget.itemWidget(item)
    assert widget is not None
    return widget


def render_widget_image(widget: Any) -> Any:
    pixmap = widget.grab()
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    if pixmap.devicePixelRatio() != 1.0:
        image = image.scaled(
            widget.size(),
            Qt.IgnoreAspectRatio,
            Qt.FastTransformation,
        )

    return image


def image_pixel_rgb(image: Any, x: int, y: int) -> tuple[int, int, int]:
    color = image.pixelColor(x, y)
    return (color.red(), color.green(), color.blue())


def set_scene_detection_result(
        window: Any, scene_groups: list[list[str]]
) -> None:
    window.library.scenes = [
        SceneGroup(scene_id=f'scene-{index:04d}', photo_ids=list(photo_ids))
        for index, photo_ids in enumerate(scene_groups, start=1)
    ]
    for scene in window.library.scenes:
        for photo_id in scene.photo_ids:
            window.library.get_photo(photo_id).scene_id = scene.scene_id

    window.library.scene_detection_done = True


def record_fit_view_calls(window: Any) -> list[str]:
    fit_view_calls: list[str] = []
    original_set_fit_view = window.viewer.set_fit_view

    def record_fit_view() -> None:
        fit_view_calls.append('fit')
        original_set_fit_view()

    window.viewer.set_fit_view = record_fit_view
    return fit_view_calls


def assert_choose_folder_idle(window: Any) -> None:
    assert window.current_photo_id is None
    assert window.library.photos == []
    assert window._busy is False
    assert window.progress_overlay.isHidden() is True
