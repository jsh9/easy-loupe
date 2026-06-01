from __future__ import annotations

from typing import TYPE_CHECKING

import easy_loupe.core.folder_loading as folder_loading_module
from easy_loupe.core.folder_loading import PHOTO_SORT_MODE_FILENAME
from tests.core._helpers import create_jpeg

if TYPE_CHECKING:
    from pathlib import Path


def test_folder_loading_module_exports_load_folder_state() -> None:
    assert hasattr(folder_loading_module, 'load_folder_state')


def test_folder_loading_load_folder_state_builds_grouped_sorted_records(
        tmp_path: Path,
) -> None:
    """Folder-loading helper builds sorted records and resets scene state."""
    (tmp_path / 'IMG_0101.JPG').write_bytes(b'j' * 1536)
    (tmp_path / 'IMG_0101.CR3').write_bytes(b'r' * (2 * 1024 * 1024))
    create_jpeg(tmp_path / 'IMG_0100.JPG', 'blue')

    exif_map = {
        'IMG_0100.JPG': {'DateTimeOriginal': '2024:05:01 08:00:00'},
        'IMG_0101.CR3': {
            'Make': 'Canon',
            'Model': 'EOS R5',
            'LensModel': 'RF 50mm F1.2L USM',
            'ImageWidth': 6000,
            'ImageHeight': 4000,
            'AFAreaXPosition': 3000,
            'AFAreaYPosition': 2000,
            'DateTimeOriginal': '2024:05:01 09:00:05',
        },
    }
    progress_updates: list[tuple[str, int]] = []

    loaded_state = folder_loading_module.load_folder_state(
        tmp_path,
        metadata_entries={
            'photos': {'IMG_0101.JPG': {'rating': 4, 'color_label': 'green'}}
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
    assert loaded_state.photo_map['IMG_0101'].exif_display == {
        'Captured': '2024-05-01, 9:00:05 AM',
        'Camera Make': 'Canon',
        'Camera Model': 'EOS R5',
        'Lens Model': 'RF 50mm F1.2L USM',
        'Resolution': '6000 x 4000 pixels (24.0 MP)',
        'File Size': 'JPG: 2 KB, RAW: 2.0 MB',
    }
    assert loaded_state.photo_map['IMG_0101'].rating == 4
    assert loaded_state.photo_map['IMG_0101'].color_label == 'green'
    assert loaded_state.scenes == []
    assert loaded_state.scene_detection_done is False
    assert progress_updates[0] == ('Scanning folder', 5)
    assert progress_updates[1] == ('Reading metadata', 20)


def test_folder_loading_can_sort_records_by_filename(tmp_path: Path) -> None:
    """
    Verify filename sort ignores EXIF chronology at the loader boundary.

    This protects the user preference before records reach ``PhotoLibrary``.
    """
    create_jpeg(tmp_path / 'IMG_0102.JPG', 'dimgray')
    create_jpeg(tmp_path / 'IMG_0100.JPG', 'blue')
    create_jpeg(tmp_path / 'IMG_0101.JPG', 'green')

    exif_map = {
        'IMG_0102.JPG': {'DateTimeOriginal': '2024:05:01 10:00:00'},
        'IMG_0101.JPG': {'DateTimeOriginal': '2024:05:01 10:00:05'},
    }

    loaded_state = folder_loading_module.load_folder_state(
        tmp_path,
        sort_mode=PHOTO_SORT_MODE_FILENAME,
        read_exif_metadata_fn=lambda _files: exif_map,
    )

    assert [photo.photo_id for photo in loaded_state.photos] == [
        'IMG_0100',
        'IMG_0101',
        'IMG_0102',
    ]


def test_folder_loading_can_reverse_filename_sort(tmp_path: Path) -> None:
    """
    Verify folder loading applies the persisted reverse direction.

    The loader is the first boundary that builds visible photo order, so it
    must honor reverse sorting before the records reach ``PhotoLibrary``.
    """
    create_jpeg(tmp_path / 'IMG_0102.JPG', 'dimgray')
    create_jpeg(tmp_path / 'IMG_0100.JPG', 'blue')
    create_jpeg(tmp_path / 'IMG_0101.JPG', 'green')

    loaded_state = folder_loading_module.load_folder_state(
        tmp_path,
        sort_mode=PHOTO_SORT_MODE_FILENAME,
        sort_reversed=True,
        read_exif_metadata_fn=lambda _files: {},
    )

    assert [photo.photo_id for photo in loaded_state.photos] == [
        'IMG_0102',
        'IMG_0101',
        'IMG_0100',
    ]
