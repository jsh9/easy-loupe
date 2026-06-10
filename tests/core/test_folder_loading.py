from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import easy_loupe.core.folder_loading as folder_loading_module
from easy_loupe.core.folder_loading import PHOTO_SORT_MODE_FILENAME
from easy_loupe.core.recursive_loading import relative_photo_group_key
from easy_loupe.progress import ProgressReporter
from tests.core._helpers import create_jpeg


def test_folder_loading_module_exports_load_folder_state() -> None:
    assert hasattr(folder_loading_module, 'load_folder_state')


@pytest.mark.parametrize(
    ('photo_count', 'expected_batch_size'),
    [
        pytest.param(0, 20, id='empty-folder'),
        pytest.param(1, 20, id='single-photo'),
        pytest.param(100, 20, id='small-upper-bound'),
        pytest.param(101, 50, id='medium-lower-bound'),
        pytest.param(499, 50, id='medium-upper-bound'),
        pytest.param(500, 100, id='large-lower-bound'),
        pytest.param(3651, 100, id='large-folder'),
    ],
)
def test_metadata_batch_size_uses_grouped_photo_thresholds(
        photo_count: int, expected_batch_size: int
) -> None:
    """
    Verify metadata batch sizes are based on grouped photo counts.

    This protects the user-visible progress cadence where JPEG+RAW companions
    count as one photo, and the threshold edges are easy to regress.
    """
    assert (
        folder_loading_module.metadata_batch_size_for_photo_count(photo_count)
        == expected_batch_size
    )


def test_folder_loading_load_folder_state_builds_grouped_sorted_records(
        tmp_path: Path,
) -> None:
    """
    Verify folder loading builds grouped records and reports early progress.

    This broad loader smoke test protects JPEG+RAW grouping, metadata
    application, scene reset, and the scan/metadata progress messages emitted
    before record construction.
    """
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
        read_exif_metadata_fn=lambda _files, **_kwargs: exif_map,
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
    assert progress_updates[1] == ('Discovered 2 photos from 3 files', 20)
    assert (
        'Loading EXIF data, batch 1 of 1 (20 photos per batch)',
        35,
    ) in progress_updates


def test_folder_loading_reads_one_primary_metadata_source_per_group(
        tmp_path: Path,
) -> None:
    """
    Verify the first EXIF pass sends only one source for each photo group.

    Paired JPEG+RAW photos used to send both files to ExifTool. This regression
    test keeps the optimized primary pass aligned with the record metadata
    source priority: RAW when present, otherwise the preview source.
    """
    create_jpeg(tmp_path / 'JPEG_ONLY.JPG', 'blue')
    (tmp_path / 'PAIR.CR3').write_bytes(b'raw')
    create_jpeg(tmp_path / 'PAIR.JPG', 'green')
    (tmp_path / 'RAW_ONLY.CR3').write_bytes(b'raw')
    calls: list[list[Path]] = []

    def fake_read_exif_metadata(
            files: list[Path], **_kwargs: Any
    ) -> dict[str, dict[str, Any]]:
        calls.append(list(files))
        return {path.name: {'SourceFile': path.name} for path in files}

    loaded_state = folder_loading_module.load_folder_state(
        tmp_path,
        read_exif_metadata_fn=fake_read_exif_metadata,
    )

    assert [[path.name for path in call] for call in calls] == [
        [
            'JPEG_ONLY.JPG',
            'PAIR.CR3',
            'RAW_ONLY.CR3',
        ]
    ]
    assert loaded_state.photo_map['JPEG_ONLY'].metadata_source == (
        tmp_path / 'JPEG_ONLY.JPG'
    )
    assert loaded_state.photo_map['PAIR'].metadata_source == (
        tmp_path / 'PAIR.CR3'
    )
    assert loaded_state.photo_map['RAW_ONLY'].metadata_source == (
        tmp_path / 'RAW_ONLY.CR3'
    )


