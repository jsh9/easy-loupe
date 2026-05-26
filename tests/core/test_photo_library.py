from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

import easy_cull.analysis.scenes as analysis_scenes_module
import easy_cull.core.photo_library as library_module
from easy_cull.core.photo_library import PhotoLibrary
from easy_cull.core.records import METADATA_FILENAME, SceneGroup
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
