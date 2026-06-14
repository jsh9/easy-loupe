from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from easy_loupe.core.photo_library import PhotoLibrary
from easy_loupe.operations.common import (
    OperationError,
    UndoPlan,
    undo_operation,
)
from easy_loupe.operations.export import (
    OrganizeFilesOptions,
    organize_photos,
)
from tests.core._helpers import create_jpeg, stub_read_exif

if TYPE_CHECKING:
    from pathlib import Path


def test_export_module_exports_organize_photos() -> None:
    assert organize_photos.__name__ == 'organize_photos'


@pytest.mark.parametrize('criterion', ['flag', 'color_label', 'rating'])
@pytest.mark.parametrize('action', ['copy', 'move'])
@pytest.mark.parametrize('include_untagged', [False, True])
@pytest.mark.parametrize('conflict_policy', ['fail', 'skip', 'overwrite'])
def test_organize_photos_supports_grouped_files_conflicts_and_untagged(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        criterion: str,
        action: str,
        include_untagged: bool,
        conflict_policy: str,
) -> None:
    source_folder, library = _make_library(tmp_path, monkeypatch)
    output_parent = source_folder
    conflict_path = (
        output_parent / _folder_name_for('IMG_A', criterion) / 'IMG_A.JPG'
    )
    conflict_path.parent.mkdir(parents=True, exist_ok=True)
    conflict_path.write_bytes(b'conflict')

    options = OrganizeFilesOptions(
        criterion=criterion,  # type: ignore[arg-type]
        action=action,  # type: ignore[arg-type]
        output_parent=output_parent,
        include_untagged=include_untagged,
        conflict_policy=conflict_policy,  # type: ignore[arg-type]
        include_sidecars=True,
    )

    if conflict_policy == 'fail':
        with pytest.raises(OperationError, match='Destination already exists'):
            organize_photos(source_folder, library.get_photos(), options)

        assert conflict_path.read_bytes() == b'conflict'
        _assert_sources_present(
            source_folder,
            [
                'IMG_A.JPG',
                'IMG_B.CR3',
                'IMG_B.XMP',
                'IMG_C.CR3',
                'IMG_C.JPG',
                'IMG_C.XMP',
            ],
        )
        return

    summary = organize_photos(source_folder, library.get_photos(), options)

    expected_processed_photos = 3 if include_untagged else 2
    expected_processed_files = 6 if include_untagged else 3
    expected_skipped_photos = 1 if conflict_policy == 'skip' else 0
    expected_handled_files = (
        expected_processed_files - 1
        if conflict_policy == 'skip'
        else expected_processed_files
    )

    assert summary.processed_photos == expected_processed_photos
    assert summary.skipped_photos == expected_skipped_photos
    assert summary.skipped_paths == (
        (str(conflict_path),) if conflict_policy == 'skip' else ()
    )

    if action == 'copy':
        assert summary.copied_files == expected_handled_files
        assert summary.moved_files == 0
    else:
        assert summary.copied_files == 0
        assert summary.moved_files == expected_handled_files

    if conflict_policy == 'overwrite':
        assert conflict_path.read_bytes() != b'conflict'
    else:
        assert conflict_path.read_bytes() == b'conflict'

    _assert_destination_files(source_folder, criterion, include_untagged)
    if include_untagged:
        untagged_folder = source_folder / 'Untagged'
        assert {path.name for path in untagged_folder.iterdir()} == {
            'IMG_C.CR3',
            'IMG_C.JPG',
            'IMG_C.XMP',
        }

    if action == 'copy':
        _assert_sources_present(
            source_folder,
            [
                'IMG_A.JPG',
                'IMG_B.CR3',
                'IMG_B.XMP',
                'IMG_C.CR3',
                'IMG_C.JPG',
                'IMG_C.XMP',
            ],
        )
    elif conflict_policy == 'skip':
        _assert_sources_present(source_folder, ['IMG_A.JPG'])
        _assert_sources_absent(
            source_folder,
            ['IMG_B.CR3', 'IMG_B.XMP']
            + (
                ['IMG_C.CR3', 'IMG_C.JPG', 'IMG_C.XMP']
                if include_untagged
                else []
            ),
        )
    else:
        _assert_sources_absent(
            source_folder,
            [
                'IMG_A.JPG',
                'IMG_B.CR3',
                'IMG_B.XMP',
                'IMG_C.CR3',
                'IMG_C.JPG',
                'IMG_C.XMP',
            ]
            if include_untagged
            else ['IMG_A.JPG', 'IMG_B.CR3', 'IMG_B.XMP'],
        )
        if not include_untagged:
            _assert_sources_present(
                source_folder, ['IMG_C.CR3', 'IMG_C.JPG', 'IMG_C.XMP']
            )


