"""Shared operation helpers for EasyLoupe batch workflows."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from easy_loupe.core.recursive_loading import resolve_relative_path
from easy_loupe.progress import (
    ProgressReporter,
    ProgressStageDefinition,
    StructuredProgressCallback,
)

if TYPE_CHECKING:
    from easy_loupe.core.records import PhotoRecord

ProgressCallback = Callable[[str, int], None]


@dataclass(slots=True, frozen=True)
class CreatedFileUndo:
    """Undo entry for a file created by the operation."""

    path: Path


@dataclass(slots=True, frozen=True)
class RestoredFileUndo:
    """Undo entry for a file whose original contents were backed up."""

    path: Path
    backup_path: Path


@dataclass(slots=True, frozen=True)
class MovedFileUndo:
    """Undo entry for a file moved from source to destination."""

    source: Path
    destination: Path


@dataclass(slots=True, frozen=True)
class CreatedDirectoryUndo:
    """Undo entry for a directory created during the operation."""

    path: Path


UndoEntry = (
    CreatedFileUndo | RestoredFileUndo | MovedFileUndo | CreatedDirectoryUndo
)


@dataclass(slots=True)
class UndoPlan:
    """Reversible filesystem changes recorded during an operation."""

    entries: list[UndoEntry] = field(default_factory=list)
    backup_root: Path | None = None
    consumed: bool = False


@dataclass(slots=True, frozen=True)
class OperationSummary:
    """Summary counts returned from a completed batch operation."""

    processed_photos: int = 0
    copied_files: int = 0
    moved_files: int = 0
    written_sidecars: int = 0
    skipped_photos: int = 0
    skipped_paths: tuple[str, ...] = ()
    undo_plan: UndoPlan | None = None


class OperationError(RuntimeError):
    """Structured failure for a file-operation path and reason."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f'{path}: {reason}')


def sidecar_path_for_photo(current_folder: Path, photo: PhotoRecord) -> Path:
    """Return the shared uppercase XMP sidecar path for a photo stem."""
    return resolve_relative_path(current_folder, f'{photo.photo_id}.XMP')


def ensure_directory(path: Path, undo_plan: UndoPlan | None = None) -> None:
    """Create a directory and record any newly created parents for undo."""
    if path.exists():
        return

    parent = path.parent
    if parent != path:
        ensure_directory(parent, undo_plan)

    path.mkdir()
    if undo_plan is not None:
        undo_plan.entries.append(CreatedDirectoryUndo(path))


def backup_existing_file(path: Path, undo_plan: UndoPlan) -> None:
    """Snapshot an existing file so undo can restore it later."""
    if path.exists() is False:
        return

    backup_root = _ensure_backup_root(undo_plan)
    backup_path = backup_root / f'{len(undo_plan.entries):08d}-{path.name}'
    shutil.copy2(path, backup_path)
    undo_plan.entries.append(
        RestoredFileUndo(path=path, backup_path=backup_path)
    )


def undo_operation(
        undo_plan: UndoPlan | None,
        progress_callback: ProgressCallback | None = None,
        *,
        progress_snapshot_callback: StructuredProgressCallback | None = None,
) -> None:
    """Undo a completed operation by replaying inverse file actions."""
    if undo_plan is None:
        return

    if undo_plan.consumed:
        raise RuntimeError('Undo plan has already been consumed')

    entries = list(reversed(undo_plan.entries))
    total_entries = len(entries)
    reporter = ProgressReporter(
        'Undoing photo organization',
        (ProgressStageDefinition('undo', 'Undoing photo organization'),),
        progress_callback=progress_callback,
        snapshot_callback=progress_snapshot_callback,
    )
    undo_progress = reporter.counted_stage(
        'undo',
        label='Undoing photo organization',
        total=total_entries,
        start_progress=0,
        end_progress=100,
        zero_progress=100,
    )
    try:
        if total_entries == 0:
            undo_progress.update(0)

        for index, entry in enumerate(entries, start=1):
            _undo_entry(entry)
            undo_progress.update(index)
    finally:
        backup_root = undo_plan.backup_root
        if backup_root is not None and backup_root.exists():
            shutil.rmtree(backup_root, ignore_errors=True)

        undo_plan.consumed = True


def _undo_entry(entry: UndoEntry) -> None:
    if isinstance(entry, CreatedFileUndo):
        if entry.path.exists():
            entry.path.unlink()

        return

    if isinstance(entry, RestoredFileUndo):
        ensure_directory(entry.path.parent)
        if entry.path.exists():
            entry.path.unlink()

        shutil.copy2(entry.backup_path, entry.path)
        return

    if isinstance(entry, MovedFileUndo):
        if entry.destination.exists() is False:
            raise OperationError(
                entry.destination, 'Moved file is missing during undo'
            )

        ensure_directory(entry.source.parent)
        shutil.move(entry.destination, entry.source)
        return

    assert isinstance(entry, CreatedDirectoryUndo)
    if entry.path.exists():
        entry.path.rmdir()


def _ensure_backup_root(undo_plan: UndoPlan) -> Path:
    if undo_plan.backup_root is None:
        undo_plan.backup_root = Path(
            tempfile.mkdtemp(prefix='easy-loupe-undo-')
        )

    return undo_plan.backup_root
