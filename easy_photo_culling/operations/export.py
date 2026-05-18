"""Copy or move tagged photo sets into output folders."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from easy_photo_culling.operations.common import (
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

if TYPE_CHECKING:
    from pathlib import Path

    from easy_photo_culling.core.records import PhotoRecord

ProgressCallback = Callable[[str, int], None]
OrganizeCriterion = Literal['flag', 'color_label', 'rating']
OrganizeAction = Literal['copy', 'move']
ConflictPolicy = Literal['fail', 'skip', 'overwrite']


@dataclass(slots=True, frozen=True)
class OrganizeFilesOptions:
    """Options for reorganizing photos into output folders."""

    criterion: OrganizeCriterion
    action: OrganizeAction
    output_parent: Path
    include_untagged: bool
    conflict_policy: ConflictPolicy
    include_sidecars: bool = True


def organize_photos(
        current_folder: Path,
        photos: list[PhotoRecord],
        options: OrganizeFilesOptions,
        progress_callback: ProgressCallback | None = None,
) -> OperationSummary:
    """Copy or move the selected photo sets into tag-named folders."""
    source_folder = current_folder.expanduser().resolve()
    if not source_folder.is_dir():
        raise FileNotFoundError(f'{source_folder} is not a directory')

    output_parent = options.output_parent.expanduser().resolve()
    if output_parent.exists() and not output_parent.is_dir():
        raise OperationError(output_parent, 'Output parent is not a directory')

    if progress_callback:
        progress_callback('Preparing photo organization', 5)

    jobs = _build_jobs(source_folder, photos, options)
    if options.conflict_policy == 'fail':
        _preflight_conflicts(jobs)

    undo_plan = UndoPlan()
    copied_files = 0
    moved_files = 0
    skipped_photos = 0
    skipped_paths: list[str] = []
    total_jobs = max(len(jobs), 1)
    try:
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

            if progress_callback:
                progress = 5 + int((index / total_jobs) * 94)
                progress_callback('Organizing photo files', min(progress, 99))
    except Exception:
        undo_operation(undo_plan)
        raise

    if progress_callback:
        progress_callback('Photo organization complete', 100)

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
        options: OrganizeFilesOptions,
) -> list[_OrganizeJob]:
    jobs: list[_OrganizeJob] = []
    for photo in photos:
        folder_name = _target_folder_name(
            photo,
            options.criterion,
            include_untagged=options.include_untagged,
        )
        if folder_name is None:
            continue

        sources = list(_source_paths_for_photo(current_folder, photo, options))
        destinations = tuple(
            options.output_parent.expanduser().resolve()
            / folder_name
            / path.name
            for path in sources
        )
        jobs.append(
            _OrganizeJob(sources=tuple(sources), destinations=destinations)
        )

    return jobs


def _source_paths_for_photo(
        current_folder: Path,
        photo: PhotoRecord,
        options: OrganizeFilesOptions,
) -> tuple[Path, ...]:
    sources: list[Path] = []
    for name in photo.files:
        source = current_folder / name
        if not source.exists():
            raise OperationError(source, 'Source file does not exist')

        sources.append(source)

    if options.include_sidecars:
        sidecar_path = sidecar_path_for_photo(current_folder, photo)
        if sidecar_path.exists():
            sources.append(sidecar_path)

    return tuple(sources)


def _preflight_conflicts(jobs: list[_OrganizeJob]) -> None:
    for job in jobs:
        for destination in job.destinations:
            if destination.exists():
                raise OperationError(destination, 'Destination already exists')


def _target_folder_name(
        photo: PhotoRecord,
        criterion: OrganizeCriterion,
        *,
        include_untagged: bool,
) -> str | None:
    if criterion == 'flag':
        if photo.flag == 'picked':
            return 'Picked'

        if photo.flag == 'rejected':
            return 'Rejected'
    elif criterion == 'color_label':
        if photo.color_label is not None:
            return photo.color_label.title()
    elif photo.rating is not None:
        suffix = 'Star' if photo.rating == 1 else 'Stars'
        return f'{photo.rating} {suffix}'

    if include_untagged:
        return 'Untagged'

    return None