def test_folder_loading_accepts_legacy_one_argument_exif_reader(
        tmp_path: Path,
) -> None:
    """
    Verify exported folder loading still accepts one-argument EXIF readers.

    Batch progress kwargs were added after ``load_folder_state`` was already
    importable by tests and callers, so the adapter must preserve simple
    ``reader(files)`` injections while production readers receive richer hooks.
    """
    create_jpeg(tmp_path / 'IMG_3100.JPG', 'blue')
    calls: list[list[Path]] = []

    def fake_read_exif_metadata(
            files: list[Path],
    ) -> dict[str, dict[str, Any]]:
        calls.append(list(files))
        return {
            'IMG_3100.JPG': {
                'DateTimeOriginal': '2024:05:01 08:30:00',
            }
        }

    loaded_state = folder_loading_module.load_folder_state(
        tmp_path,
        read_exif_metadata_fn=fake_read_exif_metadata,
    )

    assert [[path.name for path in call] for call in calls] == [
        ['IMG_3100.JPG']
    ]
    assert loaded_state.photos[0].photo_id == 'IMG_3100'
    assert loaded_state.photos[0].capture_at == datetime(
        2024, 5, 1, 8, 30, 0, tzinfo=UTC
    )


def test_folder_loading_reads_preview_metadata_when_primary_is_missing(
        tmp_path: Path,
) -> None:
    """
    Verify paired photos fall back to preview metadata only when needed.

    Some RAW files may not produce usable ExifTool output. The optimized
    primary pass must still preserve the previous record-building fallback to
    JPEG metadata without rereading every JPEG+RAW companion.
    """
    (tmp_path / 'FALLBACK.CR3').write_bytes(b'raw')
    create_jpeg(tmp_path / 'FALLBACK.JPG', 'green')
    (tmp_path / 'GOOD.CR3').write_bytes(b'raw')
    create_jpeg(tmp_path / 'GOOD.JPG', 'blue')
    calls: list[list[Path]] = []
    progress_updates: list[tuple[str, int]] = []

    def fake_read_exif_metadata(
            files: list[Path], **_kwargs: Any
    ) -> dict[str, dict[str, Any]]:
        calls.append(list(files))
        if any(path.suffix.lower() == '.cr3' for path in files):
            return {
                'GOOD.CR3': {
                    'DateTimeOriginal': '2024:05:01 10:30:00',
                }
            }

        return {
            'FALLBACK.JPG': {
                'DateTimeOriginal': '2024:05:01 11:30:00',
                'ImageWidth': 3000,
                'ImageHeight': 2000,
            }
        }

    loaded_state = folder_loading_module.load_folder_state(
        tmp_path,
        progress_callback=lambda message, progress: progress_updates.append((
            message,
            progress,
        )),
        read_exif_metadata_fn=fake_read_exif_metadata,
    )

    assert [[path.name for path in call] for call in calls] == [
        ['FALLBACK.CR3', 'GOOD.CR3'],
        ['FALLBACK.JPG'],
    ]
    assert (
        'Loading fallback EXIF data, batch 1 of 2 (20 photos per batch)',
        27,
    ) in progress_updates
    assert loaded_state.photo_map['FALLBACK'].capture_at == datetime(
        2024, 5, 1, 11, 30, 0, tzinfo=UTC
    )
    assert loaded_state.photo_map['GOOD'].capture_at == datetime(
        2024, 5, 1, 10, 30, 0, tzinfo=UTC
    )
    assert loaded_state.photo_map['FALLBACK'].exif_display['Resolution'] == (
        '3000 x 2000 pixels (6.0 MP)'
    )


def test_folder_loading_progress_reports_scan_counts_and_metadata_batches(
        tmp_path: Path,
) -> None:
    """
    Verify folder-load progress reports discovered counts and EXIF batches.

    Large folders can appear stuck during metadata reads. This protects the
    legacy progress text that the UI overlay uses to show batch movement.
    """
    for index in range(21):
        create_jpeg(tmp_path / f'IMG_{index:04d}.JPG', 'white')

    progress_updates: list[tuple[str, int]] = []

    def fake_read_exif_metadata(
            files: list[Path],
            *,
            batch_size: int,
            batch_progress_callback: Any,
    ) -> dict[str, dict[str, Any]]:
        assert batch_size == 20
        total_batches = 2
        for batch_index in range(1, total_batches + 1):
            batch_progress_callback(batch_index, total_batches, batch_size)

        return {path.name: {} for path in files}

    folder_loading_module.load_folder_state(
        tmp_path,
        progress_callback=lambda message, progress: progress_updates.append((
            message,
            progress,
        )),
        read_exif_metadata_fn=fake_read_exif_metadata,
    )

    assert progress_updates[1] == ('Discovered 21 photos from 21 files', 20)
    assert (
        'Loading EXIF data, batch 1 of 2 (20 photos per batch)',
        27,
    ) in progress_updates
    assert (
        'Loading EXIF data, batch 2 of 2 (20 photos per batch)',
        35,
    ) in progress_updates


