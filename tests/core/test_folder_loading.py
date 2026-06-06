from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import easy_loupe.core.folder_loading as folder_loading_module
from easy_loupe.core.folder_loading import PHOTO_SORT_MODE_FILENAME
from easy_loupe.core.recursive_loading import relative_photo_group_key
from tests.core._helpers import create_jpeg


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


def test_folder_loading_can_scan_direct_children_only(
        tmp_path: Path,
) -> None:
    """
    Verify direct-only loading ignores supported photos in subfolders.

    This protects the user preference from accidentally doing the default
    recursive scan when the top-bar option is unchecked.
    """
    create_jpeg(tmp_path / 'ROOT.JPG', 'blue')
    subfolder = tmp_path / 'subfolder_1'
    subfolder.mkdir()
    create_jpeg(subfolder / 'NESTED.JPG', 'green')

    loaded_state = folder_loading_module.load_folder_state(
        tmp_path,
        load_recursively=False,
        read_exif_metadata_fn=lambda _files: {},
    )

    assert [photo.photo_id for photo in loaded_state.photos] == ['ROOT']
    assert loaded_state.photos[0].files == ['ROOT.JPG']


def test_folder_loading_recursive_scan_uses_posix_relative_ids(
        tmp_path: Path,
) -> None:
    """
    Verify recursive loading uses POSIX relative photo IDs and file paths.

    Duplicate stems are common across camera folders, so subfolder components
    must be part of the ID and the stored file paths.
    """
    create_jpeg(tmp_path / 'IMG_0001.JPG', 'blue')
    subfolder = tmp_path / 'subfolder_1'
    subfolder.mkdir()
    create_jpeg(subfolder / 'IMG_0001.JPG', 'green')
    (subfolder / 'IMG_0001.CR3').write_bytes(b'raw')

    loaded_state = folder_loading_module.load_folder_state(
        tmp_path,
        load_recursively=True,
        read_exif_metadata_fn=lambda _files: {},
    )

    assert [photo.photo_id for photo in loaded_state.photos] == [
        'IMG_0001',
        'subfolder_1/IMG_0001',
    ]
    nested = loaded_state.photo_map['subfolder_1/IMG_0001']
    assert nested.display_name == 'subfolder_1/IMG_0001'
    assert nested.files == [
        'subfolder_1/IMG_0001.CR3',
        'subfolder_1/IMG_0001.JPG',
    ]
    assert nested.has_jpeg is True
    assert nested.has_raw is True


def test_recursive_group_key_preserves_case_distinct_parent_paths() -> None:
    """
    Verify recursive pairing keeps case-only folder names separate.

    The helper-level check is portable on case-insensitive filesystems where
    creating ``Trip`` and ``trip`` as real sibling directories is impossible.
    """
    root = Path('/photos')

    assert relative_photo_group_key(root, root / 'Trip' / 'IMG_1000.JPG') == (
        'Trip',
        'img_1000',
    )
    assert relative_photo_group_key(root, root / 'trip' / 'IMG_1000.CR3') == (
        'trip',
        'img_1000',
    )
    assert relative_photo_group_key(
        root, root / 'IMG_1000.JPG'
    ) == relative_photo_group_key(root, root / 'img_1000.CR3')


def test_folder_loading_recursive_exif_lookup_uses_path_keys(
        tmp_path: Path,
) -> None:
    """
    Verify same basenames in different folders keep distinct EXIF metadata.

    Basename-only EXIF maps would leak capture times or focus data between
    recursive records that share a filename.
    """
    create_jpeg(tmp_path / 'IMG_0001.JPG', 'blue')
    subfolder = tmp_path / 'subfolder_1'
    subfolder.mkdir()
    create_jpeg(subfolder / 'IMG_0001.JPG', 'green')

    loaded_state = folder_loading_module.load_folder_state(
        tmp_path,
        load_recursively=True,
        read_exif_metadata_fn=lambda _files: {
            str((tmp_path / 'IMG_0001.JPG').resolve()): {
                'DateTimeOriginal': '2024:05:01 08:00:00'
            },
            str((subfolder / 'IMG_0001.JPG').resolve()): {
                'DateTimeOriginal': '2024:05:01 09:00:00'
            },
        },
    )

    assert loaded_state.photo_map['IMG_0001'].capture_at == datetime(
        2024, 5, 1, 8, 0, 0, tzinfo=UTC
    )
    assert loaded_state.photo_map['subfolder_1/IMG_0001'].capture_at == (
        datetime(2024, 5, 1, 9, 0, 0, tzinfo=UTC)
    )
