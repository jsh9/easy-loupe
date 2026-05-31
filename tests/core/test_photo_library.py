from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

import easy_cull.analysis.scenes as analysis_scenes_module
import easy_cull.core.photo_library as library_module
from easy_cull.core.folder_loading import (
    PHOTO_SORT_MODE_CAPTURE_TIME,
    PHOTO_SORT_MODE_FILENAME,
)
from easy_cull.core.photo_library import PhotoLibrary
from easy_cull.core.records import (
    METADATA_FILENAME,
    RAW_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    SceneGroup,
)
from tests.core._helpers import FakeHash, create_jpeg, stub_read_exif

if TYPE_CHECKING:
    from pathlib import Path


def test_core_library_module_exports_public_symbols() -> None:
    assert library_module.PhotoLibrary is PhotoLibrary
    assert not hasattr(library_module, 'normalize_metadata_entries')
    assert not hasattr(library_module, 'serialize_metadata_entries')
    assert not hasattr(library_module, '_parse_capture_time')
    assert not hasattr(library_module, '_coerce_number_list')
    assert not hasattr(library_module, '_parse_index')
    assert not hasattr(library_module, '_default_cache_dir')
    assert not hasattr(library_module, '_cosine_similarity')
    assert not hasattr(PhotoLibrary, '_read_exif_metadata')
    assert not hasattr(PhotoLibrary, '_render_source_image')
    assert not hasattr(PhotoLibrary, '_extract_raw_thumbnail')
    assert not hasattr(PhotoLibrary, '_analysis_features')
    assert not hasattr(PhotoLibrary, '_should_merge_scene')


def test_load_folder_groups_jpeg_and_raw_files_by_stem(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'IMG_0001.JPG', 'dimgray')
    (tmp_path / 'IMG_0001.CR3').write_bytes(b'raw')
    create_jpeg(tmp_path / 'IMG_0002.JPG', 'blue')

    exif_map = {
        'IMG_0001.CR3': {
            'ImageWidth': 6000,
            'ImageHeight': 4000,
            'AFAreaXPosition': 1800,
            'AFAreaYPosition': 1200,
            'DateTimeOriginal': '2024:05:01 10:00:00',
        },
        'IMG_0002.JPG': {
            'ImageWidth': 3000,
            'ImageHeight': 2000,
            'DateTimeOriginal': '2024:05:01 10:00:05',
        },
    }
    stub_read_exif(monkeypatch, exif_map)

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(
        tmp_path,
        metadata_entries={
            'photos': {
                'IMG_0001.JPG': {
                    'flag': 'reject',
                    'rating': 4,
                    'color_label': 'green',
                }
            }
        },
    )

    assert [photo.photo_id for photo in library.photos] == [
        'IMG_0001',
        'IMG_0002',
    ]
    first = library.photos[0]
    assert first.files == ['IMG_0001.CR3', 'IMG_0001.JPG']
    assert first.has_jpeg is True
    assert first.has_raw is True
    assert first.focus_point == (0.3, 0.3)
    assert first.flag == 'rejected'
    assert first.rating == 4
    assert first.color_label == 'green'


def test_supported_extensions_include_major_viewer_formats() -> None:
    assert {'.jpg', '.jpeg', '.heic', '.heif'} <= SUPPORTED_EXTENSIONS
    assert {
        '.crw',
        '.cr2',
        '.cr3',
        '.nef',
        '.nrw',
        '.arw',
        '.raf',
        '.rwl',
        '.dng',
        '.rw2',
        '.orf',
        '.ori',
    } <= RAW_EXTENSIONS


