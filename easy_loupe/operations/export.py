"""Copy or move tagged photo sets into output folders."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from easy_loupe.core.recursive_loading import (
    normalize_relative_file_path,
    resolve_relative_path,
)
from easy_loupe.operations.common import (
    CreatedFileUndo,
    MovedFileUndo,
    OperationError,
    OperationSummary,
    UndoPlan,
    backup_existing_file,
    ensure_directory,
    sidecar_path_for_photo,
    undo_operation,
)
from easy_loupe.progress import (
    ProgressReporter,
    ProgressStageDefinition,
    StructuredProgressCallback,
)

if TYPE_CHECKING:
    from easy_loupe.core.records import PhotoRecord

ProgressCallback = Callable[[str, int], None]
MetadataOrganizeCriterion = Literal['color_label', 'rating']
OrganizeCriterion = Literal['flag', 'color_label', 'rating']
FlagFolderMode = Literal[
    'picked_rejected_untagged',
    'picked_rejected',
    'picked_others',
    'rejected_others',
    'picked_only',
    'rejected_only',
]
OrganizeAction = Literal['copy', 'move']
ConflictPolicy = Literal['fail', 'skip', 'overwrite']


@dataclass(slots=True, frozen=True)
class FlagOrganizeFilesOptions:
    """
    Options for picked/rejected file organization.

    Flag organization has several ways to route photos without a picked or
    rejected flag, so ``flag_folder_mode`` is the only source of truth for that
    decision. Keeping this separate from metadata criteria prevents a stale
    ``include_untagged`` value from looking meaningful for flag runs.
    """

    criterion: Literal['flag']
    action: OrganizeAction
    output_parent: Path
    flag_folder_mode: FlagFolderMode
    conflict_policy: ConflictPolicy
    include_sidecars: bool = True


@dataclass(slots=True, frozen=True)
class MetadataOrganizeFilesOptions:
    """
    Options for rating and color-label file organization.

    Rating and color-label organization only need one missing-metadata choice:
    include untagged photos under ``Untagged`` or skip them. Keeping that
    boolean separate from flag folder modes makes the valid control surface
    match the dialog and avoids ignored fields in organizer callers.
    """

    criterion: MetadataOrganizeCriterion
    action: OrganizeAction
    output_parent: Path
    include_untagged: bool
    conflict_policy: ConflictPolicy
    include_sidecars: bool = True


@dataclass(slots=True, frozen=True)
class OrganizeFilesOptions:
    """
    Legacy options for reorganizing photos into output folders.

    New UI code should prefer ``FlagOrganizeFilesOptions`` or
    ``MetadataOrganizeFilesOptions`` so invalid criterion-specific fields
    cannot be mixed, but this dataclass remains callable for existing
    integrations.

    For legacy flag runs, ``include_untagged`` maps to the old two-choice
    behavior: picked/rejected only, or picked/rejected plus untagged.
    """

    criterion: OrganizeCriterion
    action: OrganizeAction
    output_parent: Path
    include_untagged: bool
    conflict_policy: ConflictPolicy
    include_sidecars: bool = True


type OrganizeFilesRequest = (
    FlagOrganizeFilesOptions
    | MetadataOrganizeFilesOptions
    | OrganizeFilesOptions
)


def organize_photos(
        current_folder: Path,
        photos: list[PhotoRecord],
        options: OrganizeFilesRequest,
        progress_callback: ProgressCallback | None = None,
        *,
        progress_snapshot_callback: StructuredProgressCallback | None = None,
) -> OperationSummary:
    """Copy or move the selected photo sets into tag-named folders."""
    source_folder = current_folder.expanduser().resolve()
    if not source_folder.is_dir():
        raise FileNotFoundError(f'{source_folder} is not a directory')

    output_parent = options.output_parent.expanduser().resolve()
    if output_parent.exists() and not output_parent.is_dir():
        raise OperationError(output_parent, 'Output parent is not a directory')

    reporter = ProgressReporter(
        'Organizing photos',
        (
            ProgressStageDefinition('prepare', 'Preparing photo organization'),
            ProgressStageDefinition('organize', 'Organizing photo files'),
        ),
        progress_callback=progress_callback,
        snapshot_callback=progress_snapshot_callback,
    )
    reporter.start_stage('prepare', overall_progress=5)

    jobs = _build_jobs(source_folder, photos, options)
    if options.conflict_policy == 'fail':
        _preflight_conflicts(jobs)

    undo_plan = UndoPlan()
    copied_files = 0
    moved_files = 0
    skipped_photos = 0
    skipped_paths: list[str] = []
    total_jobs = len(jobs)
    organize_progress = reporter.counted_stage(
        'organize',
        label='Organizing photo files',
        total=total_jobs,
        start_progress=5,
        end_progress=99,
        zero_progress=99,
    )
    try:
        if total_jobs == 0:
            # No organization jobs means no filesystem loop will report
            # progress. Complete the work stage with a zero total so the UI
            # renders a status-only row for this no-op operation.
            organize_progress.update(0)

        for index, job in enumerate(jobs, start=1):
            conflicts = [
                destination
                for destination in job.destinations
                if destination.exists()
            ]
            if options.conflict_policy == 'skip' and conflicts:
                skipped_photos += 1
                skipped_paths.extend(str(path) for path in conflicts)
            else:
                for source, destination in zip(
                    job.sources, job.destinations, strict=True
                ):
                    ensure_directory(destination.parent, undo_plan)
                    if (
                        options.conflict_policy == 'overwrite'
                        and destination.exists()
                    ):
                        backup_existing_file(destination, undo_plan)
                        destination.unlink()

                    if options.action == 'copy':
                        shutil.copy2(source, destination)
                        copied_files += 1
                        undo_plan.entries.append(CreatedFileUndo(destination))
                    else:
                        shutil.move(source, destination)
                        moved_files += 1
                        undo_plan.entries.append(
                            MovedFileUndo(
                                source=source, destination=destination
                            )
                        )

            organize_progress.update(index)
    except Exception:
        undo_operation(undo_plan)
        raise

    reporter.finish('Photo organization complete', 100)

    return OperationSummary(
        processed_photos=len(jobs),
        copied_files=copied_files,
        moved_files=moved_files,
        skipped_photos=skipped_photos,
        skipped_paths=tuple(skipped_paths),
        undo_plan=undo_plan,
    )


@dataclass(slots=True, frozen=True)
class _OrganizeJob:
    sources: tuple[Path, ...]
    destinations: tuple[Path, ...]


def _build_jobs(
        current_folder: Path,
        photos: list[PhotoRecord],
        options: OrganizeFilesRequest,
) -> list[_OrganizeJob]:
    jobs: list[_OrganizeJob] = []
    for photo in photos:
        folder_name = _target_folder_name(photo, options)
        if folder_name is None:
            continue

        sources = list(_source_paths_for_photo(current_folder, photo, options))
        destinations = tuple(
            options.output_parent.expanduser().resolve()
            / folder_name
            / _relative_output_path(current_folder, path)
            for path in sources
        )
        jobs.append(
            _OrganizeJob(sources=tuple(sources), destinations=destinations)
        )

    return jobs


def _source_paths_for_photo(
        current_folder: Path,
        photo: PhotoRecord,
        options: OrganizeFilesRequest,
) -> tuple[Path, ...]:
    sources: list[Path] = []
    for name in photo.files:
        source = resolve_relative_path(current_folder, name)
        if not source.exists():
            raise OperationError(source, 'Source file does not exist')

        sources.append(source)

    if options.include_sidecars:
        sidecar_path = sidecar_path_for_photo(current_folder, photo)
        if sidecar_path.exists():
            sources.append(sidecar_path)

    return tuple(sources)


def _relative_output_path(current_folder: Path, source: Path) -> Path:
    """
    Return the source path to preserve under an output bucket.

    Parameters
    ----------
    current_folder : Path
        Loaded photo folder that owns ``source``.
    source : Path
        Source file or sidecar path to place under the organizer output folder.

    Returns
    -------
    Path
        Folder-relative output path with platform-native separators.

    Raises
    ------
    OperationError
        If ``source`` is outside ``current_folder`` or cannot be normalized
        into a safe folder-relative path.
    """
    try:
        relative_path = source.relative_to(current_folder).as_posix()
    except ValueError as exc:
        raise OperationError(
            source, 'Source is outside the current folder'
        ) from exc

    # Preserve the source subfolder layout inside each tag bucket. This avoids
    # filename collisions when recursive loading finds the same stem in
    # multiple subfolders.
    normalized = normalize_relative_file_path(relative_path)
    if normalized is None:
        raise OperationError(source, 'Source path is not folder-relative')

    return Path(*normalized.split('/'))


def _preflight_conflicts(jobs: list[_OrganizeJob]) -> None:
    for job in jobs:
        for destination in job.destinations:
            if destination.exists():
                raise OperationError(destination, 'Destination already exists')


def _target_folder_name(
        photo: PhotoRecord,
        options: OrganizeFilesRequest,
) -> str | None:
    # New flag requests already chose an exact folder mode in the dialog. Route
    # them before legacy compatibility so they never appear to honor
    # metadata-only untagged settings.
    if isinstance(options, FlagOrganizeFilesOptions):
        return _target_flag_folder_name(photo, options.flag_folder_mode)

    if (
        isinstance(options, OrganizeFilesOptions)
        and options.criterion == 'flag'
    ):
        # Old callers only had ``include_untagged`` for flag organization.
        # Translate it to matching modern modes so direct API users keep the
        # pre-split behavior while sharing the current flag routing helper.
        legacy_mode: FlagFolderMode = (
            'picked_rejected_untagged'
            if options.include_untagged
            else 'picked_rejected'
        )
        return _target_flag_folder_name(photo, legacy_mode)

    if options.criterion == 'color_label':
        if photo.color_label is not None:
            return photo.color_label.title()

    elif options.criterion == 'rating':
        if photo.rating is not None:
            suffix = 'Star' if photo.rating == 1 else 'Stars'
            return f'{photo.rating} {suffix}'

    else:
        raise ValueError(f'Unknown organize criterion: {options.criterion}')

    if options.include_untagged:
        return 'Untagged'

    return None


def _target_flag_folder_name(
        photo: PhotoRecord,
        flag_folder_mode: FlagFolderMode,
) -> str | None:
    if flag_folder_mode == 'picked_rejected_untagged':
        if photo.flag == 'picked':
            return 'Picked'

        if photo.flag == 'rejected':
            return 'Rejected'

        return 'Untagged'

    if flag_folder_mode == 'picked_rejected':
        if photo.flag == 'picked':
            return 'Picked'

        if photo.flag == 'rejected':
            return 'Rejected'

        return None

    if flag_folder_mode == 'picked_others':
        return 'Picked' if photo.flag == 'picked' else 'Others'

    if flag_folder_mode == 'rejected_others':
        return 'Rejected' if photo.flag == 'rejected' else 'Others'

    if flag_folder_mode == 'picked_only':
        return 'Picked' if photo.flag == 'picked' else None

    if flag_folder_mode == 'rejected_only':
        return 'Rejected' if photo.flag == 'rejected' else None

    raise ValueError(f'Unknown flag folder mode: {flag_folder_mode}')