def test_folder_loading_empty_metadata_stage_reports_zero_total(
        tmp_path: Path,
) -> None:
    """
    Verify empty folder metadata progress is explicit zero-work progress.

    The structured renderer hides per-stage bars for ``total=0``, so folder
    loading must not leave the metadata stage as unknown-total completion when
    there are no grouped photos to read.
    """
    progress_snapshots = []
    reporter = ProgressReporter(
        'Loading folder',
        folder_loading_module.FOLDER_LOAD_PROGRESS_STAGES,
        snapshot_callback=progress_snapshots.append,
    )

    loaded_state = folder_loading_module.load_folder_state(
        tmp_path,
        progress_reporter=reporter,
        read_exif_metadata_fn=lambda _files, **_kwargs: {},
    )

    metadata_stage = next(
        stage
        for stage in progress_snapshots[-1].stages
        if stage.stage_id == 'metadata'
    )
    assert loaded_state.photos == []
    assert metadata_stage.status == 'complete'
    assert metadata_stage.current == 0
    assert metadata_stage.total == 0
    assert metadata_stage.count_text() == ''


def test_folder_loading_metadata_stage_label_includes_batch_size(
        tmp_path: Path,
) -> None:
    """
    Verify metadata progress row labels keep batch size near the row bar.

    The overlay message also includes the batch size, but this protects the
    stage label shown directly above the metadata progress bar where users look
    while tracking ``Batch X of Y``.
    """
    for index in range(21):
        create_jpeg(tmp_path / f'IMG_{index:04d}.JPG', 'white')

    progress_snapshots = []
    reporter = ProgressReporter(
        'Loading folder',
        folder_loading_module.FOLDER_LOAD_PROGRESS_STAGES,
        snapshot_callback=progress_snapshots.append,
    )

    def fake_read_exif_metadata(
            files: list[Path],
            *,
            batch_size: int,
            batch_progress_callback: Any,
    ) -> dict[str, dict[str, Any]]:
        batch_progress_callback(1, 2, batch_size)
        return {path.name: {} for path in files}

    folder_loading_module.load_folder_state(
        tmp_path,
        progress_reporter=reporter,
        read_exif_metadata_fn=fake_read_exif_metadata,
    )

    metadata_snapshot = next(
        snapshot
        for snapshot in progress_snapshots
        if snapshot.current_message
        == 'Loading EXIF data, batch 1 of 2 (20 photos per batch)'
    )
    metadata_stage = metadata_snapshot.stages[1]
    assert metadata_stage.label == 'Loading EXIF data (20 photos per batch)'
    assert metadata_stage.count_text() == '1 of 2'