@pytest.mark.parametrize('action', ['copy', 'move'])
def test_organize_photos_supports_alternate_output_parent(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        action: str,
) -> None:
    source_folder, library = _make_library(tmp_path, monkeypatch)
    output_parent = tmp_path / 'organized'
    summary = organize_photos(
        source_folder,
        library.get_photos(),
        OrganizeFilesOptions(
            criterion='flag',
            action=action,  # type: ignore[arg-type]
            output_parent=output_parent,
            include_untagged=False,
            conflict_policy='overwrite',
        ),
    )

    assert summary.processed_photos == 2
    assert (output_parent / 'Picked' / 'IMG_A.JPG').exists()
    assert (output_parent / 'Rejected' / 'IMG_B.CR3').exists()
    assert (output_parent / 'Rejected' / 'IMG_B.XMP').exists()
    assert (source_folder / 'Picked').exists() is False
    assert (source_folder / 'Rejected').exists() is False

    if action == 'copy':
        _assert_sources_present(
            source_folder, ['IMG_A.JPG', 'IMG_B.CR3', 'IMG_B.XMP']
        )
    else:
        _assert_sources_absent(
            source_folder, ['IMG_A.JPG', 'IMG_B.CR3', 'IMG_B.XMP']
        )


@pytest.mark.parametrize('action', ['copy', 'move'])
@pytest.mark.parametrize('include_untagged', [False, True])
@pytest.mark.parametrize('use_alternate_output_parent', [False, True])
def test_organize_photos_undo_restores_original_state_and_cleans_created_folders(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        action: str,
        include_untagged: bool,
        use_alternate_output_parent: bool,
) -> None:
    source_folder, library = _make_library(tmp_path, monkeypatch)
    output_parent = (
        tmp_path / 'organized'
        if use_alternate_output_parent
        else source_folder
    )

    summary = organize_photos(
        source_folder,
        library.get_photos(),
        OrganizeFilesOptions(
            criterion='flag',
            action=action,  # type: ignore[arg-type]
            output_parent=output_parent,
            include_untagged=include_untagged,
            conflict_policy='fail',
        ),
    )

    assert summary.undo_plan is not None

    undo_operation(summary.undo_plan)

    _assert_pristine_source_folder(source_folder)
    if use_alternate_output_parent:
        assert output_parent.exists() is False
    else:
        assert (source_folder / 'Picked').exists() is False
        assert (source_folder / 'Rejected').exists() is False
        assert (source_folder / 'Untagged').exists() is False


@pytest.mark.parametrize('action', ['copy', 'move'])
def test_organize_photos_undo_restores_overwritten_destination_files(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        action: str,
) -> None:
    source_folder, library = _make_library(tmp_path, monkeypatch)
    output_parent = tmp_path / 'organized'
    picked_folder = output_parent / 'Picked'
    rejected_folder = output_parent / 'Rejected'
    picked_folder.mkdir(parents=True)
    rejected_folder.mkdir(parents=True)
    conflict_path = picked_folder / 'IMG_A.JPG'
    conflict_path.write_bytes(b'original-destination')

    summary = organize_photos(
        source_folder,
        library.get_photos(),
        OrganizeFilesOptions(
            criterion='flag',
            action=action,  # type: ignore[arg-type]
            output_parent=output_parent,
            include_untagged=False,
            conflict_policy='overwrite',
        ),
    )

    assert conflict_path.read_bytes() != b'original-destination'

    undo_operation(summary.undo_plan)

    assert conflict_path.read_bytes() == b'original-destination'
    _assert_pristine_source_folder(source_folder)
    assert rejected_folder.exists() is True
    assert list(rejected_folder.iterdir()) == []
    assert output_parent.exists() is True


@pytest.mark.parametrize('action', ['copy', 'move'])
def test_organize_photos_rolls_back_partial_failures(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        action: str,
) -> None:
    source_folder, library = _make_library(tmp_path, monkeypatch)
    output_parent = tmp_path / 'organized'

    if action == 'copy':
        original_copy = organize_photos.__globals__['shutil'].copy2
        copy_calls = {'count': 0}

        def fail_copy(source: Path, destination: Path) -> Path:
            copy_calls['count'] += 1
            if copy_calls['count'] == 2:
                raise RuntimeError('copy boom')

            return original_copy(source, destination)

        monkeypatch.setattr(
            organize_photos.__globals__['shutil'], 'copy2', fail_copy
        )
    else:
        original_move = organize_photos.__globals__['shutil'].move
        move_calls = {'count': 0}

        def fail_move(source: Path, destination: Path) -> Path:
            move_calls['count'] += 1
            if move_calls['count'] == 2:
                raise RuntimeError('move boom')

            return original_move(source, destination)

        monkeypatch.setattr(
            organize_photos.__globals__['shutil'], 'move', fail_move
        )

    with pytest.raises(RuntimeError, match='boom'):
        organize_photos(
            source_folder,
            library.get_photos(),
            OrganizeFilesOptions(
                criterion='flag',
                action=action,  # type: ignore[arg-type]
                output_parent=output_parent,
                include_untagged=False,
                conflict_policy='fail',
            ),
        )

    _assert_pristine_source_folder(source_folder)
    assert output_parent.exists() is False