def test_load_folder_prefers_heic_preview_over_raw_with_shared_stem(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify HEIF files participate in shared-stem photo records as rasters.

    RAW should remain the metadata source when present, but HEIF must be a
    usable preview source and appear in the EXIF file-size summary.
    """
    (tmp_path / 'IMG_0100.HEIC').write_bytes(b'heic')
    (tmp_path / 'IMG_0100.ARW').write_bytes(b'raw')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    assert [photo.photo_id for photo in library.photos] == ['IMG_0100']
    photo = library.photos[0]
    assert photo.preview_source == tmp_path / 'IMG_0100.HEIC'
    assert photo.metadata_source == tmp_path / 'IMG_0100.ARW'
    assert photo.has_jpeg is False
    assert photo.has_heif is True
    assert photo.has_raster is True
    assert photo.has_raw is True
    assert photo.exif_display == {'File Size': 'HEIF: 1 KB, RAW: 1 KB'}


def test_load_viewer_folder_uses_filename_order_and_can_open_single_file(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify viewer folder loads always use ascending filename order.

    The photo viewer should ignore culling sort preferences, including a
    persisted capture-time reverse order, so adjacent navigation is stable.
    """
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'C.JPG', 'purple')
    stub_read_exif(
        monkeypatch,
        {
            'C.JPG': {'DateTimeOriginal': '2024:05:01 10:00:00'},
            'A.JPG': {'DateTimeOriginal': '2024:05:01 10:00:10'},
        },
    )

    library = PhotoLibrary(
        cache_dir=tmp_path / '.cache',
        sort_mode=PHOTO_SORT_MODE_CAPTURE_TIME,
        sort_reversed=True,
    )
    library.load_viewer_folder(tmp_path / 'B.JPG')

    assert [photo.photo_id for photo in library.photos] == ['A', 'B', 'C']
    assert library.sort_mode == PHOTO_SORT_MODE_FILENAME
    assert library.sort_reversed is False
    assert all(photo.focus_point_pending for photo in library.photos)

    single_library = PhotoLibrary(cache_dir=tmp_path / '.single-cache')
    single_library.load_viewer_folder(
        tmp_path / 'B.JPG', allow_folder_scan=False
    )

    assert [photo.photo_id for photo in single_library.photos] == ['B']
    assert single_library.get_photo('B').focus_point_pending is True


def test_load_folder_rejects_missing_directory(tmp_path: Path) -> None:
    library = PhotoLibrary(cache_dir=tmp_path / '.cache')

    with pytest.raises(FileNotFoundError, match='is not a directory'):
        library.load_folder(tmp_path / 'missing')


def test_load_folder_sorts_by_capture_time_ignores_unsupported_files_and_reports_progress(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'IMG_2102.JPG', 'blue')
    create_jpeg(tmp_path / 'IMG_2100.JPEG', 'green')
    (tmp_path / 'IMG_2101.NEF').write_bytes(b'raw')
    (tmp_path / 'notes.txt').write_text('ignore me', encoding='utf-8')

    exif_map = {
        'IMG_2100.JPEG': {'CreateDate': '2024-05-01T10:00:00'},
        'IMG_2101.NEF': {'DateTimeOriginal': '2024:05:01 10:00:05'},
    }
    stub_read_exif(monkeypatch, exif_map)

    progress_updates: list[tuple[str, int]] = []
    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.scenes = [SceneGroup(scene_id='scene-old', photo_ids=['OLD'])]
    library.scene_detection_done = True

    library.load_folder(
        tmp_path,
        folder_label='Shoot A',
        progress_callback=lambda message, progress: progress_updates.append((
            message,
            progress,
        )),
    )

    assert [photo.photo_id for photo in library.photos] == [
        'IMG_2100',
        'IMG_2101',
        'IMG_2102',
    ]
    assert library.folder_label == 'Shoot A'
    assert library.scenes == []
    assert library.scene_detection_done is False
    assert progress_updates[0] == ('Scanning folder', 5)
    assert progress_updates[1] == ('Reading metadata', 20)
    assert progress_updates[-1] == ('Finished loading folder', 100)
    assert all('notes.txt' not in photo.files for photo in library.photos)
    assert library.photos[0].capture_at == datetime(
        2024, 5, 1, 10, 0, 0, tzinfo=UTC
    )
    assert library.photos[1].capture_at == datetime(
        2024, 5, 1, 10, 0, 5, tzinfo=UTC
    )
    assert library.photos[2].capture_at is None


