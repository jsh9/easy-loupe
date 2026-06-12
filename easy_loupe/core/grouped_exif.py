"""Grouped-photo EXIF loading and progress accounting."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from easy_loupe.core.recursive_loading import exif_metadata_for_path
from easy_loupe.progress.callbacks import (
    accepted_keyword_arguments,
    accepts_keyword_argument,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from easy_loupe.core.photo_groups import PhotoGroupSources
    from easy_loupe.progress import ProgressReporter

METADATA_PROGRESS_START = 20
METADATA_PROGRESS_END = 35
SMALL_FOLDER_METADATA_PHOTO_LIMIT = 100
LARGE_FOLDER_METADATA_PHOTO_MINIMUM = 500
SMALL_FOLDER_METADATA_BATCH_SIZE = 20
MEDIUM_FOLDER_METADATA_BATCH_SIZE = 50
LARGE_FOLDER_METADATA_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class GroupedExifMetadataResult:
    """Grouped EXIF metadata plus lookup policy for record construction."""

    metadata: dict[str, dict[str, Any]]
    exact_exif_lookup: bool


@dataclass(frozen=True, slots=True)
class _ExifMetadataReadResult:
    """EXIF metadata plus whether the reader explicitly supports batches."""

    metadata: dict[str, dict[str, Any]]
    supports_batch_progress: bool


def read_grouped_exif_metadata(
        read_exif_metadata_fn: Callable[..., dict[str, dict[str, Any]]],
        photo_sources: list[PhotoGroupSources],
        reporter: ProgressReporter,
) -> GroupedExifMetadataResult:
    """
    Read grouped-photo EXIF metadata with primary and fallback sources.

    Grouping happens before ExifTool so JPEG+RAW companions count as one photo
    in progress and normally send only one metadata source. The preview-source
    fallback preserves old record-building behavior without rereading every
    companion file.
    """
    batch_size = metadata_batch_size_for_photo_count(len(photo_sources))
    primary_sources = [sources.metadata_source for sources in photo_sources]
    primary_total_batches = _metadata_batch_count(
        len(primary_sources), batch_size
    )
    if primary_total_batches == 0:
        # No ExifTool batches will run for an empty folder. Record an explicit
        # zero-total completion so structured overlays render this as a
        # status-only row instead of an unknown-total completed bar.
        reporter.update_stage(
            'metadata',
            current=0,
            total=0,
            message='Loading EXIF data, no photos found',
            overall_progress=METADATA_PROGRESS_END,
            complete=True,
        )
        return GroupedExifMetadataResult({}, exact_exif_lookup=False)

    reporter.update_stage(
        'metadata',
        label=_metadata_stage_label(batch_size),
        current=0,
        total=primary_total_batches,
        message=_metadata_progress_message(
            'Loading EXIF data', 0, primary_total_batches, batch_size
        ),
        overall_progress=METADATA_PROGRESS_START,
    )
    primary_updates = 0

    def handle_primary_batch(
            batch_index: int, total_batches: int, batch_size: int
    ) -> None:
        nonlocal primary_updates
        primary_updates = batch_index
        reporter.update_stage(
            'metadata',
            label=_metadata_stage_label(batch_size),
            current=batch_index,
            total=total_batches,
            message=_metadata_progress_message(
                'Loading EXIF data', batch_index, total_batches, batch_size
            ),
            overall_progress=_metadata_overall_progress(
                batch_index, total_batches
            ),
        )

    primary_result = _call_read_exif_metadata(
        read_exif_metadata_fn,
        primary_sources,
        batch_size=batch_size,
        batch_progress_callback=handle_primary_batch,
    )
    exif_map = primary_result.metadata
    # Test doubles and older injected readers may ignore the batch callback.
    # Move the row forward here so the record-building stage never starts
    # while metadata still appears to be at batch zero. Readers that
    # explicitly support batch callbacks are allowed to stop early without
    # showing skipped batches as complete.
    if primary_updates == 0 and not primary_result.supports_batch_progress:
        reporter.update_stage(
            'metadata',
            label=_metadata_stage_label(batch_size),
            current=primary_total_batches,
            total=primary_total_batches,
            message=_metadata_progress_message(
                'Loading EXIF data',
                primary_total_batches,
                primary_total_batches,
                batch_size,
            ),
            overall_progress=METADATA_PROGRESS_END,
        )

    primary_reported_batches = _reported_metadata_batches(
        primary_total_batches,
        primary_updates,
        supports_batch_progress=primary_result.supports_batch_progress,
    )
    # A reported-but-incomplete primary pass means ExifTool stopped after
    # some configured batches. Do not start fallback reads after that tool
    # stop; the extra pass can repeat the failure and make partial progress
    # look like reliable fallback work. Requiring at least one callback keeps
    # kwargs-compatible readers that never report batches on the legacy path.
    primary_stopped_early = (
        primary_result.supports_batch_progress
        and primary_updates > 0
        and primary_reported_batches < primary_total_batches
    )
    if primary_stopped_early:
        reporter.complete_stage(
            'metadata',
            message=_metadata_progress_message(
                'Loading EXIF data',
                primary_reported_batches,
                primary_total_batches,
                batch_size,
            ),
            overall_progress=METADATA_PROGRESS_END,
        )
        return GroupedExifMetadataResult(
            exif_map,
            exact_exif_lookup=_uses_exact_exif_lookup(exif_map, photo_sources),
        )

    # Only reread preview sources for groups whose primary source produced no
    # metadata. This preserves JPEG fallback while avoiding a second ExifTool
    # pass over every JPEG+RAW companion.
    # Production EXIF maps contain resolved path keys; once those are present,
    # basename fallback would be unsafe because recursive folders can contain
    # same-named RAW files in different subfolders. Legacy test doubles may
    # still provide basename-only maps, so keep basename lookup only for that
    # older shape.
    use_exact_primary_lookup = _uses_exact_exif_lookup(exif_map, photo_sources)
    fallback_sources = [
        sources.preview_source
        for sources in photo_sources
        if (
            sources.preview_source != sources.metadata_source
            and not _has_exif_metadata_for_path(
                exif_map,
                sources.metadata_source,
                exact_only=use_exact_primary_lookup,
            )
        )
    ]
    fallback_total_batches = _metadata_batch_count(
        len(fallback_sources), batch_size
    )
    if fallback_total_batches == 0:
        reporter.complete_stage(
            'metadata',
            message=_metadata_progress_message(
                'Loading EXIF data',
                primary_reported_batches,
                primary_total_batches,
                batch_size,
            ),
            overall_progress=METADATA_PROGRESS_END,
        )
        return GroupedExifMetadataResult(
            exif_map,
            exact_exif_lookup=use_exact_primary_lookup,
        )

    combined_total_batches = primary_total_batches + fallback_total_batches
    fallback_updates = 0
    # ExifTool reports a batch only after it finishes. Extend the row before
    # the fallback subprocess starts so the overlay does not look complete
    # while JPEG fallback metadata is still being read.
    reporter.update_stage(
        'metadata',
        label=_metadata_stage_label(batch_size),
        current=primary_reported_batches,
        total=combined_total_batches,
        message=_metadata_progress_message(
            'Loading fallback EXIF data',
            primary_reported_batches,
            combined_total_batches,
            batch_size,
        ),
        overall_progress=_metadata_overall_progress(
            primary_reported_batches, combined_total_batches
        ),
    )

    def handle_fallback_batch(
            batch_index: int, _total_batches: int, batch_size: int
    ) -> None:
        nonlocal fallback_updates
        fallback_updates = batch_index
        combined_index = primary_reported_batches + batch_index
        reporter.update_stage(
            'metadata',
            label=_metadata_stage_label(batch_size),
            current=combined_index,
            total=combined_total_batches,
            message=_metadata_progress_message(
                'Loading fallback EXIF data',
                combined_index,
                combined_total_batches,
                batch_size,
            ),
            overall_progress=_metadata_overall_progress(
                combined_index, combined_total_batches
            ),
        )

    fallback_result = _call_read_exif_metadata(
        read_exif_metadata_fn,
        fallback_sources,
        batch_size=batch_size,
        batch_progress_callback=handle_fallback_batch,
    )
    exif_map.update(fallback_result.metadata)
    if fallback_updates == 0 and not fallback_result.supports_batch_progress:
        reporter.update_stage(
            'metadata',
            label=_metadata_stage_label(batch_size),
            current=combined_total_batches,
            total=combined_total_batches,
            message=_metadata_progress_message(
                'Loading fallback EXIF data',
                combined_total_batches,
                combined_total_batches,
                batch_size,
            ),
            overall_progress=METADATA_PROGRESS_END,
        )

    fallback_reported_batches = _reported_metadata_batches(
        fallback_total_batches,
        fallback_updates,
        supports_batch_progress=fallback_result.supports_batch_progress,
    )
    combined_reported_batches = (
        primary_reported_batches + fallback_reported_batches
    )
    reporter.complete_stage(
        'metadata',
        message=_metadata_progress_message(
            'Loading EXIF data',
            combined_reported_batches,
            combined_total_batches,
            batch_size,
        ),
        overall_progress=METADATA_PROGRESS_END,
    )
    return GroupedExifMetadataResult(
        exif_map,
        exact_exif_lookup=_uses_exact_exif_lookup(exif_map, photo_sources),
    )


def metadata_batch_size_for_photo_count(photo_count: int) -> int:
    """Return the ExifTool batch size for a grouped photo count."""
    if photo_count <= SMALL_FOLDER_METADATA_PHOTO_LIMIT:
        return SMALL_FOLDER_METADATA_BATCH_SIZE

    if photo_count < LARGE_FOLDER_METADATA_PHOTO_MINIMUM:
        return MEDIUM_FOLDER_METADATA_BATCH_SIZE

    return LARGE_FOLDER_METADATA_BATCH_SIZE


def exact_exif_metadata_for_path(
        exif_map: dict[str, dict[str, Any]], path: Path
) -> dict[str, Any]:
    """
    Look up EXIF metadata by path keys without basename compatibility.

    Recursive folder loads can contain duplicate filenames in different
    subfolders. Callers use this when a basename match would make one photo's
    metadata appear to belong to a different same-named companion.
    """
    return (
        exif_map.get(str(path.expanduser().resolve()))
        or exif_map.get(path.as_posix())
        or {}
    )


def _call_read_exif_metadata(
        read_exif_metadata_fn: Callable[..., dict[str, dict[str, Any]]],
        files: list[Path],
        *,
        batch_size: int,
        batch_progress_callback: Callable[[int, int, int], None],
) -> _ExifMetadataReadResult:
    """
    Call injected EXIF readers without breaking legacy one-argument readers.

    ``load_folder_state`` is exported and some tests or external callers inject
    simple ``reader(files)`` callables. Production readers accept batch
    arguments, so this adapter preserves the old injection contract while still
    passing progress hooks whenever the callable can receive them.
    """
    kwargs: dict[str, object] = {
        'batch_size': batch_size,
        'batch_progress_callback': batch_progress_callback,
    }
    try:
        signature = inspect.signature(read_exif_metadata_fn)
    except (TypeError, ValueError):
        return _ExifMetadataReadResult(
            read_exif_metadata_fn(files, **kwargs),
            supports_batch_progress=True,
        )

    supported_kwargs = accepted_keyword_arguments(signature, kwargs)
    supports_batch_progress = accepts_keyword_argument(
        signature, 'batch_progress_callback'
    )
    return _ExifMetadataReadResult(
        read_exif_metadata_fn(files, **supported_kwargs),
        supports_batch_progress=supports_batch_progress,
    )


def _metadata_batch_count(item_count: int, batch_size: int) -> int:
    if item_count <= 0:
        return 0

    return ((item_count - 1) // max(1, batch_size)) + 1


def _metadata_overall_progress(current: int, total: int) -> int:
    if total <= 0:
        return METADATA_PROGRESS_END

    progress_span = METADATA_PROGRESS_END - METADATA_PROGRESS_START
    return METADATA_PROGRESS_START + int((current / total) * progress_span)


def _reported_metadata_batches(
        total_batches: int,
        updates_seen: int,
        *,
        supports_batch_progress: bool,
) -> int:
    """
    Return the count that should remain visible for a completed metadata pass.

    Callback-aware EXIF readers report only batches that actually finished. For
    legacy readers with no callbacks, folder loading keeps the previous
    behavior of treating the opaque call as complete so injected test readers
    do not leave metadata stuck at zero.
    """
    if supports_batch_progress or updates_seen > 0:
        return min(updates_seen, total_batches)

    return total_batches


def _metadata_progress_message(
        label: str, current: int, total: int, batch_size: int
) -> str:
    return (
        f'{label}, batch {current} of {total} ({batch_size} photos per batch)'
    )


def _metadata_stage_label(batch_size: int) -> str:
    """Return the metadata row label shown directly above its progress bar."""
    return f'Loading EXIF data ({batch_size} photos per batch)'


def _uses_exact_exif_lookup(
        exif_map: dict[str, dict[str, Any]],
        photo_sources: list[PhotoGroupSources],
) -> bool:
    """
    Return whether the EXIF map contains production-style path metadata.

    When any grouped photo source has exact metadata, basename fallback becomes
    unsafe for all records in this load because recursive folders can contain
    same-named photos. Basename-only injected readers still return ``False``
    here and keep the legacy compatibility path.
    """
    return any(
        exact_exif_metadata_for_path(exif_map, sources.metadata_source)
        or exact_exif_metadata_for_path(exif_map, sources.preview_source)
        for sources in photo_sources
    )


def _has_exif_metadata_for_path(
        exif_map: dict[str, dict[str, Any]],
        path: Path,
        *,
        exact_only: bool,
) -> bool:
    """
    Return whether EXIF metadata exists with the chosen lookup contract.

    ``exact_only`` is enabled for production-style path-keyed maps so fallback
    decisions cannot be influenced by duplicate basenames. It stays disabled
    for legacy injected readers that still return basename-only maps.
    """
    if exact_only:
        return bool(exact_exif_metadata_for_path(exif_map, path))

    return bool(exif_metadata_for_path(exif_map, path))