def test_organize_photos_preserves_relative_subfolder_paths(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify organizer output keeps recursive source subfolders under buckets.

    Without the relative path, two nested photos with the same filename could
    collide in the same tag folder.
    """
    source_folder = tmp_path / 'source'
    nested = source_folder / 'subfolder_1'
    nested.mkdir(parents=True)
    create_jpeg(nested / 'IMG_A.JPG', 'red')
    (nested / 'IMG_A.XMP').write_text('<xmp/>', encoding='utf-8')
    stub_read_exif(monkeypatch, {})
    library = PhotoLibrary(cache_dir=tmp_path / '.cache-recursive')
    library.load_folder(source_folder)
    library.update_metadata(
        'subfolder_1/IMG_A',
        flag='picked',
        fields={'flag'},
    )

    output_parent = tmp_path / 'organized'
    summary = organize_photos(
        source_folder,
        library.get_photos(),
        OrganizeFilesOptions(
            criterion='flag',
            action='copy',
            output_parent=output_parent,
            include_untagged=False,
            conflict_policy='fail',
            include_sidecars=True,
        ),
    )

    assert summary.copied_files == 2
    assert (output_parent / 'Picked' / 'subfolder_1' / 'IMG_A.JPG').exists()
    assert (output_parent / 'Picked' / 'subfolder_1' / 'IMG_A.XMP').exists()
    assert (source_folder / 'Picked').exists() is False


def test_organize_and_undo_report_structured_progress(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify file operations expose counted structured progress stages.

    This protects organize and undo overlays from regressing to scalar-only
    progress while the filesystem operation behavior stays unchanged.
    """
    source_folder, library = _make_library(tmp_path, monkeypatch)
    output_parent = tmp_path / 'organized'
    options = OrganizeFilesOptions(
        criterion='flag',
        action='copy',
        output_parent=output_parent,
        include_untagged=False,
        conflict_policy='fail',
    )
    progress_updates: list[tuple[str, int]] = []
    progress_snapshots = []

    summary = organize_photos(
        source_folder,
        library.get_photos(),
        options,
        lambda message, progress: progress_updates.append((
            message,
            progress,
        )),
        progress_snapshot_callback=progress_snapshots.append,
    )

    assert progress_updates[0] == ('Preparing photo organization', 5)
    assert progress_updates[1] == ('Organizing photo files, 1 of 2', 52)
    assert progress_snapshots[-2].stages[1].count_text() == '2 of 2'
    assert progress_snapshots[-2].stages[1].status == 'complete'

    undo_snapshots = []
    undo_operation(
        summary.undo_plan,
        progress_snapshot_callback=undo_snapshots.append,
    )

    undo_stage = undo_snapshots[-1].stages[0]
    assert undo_stage.status == 'complete'
    assert undo_stage.count_text().endswith(f'of {undo_stage.total}')


def test_organize_skip_conflict_reports_completed_progress(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify skipped organizer jobs still advance counted progress.

    Conflict-policy ``skip`` bypasses the file-copy loop for one photo, but it
    still represents a completed job from the user's progress perspective.
    """
    source_folder, library = _make_library(tmp_path, monkeypatch)
    conflict_path = source_folder / 'Picked' / 'IMG_A.JPG'
    conflict_path.parent.mkdir(parents=True)
    conflict_path.write_bytes(b'conflict')
    progress_updates: list[tuple[str, int]] = []
    progress_snapshots = []

    summary = organize_photos(
        source_folder,
        library.get_photos(),
        OrganizeFilesOptions(
            criterion='flag',
            action='copy',
            output_parent=source_folder,
            include_untagged=False,
            conflict_policy='skip',
        ),
        lambda message, progress: progress_updates.append((
            message,
            progress,
        )),
        progress_snapshot_callback=progress_snapshots.append,
    )

    organize_stage = next(
        stage
        for stage in progress_snapshots[-2].stages
        if stage.stage_id == 'organize'
    )
    assert summary.skipped_photos == 1
    assert progress_updates[1] == ('Organizing photo files, 1 of 2', 52)
    assert progress_updates[2] == ('Organizing photo files, 2 of 2', 99)
    assert organize_stage.status == 'complete'
    assert organize_stage.count_text() == '2 of 2'
    assert conflict_path.read_bytes() == b'conflict'


def test_organize_photos_empty_jobs_report_zero_total_progress(
        tmp_path: Path,
) -> None:
    """
    Verify no-op organization reports completed zero-work progress.

    When no photos match the requested organization plan, the structured
    overlay should render the organize stage as status-only instead of an
    unknown-total completed progress bar.
    """
    source_folder = tmp_path / 'source'
    source_folder.mkdir()
    progress_snapshots = []

    summary = organize_photos(
        source_folder,
        [],
        OrganizeFilesOptions(
            criterion='flag',
            action='copy',
            output_parent=tmp_path / 'organized',
            include_untagged=False,
            conflict_policy='fail',
        ),
        progress_snapshot_callback=progress_snapshots.append,
    )

    organize_stage = next(
        stage
        for stage in progress_snapshots[-1].stages
        if stage.stage_id == 'organize'
    )
    assert summary.processed_photos == 0
    assert organize_stage.status == 'complete'
    assert organize_stage.current == 0
    assert organize_stage.total == 0
    assert organize_stage.count_text() == ''


def test_empty_undo_plan_reports_complete_zero_progress() -> None:
    """
    Verify no-op undo still emits a completed progress stage.

    Skipped or no-op operations can produce an empty undo plan. The progress
    overlay should receive a terminal update instead of staying at its
    preparation message until the UI hides it.
    """
    undo_plan = UndoPlan()
    progress_updates: list[tuple[str, int]] = []
    progress_snapshots = []

    undo_operation(
        undo_plan,
        lambda message, progress: progress_updates.append((
            message,
            progress,
        )),
        progress_snapshot_callback=progress_snapshots.append,
    )

    undo_stage = progress_snapshots[-1].stages[0]
    assert undo_plan.consumed is True
    assert progress_updates == [('Undoing photo organization', 100)]
    assert undo_stage.status == 'complete'
    assert undo_stage.total == 0
    assert undo_stage.count_text() == ''


def _make_library(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, PhotoLibrary]:
    source_folder = tmp_path / 'source'
    source_folder.mkdir()
    create_jpeg(source_folder / 'IMG_A.JPG', 'red')
    (source_folder / 'IMG_B.CR3').write_bytes(b'raw-b')
    create_jpeg(source_folder / 'IMG_C.JPG', 'green')
    (source_folder / 'IMG_C.CR3').write_bytes(b'raw-c')
    (source_folder / 'IMG_B.XMP').write_text('<xmp/>', encoding='utf-8')
    (source_folder / 'IMG_C.XMP').write_text('<xmp/>', encoding='utf-8')

    stub_read_exif(monkeypatch, {})
    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(source_folder)
    library.update_metadata(
        'IMG_A',
        rating=1,
        color_label='red',
        flag='picked',
        fields={'rating', 'color_label', 'flag'},
    )
    library.update_metadata(
        'IMG_B',
        rating=3,
        color_label='green',
        flag='rejected',
        fields={'rating', 'color_label', 'flag'},
    )
    return source_folder, library


def _folder_name_for(stem: str, criterion: str) -> str:
    if criterion == 'flag':
        return 'Picked' if stem == 'IMG_A' else 'Rejected'

    if criterion == 'color_label':
        return 'Red' if stem == 'IMG_A' else 'Green'

    return '1 Star' if stem == 'IMG_A' else '3 Stars'


def _assert_destination_files(
        output_parent: Path, criterion: str, include_untagged: bool
) -> None:
    assert (
        output_parent / _folder_name_for('IMG_A', criterion) / 'IMG_A.JPG'
    ).exists()
    target_folder = output_parent / _folder_name_for('IMG_B', criterion)
    assert {path.name for path in target_folder.iterdir()} == {
        'IMG_B.CR3',
        'IMG_B.XMP',
    }
    if include_untagged:
        assert len(list((output_parent / 'Untagged').glob('IMG_C*'))) == 3


def _assert_sources_present(folder: Path, names: list[str]) -> None:
    for name in names:
        assert (folder / name).exists()


def _assert_sources_absent(folder: Path, names: list[str]) -> None:
    for name in names:
        assert (folder / name).exists() is False


def _assert_pristine_source_folder(source_folder: Path) -> None:
    _assert_sources_present(
        source_folder,
        [
            'IMG_A.JPG',
            'IMG_B.CR3',
            'IMG_B.XMP',
            'IMG_C.CR3',
            'IMG_C.JPG',
            'IMG_C.XMP',
        ],
    )
    assert (source_folder / 'Picked').exists() is False
    assert (source_folder / 'Rejected').exists() is False
    assert (source_folder / 'Untagged').exists() is False