def test_load_folder_filename_sort_ignores_missing_capture_times(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify filename sort does not push untimed photos behind timed photos.

    Capture-time fallback behavior should apply only in capture-time mode.
    """
    create_jpeg(tmp_path / 'IMG_2102.JPG', 'blue')
    create_jpeg(tmp_path / 'IMG_2100.JPG', 'green')
    create_jpeg(tmp_path / 'IMG_2101.JPG', 'purple')
    stub_read_exif(
        monkeypatch,
        {
            'IMG_2102.JPG': {'DateTimeOriginal': '2024:05:01 10:00:00'},
            'IMG_2101.JPG': {'DateTimeOriginal': '2024:05:01 10:00:05'},
        },
    )

    library = PhotoLibrary(
        cache_dir=tmp_path / '.cache', sort_mode=PHOTO_SORT_MODE_FILENAME
    )

    library.load_folder(tmp_path)

    assert [photo.photo_id for photo in library.photos] == [
        'IMG_2100',
        'IMG_2101',
        'IMG_2102',
    ]


def test_load_folder_reversed_capture_sort_keeps_missing_times_last(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify reverse capture-time sort still leaves untimed photos at the end.

    Reverse means newest dated photo first; photos without EXIF capture time
    should not jump ahead of dated photos just because direction changes.
    """
    create_jpeg(tmp_path / 'IMG_2112.JPG', 'blue')
    create_jpeg(tmp_path / 'IMG_2110.JPG', 'green')
    create_jpeg(tmp_path / 'IMG_2111.JPG', 'purple')
    stub_read_exif(
        monkeypatch,
        {
            'IMG_2110.JPG': {'DateTimeOriginal': '2024:05:01 10:00:00'},
            'IMG_2112.JPG': {'DateTimeOriginal': '2024:05:01 10:00:10'},
        },
    )

    library = PhotoLibrary(
        cache_dir=tmp_path / '.cache',
        sort_mode=PHOTO_SORT_MODE_CAPTURE_TIME,
        sort_reversed=True,
    )

    library.load_folder(tmp_path)

    assert library.sort_reversed is True
    assert [photo.photo_id for photo in library.photos] == [
        'IMG_2112',
        'IMG_2110',
        'IMG_2111',
    ]


def test_set_sort_mode_reorders_loaded_photos_and_scene_groups(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify changing sort mode reorders loaded records without rereading EXIF.

    Scene groups should keep their membership while following the new photo
    order so the UI cover rows and scene IDs remain consistent.
    """
    for photo_id in ['IMG_2200', 'IMG_2201', 'IMG_2202']:
        create_jpeg(tmp_path / f'{photo_id}.JPG', 'white')

    stub_read_exif(
        monkeypatch,
        {
            'IMG_2200.JPG': {'DateTimeOriginal': '2024:05:01 10:00:10'},
            'IMG_2201.JPG': {'DateTimeOriginal': '2024:05:01 10:00:00'},
            'IMG_2202.JPG': {'DateTimeOriginal': '2024:05:01 10:00:05'},
        },
    )
    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    library.set_scene_group_photo_ids(
        [['IMG_2201', 'IMG_2202'], ['IMG_2200']],
        scene_source='manual',
    )

    library.set_sort_mode(PHOTO_SORT_MODE_FILENAME)

    assert library.sort_mode == PHOTO_SORT_MODE_FILENAME
    assert [photo.photo_id for photo in library.photos] == [
        'IMG_2200',
        'IMG_2201',
        'IMG_2202',
    ]
    assert [scene.photo_ids for scene in library.scenes] == [
        ['IMG_2200'],
        ['IMG_2201', 'IMG_2202'],
    ]
    assert library.get_photo('IMG_2200').scene_id == 'scene-0001'
    assert library.get_photo('IMG_2201').scene_id == 'scene-0002'

    library.set_sort_mode('invalid')

    assert library.sort_mode == PHOTO_SORT_MODE_CAPTURE_TIME
    assert [photo.photo_id for photo in library.photos] == [
        'IMG_2201',
        'IMG_2202',
        'IMG_2200',
    ]


def test_set_sort_order_reverses_loaded_photos_and_scene_groups(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify sort direction changes reorder photos and existing scene groups.

    Scene membership should remain unchanged, but covers, scene rows, and
    ``photo.scene_id`` values need to follow the reversed library order.
    """
    for photo_id in ['IMG_2210', 'IMG_2211', 'IMG_2212']:
        create_jpeg(tmp_path / f'{photo_id}.JPG', 'white')

    stub_read_exif(
        monkeypatch,
        {
            'IMG_2210.JPG': {'DateTimeOriginal': '2024:05:01 10:00:10'},
            'IMG_2211.JPG': {'DateTimeOriginal': '2024:05:01 10:00:00'},
            'IMG_2212.JPG': {'DateTimeOriginal': '2024:05:01 10:00:05'},
        },
    )
    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    library.set_scene_group_photo_ids(
        [['IMG_2211', 'IMG_2212'], ['IMG_2210']],
        scene_source='manual',
    )

    library.set_sort_order(
        sort_mode=PHOTO_SORT_MODE_CAPTURE_TIME,
        sort_reversed=True,
    )

    assert library.sort_mode == PHOTO_SORT_MODE_CAPTURE_TIME
    assert library.sort_reversed is True
    assert [photo.photo_id for photo in library.photos] == [
        'IMG_2210',
        'IMG_2212',
        'IMG_2211',
    ]
    assert [scene.photo_ids for scene in library.scenes] == [
        ['IMG_2210'],
        ['IMG_2212', 'IMG_2211'],
    ]
    assert library.get_photo('IMG_2210').scene_id == 'scene-0001'
    assert library.get_photo('IMG_2212').scene_id == 'scene-0002'


@pytest.mark.parametrize(
    (
        'initial_sort_mode',
        'next_sort_mode',
        'expected_initial_order',
        'merge_photo_ids',
        'expected_groups_after_merge',
        'expected_groups_after_resort',
    ),
    [
        pytest.param(
            PHOTO_SORT_MODE_FILENAME,
            PHOTO_SORT_MODE_CAPTURE_TIME,
            ['IMG_2300', 'IMG_2301', 'IMG_2302', 'IMG_2303'],
            ['IMG_2301', 'IMG_2302'],
            [['IMG_2300'], ['IMG_2301', 'IMG_2302'], ['IMG_2303']],
            [['IMG_2302', 'IMG_2301'], ['IMG_2300'], ['IMG_2303']],
            id='filename-to-capture-time',
        ),
        pytest.param(
            PHOTO_SORT_MODE_CAPTURE_TIME,
            PHOTO_SORT_MODE_FILENAME,
            ['IMG_2302', 'IMG_2300', 'IMG_2303', 'IMG_2301'],
            ['IMG_2302', 'IMG_2301'],
            [['IMG_2302', 'IMG_2301'], ['IMG_2300'], ['IMG_2303']],
            [['IMG_2300'], ['IMG_2301', 'IMG_2302'], ['IMG_2303']],
            id='capture-time-to-filename',
        ),
    ],
)
def test_sort_change_preserves_scene_merge_created_under_current_sort(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        initial_sort_mode: str,
        next_sort_mode: str,
        expected_initial_order: list[str],
        merge_photo_ids: list[str],
        expected_groups_after_merge: list[list[str]],
        expected_groups_after_resort: list[list[str]],
) -> None:
    """
    Verify merged scene membership survives later sort-mode changes.

    This covers the multi-photo selection workflow: a merge is created under
    one display order, then the user changes sorting. Membership should stay
    intact while each scene group follows the newly active order.
    """
    for photo_id in ['IMG_2300', 'IMG_2301', 'IMG_2302', 'IMG_2303']:
        create_jpeg(tmp_path / f'{photo_id}.JPG', 'white')

    stub_read_exif(
        monkeypatch,
        {
            'IMG_2300.JPG': {'DateTimeOriginal': '2024:05:01 10:00:05'},
            'IMG_2301.JPG': {'DateTimeOriginal': '2024:05:01 10:00:15'},
            'IMG_2302.JPG': {'DateTimeOriginal': '2024:05:01 10:00:00'},
            'IMG_2303.JPG': {'DateTimeOriginal': '2024:05:01 10:00:10'},
        },
    )
    library = PhotoLibrary(
        cache_dir=tmp_path / '.cache',
        sort_mode=initial_sort_mode,
    )
    library.load_folder(tmp_path)

    assert [photo.photo_id for photo in library.photos] == (
        expected_initial_order
    )

    library.merge_photos_into_scene(merge_photo_ids)

    assert library.scene_source == 'manual'
    assert library.scene_detection_done is True
    assert [scene.photo_ids for scene in library.scenes] == (
        expected_groups_after_merge
    )

    library.set_sort_mode(next_sort_mode)

    assert [scene.photo_ids for scene in library.scenes] == (
        expected_groups_after_resort
    )
    for scene in library.scenes:
        for photo_id in scene.photo_ids:
            assert library.get_photo(photo_id).scene_id == scene.scene_id


def test_set_scene_group_photo_ids_reorders_replayed_groups_to_active_sort(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify replayed scene history follows the current photo sort order.

    Scene undo/redo stores plain ordered groups. If the user changes sort
    before replaying one of those entries, the groups need to be normalized to
    the active library order rather than restoring stale visual order.
    """
    for photo_id in ['IMG_2500', 'IMG_2501', 'IMG_2502', 'IMG_2503']:
        create_jpeg(tmp_path / f'{photo_id}.JPG', 'white')

    stub_read_exif(
        monkeypatch,
        {
            'IMG_2500.JPG': {'DateTimeOriginal': '2024:05:01 10:00:05'},
            'IMG_2501.JPG': {'DateTimeOriginal': '2024:05:01 10:00:15'},
            'IMG_2502.JPG': {'DateTimeOriginal': '2024:05:01 10:00:00'},
            'IMG_2503.JPG': {'DateTimeOriginal': '2024:05:01 10:00:10'},
        },
    )
    library = PhotoLibrary(
        cache_dir=tmp_path / '.cache',
        sort_mode=PHOTO_SORT_MODE_CAPTURE_TIME,
    )
    library.load_folder(tmp_path)

    assert [photo.photo_id for photo in library.photos] == [
        'IMG_2502',
        'IMG_2500',
        'IMG_2503',
        'IMG_2501',
    ]

    library.set_scene_group_photo_ids(
        [['IMG_2501', 'IMG_2500'], ['IMG_2502'], ['IMG_2503']],
        scene_source='manual',
    )

    assert [scene.photo_ids for scene in library.scenes] == [
        ['IMG_2502'],
        ['IMG_2500', 'IMG_2501'],
        ['IMG_2503'],
    ]
    assert library.get_photo('IMG_2502').scene_id == 'scene-0001'
    assert library.get_photo('IMG_2500').scene_id == 'scene-0002'
    assert library.get_photo('IMG_2501').scene_id == 'scene-0002'
    assert library.get_photo('IMG_2503').scene_id == 'scene-0003'


def test_get_photo_and_save_metadata_require_loaded_photo_state(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'IMG_2450.JPG', 'purple')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    with pytest.raises(RuntimeError, match='No folder is currently loaded'):
        library.save_metadata()

    library.load_folder(tmp_path)

    with pytest.raises(KeyError, match='Unknown photo id'):
        library.get_photo('DOES_NOT_EXIST')


def test_detect_scenes_groups_adjacent_similar_photos(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'IMG_4000.JPG', 'white')
    create_jpeg(tmp_path / 'IMG_4001.JPG', 'white')
    create_jpeg(tmp_path / 'IMG_4002.JPG', 'black')
    base_time = datetime(2024, 5, 1, 10, 0, 0, tzinfo=UTC)
    exif_map = {
        'IMG_4000.JPG': {
            'DateTimeOriginal': base_time.strftime('%Y:%m:%d %H:%M:%S')
        },
        'IMG_4001.JPG': {
            'DateTimeOriginal': (base_time + timedelta(seconds=2)).strftime(
                '%Y:%m:%d %H:%M:%S'
            )
        },
        'IMG_4002.JPG': {
            'DateTimeOriginal': (base_time + timedelta(seconds=4)).strftime(
                '%Y:%m:%d %H:%M:%S'
            )
        },
    }
    stub_read_exif(monkeypatch, exif_map)

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    fake_features = {
        'IMG_4000': (FakeHash(0), [1.0, 0.0]),
        'IMG_4001': (FakeHash(4), [0.99, 0.01]),
        'IMG_4002': (FakeHash(18), [0.1, 0.9]),
    }
    monkeypatch.setattr(
        analysis_scenes_module,
        '_analysis_features',
        lambda photo, _get_preview_path_fn: fake_features[photo.photo_id],
    )

    progress_updates = []
    scenes = library.detect_scenes(
        progress_callback=lambda message, progress: progress_updates.append((
            message,
            progress,
        ))
    )

    assert [scene.photo_ids for scene in scenes] == [
        ['IMG_4000', 'IMG_4001'],
        ['IMG_4002'],
    ]
    assert library.photos[0].scene_id == library.photos[1].scene_id
    assert library.photos[2].scene_id != library.photos[1].scene_id
    assert progress_updates[-1] == ('done', 100)


def test_detect_scenes_handles_empty_and_single_photo_libraries(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_library = PhotoLibrary(cache_dir=tmp_path / '.cache-empty')
    empty_progress: list[tuple[str, int]] = []
    empty_scenes = empty_library.detect_scenes(
        progress_callback=lambda message, progress: empty_progress.append((
            message,
            progress,
        ))
    )

    assert empty_scenes == []
    assert empty_library.scene_detection_done is True
    assert empty_progress[0] == ('preparing files', 5)
    assert empty_progress[-1] == ('done', 100)

    create_jpeg(tmp_path / 'IMG_7300.JPG', 'white')
    stub_read_exif(monkeypatch, {})
    single_library = PhotoLibrary(cache_dir=tmp_path / '.cache-single')
    single_library.load_folder(tmp_path)
    monkeypatch.setattr(
        analysis_scenes_module,
        '_analysis_features',
        lambda _photo, _get_preview_path_fn: (FakeHash(0), [1.0, 0.0]),
    )

    scenes = single_library.detect_scenes()

    assert [scene.photo_ids for scene in scenes] == [['IMG_7300']]
    assert single_library.photos[0].scene_id == 'scene-0001'


def test_photo_library_detect_scenes_delegates_to_analysis_module(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PhotoLibrary delegates scene orchestration and stores the result."""
    create_jpeg(tmp_path / 'IMG_7305.JPG', 'white')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    delegated_scenes = [
        SceneGroup(scene_id='scene-0001', photo_ids=['IMG_7305'])
    ]

    def fake_detect_scenes(
            photos: list[Any],
            get_preview_path_fn: Any,
            progress_callback: Any = None,
            *,
            analysis_features_fn: Any = None,
    ) -> list[SceneGroup]:
        del get_preview_path_fn, analysis_features_fn
        if progress_callback is not None:
            progress_callback('done', 100)

        assert photos is library.photos
        return delegated_scenes

    monkeypatch.setattr(
        analysis_scenes_module, 'detect_scenes', fake_detect_scenes
    )

    progress_updates: list[tuple[str, int]] = []
    result = library.detect_scenes(
        progress_callback=lambda message, progress: progress_updates.append((
            message,
            progress,
        ))
    )

    assert result is delegated_scenes
    assert library.scenes is delegated_scenes
    assert library.scene_detection_done is True
    assert progress_updates == [('done', 100)]
    data = json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )
    assert data['scenes'] == {
        'groups': [['IMG_7305']],
        'source': 'detected',
    }


def test_detect_scenes_requires_imagehash_when_analysis_runs(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'IMG_7310.JPG', 'white')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    monkeypatch.setattr('easy_cull.analysis.scenes.imagehash', None)

    with pytest.raises(RuntimeError, match='imagehash is required'):
        library.detect_scenes()


def test_load_folder_hydrates_saved_scene_groups(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'IMG_7400.JPG', 'white')
    create_jpeg(tmp_path / 'IMG_7401.JPG', 'white')
    (tmp_path / METADATA_FILENAME).write_text(
        json.dumps({
            'photos': {},
            'scenes': {
                'source': 'manual',
                'groups': [['IMG_7400', 'IMG_7401']],
            },
        }),
        encoding='utf-8',
    )
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    assert library.scene_detection_done is True
    assert library.scene_source == 'manual'
    assert [scene.photo_ids for scene in library.scenes] == [
        ['IMG_7400', 'IMG_7401']
    ]
    assert library.get_photo('IMG_7400').scene_id == 'scene-0001'
    assert library.get_photo('IMG_7401').scene_id == 'scene-0001'


def test_set_scene_groups_clears_stale_scene_ids(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'IMG_7410.JPG', 'white')
    create_jpeg(tmp_path / 'IMG_7411.JPG', 'white')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    library.set_scene_group_photo_ids(
        [['IMG_7410', 'IMG_7411']], scene_source='manual'
    )
    library.set_scene_group_photo_ids([], scene_source=None)

    assert library.scenes == []
    assert library.scene_detection_done is False
    assert library.get_photo('IMG_7410').scene_id is None
    assert library.get_photo('IMG_7411').scene_id is None


def test_merge_photos_preserves_first_selected_photo_position(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(4):
        create_jpeg(tmp_path / f'IMG_742{index}.JPG', 'white')

    stub_read_exif(monkeypatch, {})
    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    library.set_scene_group_photo_ids(
        [['IMG_7420', 'IMG_7421', 'IMG_7422', 'IMG_7423']],
        scene_source='detected',
    )

    library.merge_photos_into_scene(['IMG_7421', 'IMG_7422'])

    assert [scene.photo_ids for scene in library.scenes] == [
        ['IMG_7420'],
        ['IMG_7421', 'IMG_7422'],
        ['IMG_7423'],
    ]


def test_merge_photos_keeps_exact_existing_detected_group_unchanged(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Avoid turning detected scene metadata into manual metadata for a no-op.

    Selecting an already grouped scene stack in the UI should not create an
    undoable edit or change persisted scene provenance behind the scenes.
    """
    for index in range(4):
        create_jpeg(tmp_path / f'IMG_742{index}.JPG', 'white')

    stub_read_exif(monkeypatch, {})
    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    library.set_scene_group_photo_ids(
        [['IMG_7420', 'IMG_7421'], ['IMG_7422', 'IMG_7423']],
        scene_source='detected',
    )

    library.merge_photos_into_scene(['IMG_7420', 'IMG_7421'])

    assert library.scene_source == 'detected'
    assert [scene.photo_ids for scene in library.scenes] == [
        ['IMG_7420', 'IMG_7421'],
        ['IMG_7422', 'IMG_7423'],
    ]


def test_merge_photos_supports_consecutive_manual_groups(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(4):
        create_jpeg(tmp_path / f'IMG_743{index}.JPG', 'white')

    stub_read_exif(monkeypatch, {})
    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    library.merge_photos_into_scene(['IMG_7430', 'IMG_7431'])
    library.merge_photos_into_scene(['IMG_7432', 'IMG_7433'])

    assert [scene.photo_ids for scene in library.scenes] == [
        ['IMG_7430', 'IMG_7431'],
        ['IMG_7432', 'IMG_7433'],
    ]


def test_get_state_returns_full_library_payload(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'IMG_9010.JPG', 'green')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path, folder_label='Test Shoot')

    state = library.get_state()

    assert state['folder_path'] == 'Test Shoot'
    assert len(state['photos']) == 1
    assert state['photos'][0]['photo_id'] == 'IMG_9010'
    assert state['scenes'] == []
    assert state['scene_detection_done'] is False


def test_load_folder_with_raw_only_photo_sets_correct_sources(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / 'IMG_9020.CR3').write_bytes(b'raw')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    photo = library.photos[0]

    assert photo.photo_id == 'IMG_9020'
    assert photo.has_jpeg is False
    assert photo.has_raw is True
    assert photo.preview_source == tmp_path / 'IMG_9020.CR3'
    assert photo.metadata_source == tmp_path / 'IMG_9020.CR3'


def test_get_photos_and_get_scene_groups_return_shallow_copies(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'IMG_9060.JPG', 'green')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    library.scenes = [SceneGroup(scene_id='s1', photo_ids=['IMG_9060'])]

    photos = library.get_photos()
    scenes = library.get_scene_groups()

    assert photos == library.photos
    assert photos is not library.photos
    assert scenes == library.scenes
    assert scenes is not library.scenes


def test_get_photo_raises_key_error_for_unknown_id(tmp_path: Path) -> None:
    create_jpeg(tmp_path / 'IMG_0001.JPG', 'dimgray')
    lib = library_module.PhotoLibrary()
    lib.load_folder(tmp_path)

    with pytest.raises(KeyError, match='Unknown photo id'):
        lib.get_photo('SOME_ID_THAT_DOES_NOT_EXIST')