def test_folder_loading_preserves_partial_metadata_batch_progress(
        tmp_path: Path,
) -> None:
    """
    Verify stopped EXIF reads do not mark skipped batches complete.

    A launch failure can stop a callback-capable reader before later configured
    batches run. The metadata row should preserve the last completed batch
    count even after record-building progress starts.
    """
    for index in range(60):
        create_jpeg(tmp_path / f'IMG_{index:04d}.JPG', 'white')

    progress_snapshots = []
    reporter = ProgressReporter(
        'Loading folder',
        folder_loading_module.FOLDER_LOAD_PROGRESS_STAGES,
        snapshot_callback=progress_snapshots.append,
    )

    def fake_read_exif_metadata(
            files: list[Path],
            *,
            batch_size: int,
            batch_progress_callback: Any,
    ) -> dict[str, dict[str, Any]]:
        assert len(files) == 60
        assert batch_size == 20
        batch_progress_callback(1, 3, batch_size)
        return {}

    folder_loading_module.load_folder_state(
        tmp_path,
        progress_reporter=reporter,
        read_exif_metadata_fn=fake_read_exif_metadata,
    )

    metadata_counts = [
        snapshot.stages[1].count_text()
        for snapshot in progress_snapshots
        if len(snapshot.stages) > 1
    ]
    metadata_messages = [
        snapshot.current_message
        for snapshot in progress_snapshots
        if 'EXIF data' in snapshot.current_message
    ]
    assert '3 of 3' not in metadata_counts
    assert all('batch 3 of 3' not in message for message in metadata_messages)
    assert (
        'Loading EXIF data, batch 1 of 3 (20 photos per batch)'
        in metadata_messages
    )
    assert progress_snapshots[-1].stages[1].status == 'complete'
    assert progress_snapshots[-1].stages[1].count_text() == '1 of 3'


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
        read_exif_metadata_fn=lambda _files, **_kwargs: exif_map,
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
        read_exif_metadata_fn=lambda _files, **_kwargs: {},
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
        read_exif_metadata_fn=lambda _files, **_kwargs: {},
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
        read_exif_metadata_fn=lambda _files, **_kwargs: {},
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
        read_exif_metadata_fn=lambda _files, **_kwargs: {
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


def test_folder_loading_recursive_missing_exact_record_ignores_basename_key(
        tmp_path: Path,
) -> None:
    """
    Verify path-keyed EXIF maps do not borrow same-basename metadata.

    Production EXIF maps include both resolved paths and basenames. Recursive
    folders can contain duplicate filenames, so a missing exact path record
    must not fall through to another folder's basename key.
    """
    folder_a = tmp_path / 'a'
    folder_b = tmp_path / 'b'
    folder_a.mkdir()
    folder_b.mkdir()
    create_jpeg(folder_a / 'IMG_0001.JPG', 'blue')
    create_jpeg(folder_b / 'IMG_0001.JPG', 'green')
    b_metadata = {'DateTimeOriginal': '2024:05:01 09:00:00'}

    loaded_state = folder_loading_module.load_folder_state(
        tmp_path,
        load_recursively=True,
        read_exif_metadata_fn=lambda _files, **_kwargs: {
            str((folder_b / 'IMG_0001.JPG').resolve()): b_metadata,
            'IMG_0001.JPG': b_metadata,
        },
    )

    assert loaded_state.photo_map['a/IMG_0001'].capture_at is None
    assert loaded_state.photo_map['b/IMG_0001'].capture_at == datetime(
        2024, 5, 1, 9, 0, 0, tzinfo=UTC
    )


def test_folder_loading_recursive_duplicate_raw_names_use_exact_jpeg_fallback(
        tmp_path: Path,
) -> None:
    """
    Verify recursive JPEG fallback ignores RAW basename collisions.

    ExifTool maps also keep basename keys for flat-folder compatibility. When
    recursive folders contain same-named RAW companions, a basename key from
    one folder must not make another folder's failed RAW look successful.
    """
    folder_a = tmp_path / 'a'
    folder_b = tmp_path / 'b'
    folder_a.mkdir()
    folder_b.mkdir()
    (folder_a / 'IMG_0001.CR3').write_bytes(b'raw-a')
    create_jpeg(folder_a / 'IMG_0001.JPG', 'blue')
    (folder_b / 'IMG_0001.CR3').write_bytes(b'raw-b')
    create_jpeg(folder_b / 'IMG_0001.JPG', 'green')
    calls: list[list[Path]] = []

    def fake_read_exif_metadata(
            files: list[Path], **_kwargs: Any
    ) -> dict[str, dict[str, Any]]:
        calls.append(list(files))
        if any(path.suffix.lower() == '.cr3' for path in files):
            raw_metadata = {'DateTimeOriginal': '2024:05:01 09:00:00'}
            return {
                str((folder_b / 'IMG_0001.CR3').resolve()): raw_metadata,
                'IMG_0001.CR3': raw_metadata,
            }

        fallback_metadata = {'DateTimeOriginal': '2024:05:01 08:00:00'}
        return {
            str((folder_a / 'IMG_0001.JPG').resolve()): fallback_metadata,
            'IMG_0001.JPG': fallback_metadata,
        }

    loaded_state = folder_loading_module.load_folder_state(
        tmp_path,
        load_recursively=True,
        read_exif_metadata_fn=fake_read_exif_metadata,
    )

    assert [
        [path.relative_to(tmp_path).as_posix() for path in call]
        for call in calls
    ] == [
        ['a/IMG_0001.CR3', 'b/IMG_0001.CR3'],
        ['a/IMG_0001.JPG'],
    ]
    assert loaded_state.photo_map['a/IMG_0001'].capture_at == datetime(
        2024, 5, 1, 8, 0, 0, tzinfo=UTC
    )
    assert loaded_state.photo_map['b/IMG_0001'].capture_at == datetime(
        2024, 5, 1, 9, 0, 0, tzinfo=UTC
    )
