from __future__ import annotations

from typing import TYPE_CHECKING

import easy_photo_culling.core.folder_loading as folder_loading_module
from tests.core._helpers import create_jpeg

if TYPE_CHECKING:
    from pathlib import Path


def test_folder_loading_module_exports_load_folder_state() -> None:
    assert hasattr(folder_loading_module, 'load_folder_state')


def test_folder_loading_load_folder_state_builds_grouped_sorted_records(
        tmp_path: Path,
) -> None:
    """Folder-loading helper builds sorted records and resets scene state."""
    create_jpeg(tmp_path / 'IMG_0101.JPG', 'dimgray')
    (tmp_path / 'IMG_0101.CR3').write_bytes(b'raw')
    create_jpeg(tmp_path / 'IMG_0100.JPG', 'blue')

    exif_map = {
        'IMG_0100.JPG': {'DateTimeOriginal': '2024:05:01 10:00:00'},
        'IMG_0101.CR3': {
            'ImageWidth': 6000,
            'ImageHeight': 4000,
            'AFAreaXPosition': 3000,
            'AFAreaYPosition': 2000,
            'DateTimeOriginal': '2024:05:01 10:00:05',
        },
    }
    progress_updates: list[tuple[str, int]] = []

    loaded_state = folder_loading_module.load_folder_state(
        tmp_path,
        metadata_entries={
            'IMG_0101.JPG': {'rating': 4, 'color_label': 'green'}
        },
        folder_label='Test Folder',
        progress_callback=lambda message, progress: progress_updates.append((
            message,
            progress,
        )),
        read_exif_metadata_fn=lambda _files: exif_map,
    )

    assert [photo.photo_id for photo in loaded_state.photos] == [
        'IMG_0100',
        'IMG_0101',
    ]
    assert loaded_state.folder_label == 'Test Folder'
    assert loaded_state.photo_map['IMG_0101'].files == [
        'IMG_0101.CR3',
        'IMG_0101.JPG',
    ]
    assert loaded_state.photo_map['IMG_0101'].focus_point == (0.5, 0.5)
    assert loaded_state.photo_map['IMG_0101'].rating == 4
    assert loaded_state.photo_map['IMG_0101'].color_label == 'green'
    assert loaded_state.scenes == []
    assert loaded_state.scene_detection_done is False
    assert progress_updates[0] == ('Scanning folder', 5)
    assert progress_updates[1] == ('Reading metadata', 20)
