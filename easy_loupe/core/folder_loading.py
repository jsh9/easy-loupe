"""Folder scanning and photo-record construction for EasyLoupe."""

from __future__ import annotations

import inspect
import operator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import easy_loupe.core.exif as exif_module
import easy_loupe.core.metadata as metadata_module
from easy_loupe.core.records import (
    COLOR_LABELS,
    HEIF_EXTENSIONS,
    JPEG_EXTENSIONS,
    MAX_RATING,
    MIN_RATING,
    RASTER_EXTENSIONS,
    RAW_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    PhotoRecord,
    SceneGroup,
)
from easy_loupe.core.recursive_loading import (
    DEFAULT_LOAD_RECURSIVELY,
    discover_photo_files,
    exif_metadata_for_path,
    relative_photo_group_key,
    relative_photo_id,
    relative_posix_path,
)
from easy_loupe.progress import ProgressReporter, ProgressStageDefinition

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

PHOTO_SORT_MODE_CAPTURE_TIME = 'capture_time'
PHOTO_SORT_MODE_FILENAME = 'filename'
DEFAULT_PHOTO_SORT_MODE = PHOTO_SORT_MODE_CAPTURE_TIME
DEFAULT_PHOTO_SORT_REVERSED = False
PHOTO_SORT_MODES = frozenset({
    PHOTO_SORT_MODE_CAPTURE_TIME,
    PHOTO_SORT_MODE_FILENAME,
})
FOLDER_LOAD_PROGRESS_STAGES = (
    ProgressStageDefinition('scan', 'Scanning folder'),
    ProgressStageDefinition('metadata', 'Loading EXIF data'),
    ProgressStageDefinition('records', 'Building photo list'),
)
METADATA_PROGRESS_START = 20
METADATA_PROGRESS_END = 35
SMALL_FOLDER_METADATA_PHOTO_LIMIT = 100
LARGE_FOLDER_METADATA_PHOTO_MINIMUM = 500
SMALL_FOLDER_METADATA_BATCH_SIZE = 20
MEDIUM_FOLDER_METADATA_BATCH_SIZE = 50
LARGE_FOLDER_METADATA_BATCH_SIZE = 100


@dataclass(slots=True)
class LoadedFolderState:
    """Loaded photo-library state produced from a folder scan."""

    current_folder: Path
    folder_label: str
    photos: list[PhotoRecord]
    photo_map: dict[str, PhotoRecord]
    scenes: list[SceneGroup]
    scene_source: str | None
    scene_detection_done: bool


@dataclass(frozen=True, slots=True)
class PhotoExifDisplay:
    """Formatted EXIF display payload shared by loaders and viewer workers."""

    capture_at: datetime | None
    image_width: int | None
    image_height: int | None
    exif_display: dict[str, str]


@dataclass(frozen=True, slots=True)
class PhotoGroupSources:
    """Source choices shared by metadata reading and record construction."""

    sorted_group_files: list[Path]
    jpeg_files: list[Path]
    heif_files: list[Path]
    raw_files: list[Path]
    preview_source: Path
    metadata_source: Path


@dataclass(frozen=True, slots=True)
class _ExifMetadataReadResult:
    """EXIF metadata plus whether the reader explicitly supports batches."""

    metadata: dict[str, dict[str, Any]]
    supports_batch_progress: bool


def load_folder_state(
        folder: Path,
        *,
        metadata_entries: dict[str, Any] | None = None,
        folder_label: str | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
        progress_reporter: ProgressReporter | None = None,
        sort_mode: str = DEFAULT_PHOTO_SORT_MODE,
        sort_reversed: bool = DEFAULT_PHOTO_SORT_REVERSED,
        load_recursively: bool = DEFAULT_LOAD_RECURSIVELY,
        read_exif_metadata_fn: Callable[..., dict[str, dict[str, Any]]],
) -> LoadedFolderState:
    """
    Scan a folder, build photo records, and load saved folder state.

    Folder scanning owns the transition from filesystem paths to stable
    folder-relative photo IDs. Records are built before saved metadata is
    applied because metadata migration needs the actual loaded IDs to
    distinguish exact dotted stems, such as ``IMG.0001``, from legacy
    filename-style keys that should have their final extension stripped.
    """
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        raise FileNotFoundError(f'{folder} is not a directory')

    reporter = progress_reporter or ProgressReporter(
        'Loading folder',
        FOLDER_LOAD_PROGRESS_STAGES,
        progress_callback=progress_callback,
    )
    reporter.start_stage('scan', overall_progress=5)

    files = discover_photo_files(
        folder,
        SUPPORTED_EXTENSIONS,
        load_recursively=load_recursively,
    )

    groups: dict[tuple[str, str], list[Path]] = {}
    for path in files:
        # Group case-insensitively only within the same exact relative folder.
        # This pairs same-photo JPEG/RAW files without merging case-distinct
        # subfolders on filesystems that allow them.
        groups.setdefault(relative_photo_group_key(folder, path), []).append(
            path
        )

    sorted_groups = sorted(groups.items(), key=operator.itemgetter(0))
    photo_sources = [
        _select_photo_group_sources(grouped_files)
        for _, grouped_files in sorted_groups
    ]
    total_groups = len(sorted_groups)
    reporter.complete_stage(
        'scan',
        message=(f'Discovered {total_groups} photos from {len(files)} files'),
        overall_progress=METADATA_PROGRESS_START,
    )

    if metadata_entries is None:
        metadata_entries = metadata_module.read_folder_metadata(folder)

    exif_map = _read_group_exif_metadata(
        read_exif_metadata_fn,
        photo_sources,
        reporter,
    )
    exact_exif_lookup = _uses_exact_exif_lookup(exif_map, photo_sources)

    records: list[PhotoRecord] = []
    reporter.update_stage(
        'records',
        current=0,
        total=total_groups,
        overall_progress=METADATA_PROGRESS_END,
    )
    for index, (_, grouped_files) in enumerate(sorted_groups, start=1):
        photo = _build_photo_record(
            folder,
            grouped_files,
            exif_map,
            exact_exif_lookup=exact_exif_lookup,
        )
        records.append(photo)
        progress = 35 + int((index / max(total_groups, 1)) * 55)
        reporter.update_stage(
            'records',
            current=index,
            total=total_groups,
            overall_progress=min(progress, 90),
            complete=index == total_groups,
        )

    # Apply metadata after records exist so legacy-key repair can be checked
    # against the concrete IDs discovered in this folder.
    normalized_metadata = metadata_module.normalize_metadata_entries(
        metadata_entries or {},
        valid_photo_ids=[photo.photo_id for photo in records],
    )
    _apply_normalized_metadata(records, normalized_metadata)
    sort_photo_records(records, sort_mode, sort_reversed=sort_reversed)
    photo_map = {photo.photo_id: photo for photo in records}
    scene_source, scenes = metadata_module.normalize_scene_groups(
        metadata_entries or {}, [photo.photo_id for photo in records]
    )
    reorder_scene_groups(scenes, [photo.photo_id for photo in records])
    for scene in scenes:
        for photo_id in scene.photo_ids:
            photo_map[photo_id].scene_id = scene.scene_id

    return LoadedFolderState(
        current_folder=folder,
        folder_label=folder_label or folder.name,
        photos=records,
        photo_map=photo_map,
        scenes=scenes,
        scene_source=scene_source,
        scene_detection_done=bool(scenes),
    )


def metadata_batch_size_for_photo_count(photo_count: int) -> int:
    """Return the ExifTool batch size for a grouped photo count."""
    if photo_count <= SMALL_FOLDER_METADATA_PHOTO_LIMIT:
        return SMALL_FOLDER_METADATA_BATCH_SIZE

    if photo_count < LARGE_FOLDER_METADATA_PHOTO_MINIMUM:
        return MEDIUM_FOLDER_METADATA_BATCH_SIZE

    return LARGE_FOLDER_METADATA_BATCH_SIZE


def _read_group_exif_metadata(
        read_exif_metadata_fn: Callable[..., dict[str, dict[str, Any]]],
        photo_sources: list[PhotoGroupSources],
        reporter: ProgressReporter,
) -> dict[str, dict[str, Any]]:
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
        return {}

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
        return exif_map

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
    fallback_map = fallback_result.metadata
    exif_map.update(fallback_map)
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
    return exif_map


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

    supported_kwargs = _supported_exif_reader_kwargs(signature, kwargs)
    supports_batch_progress = _explicitly_accepts_exif_reader_kwarg(
        signature, 'batch_progress_callback'
    )
    return _ExifMetadataReadResult(
        read_exif_metadata_fn(files, **supported_kwargs),
        supports_batch_progress=supports_batch_progress,
    )


def _supported_exif_reader_kwargs(
        signature: inspect.Signature,
        kwargs: dict[str, object],
) -> dict[str, object]:
    """Return batch kwargs accepted by an injected EXIF reader signature."""
    accepts_var_keyword = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if accepts_var_keyword:
        return kwargs

    return {
        name: value
        for name, value in kwargs.items()
        if (
            name in signature.parameters
            and signature.parameters[name].kind
            in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        )
    }


def _explicitly_accepts_exif_reader_kwarg(
        signature: inspect.Signature, name: str
) -> bool:
    """
    Return whether a reader signature can receive a specific keyword argument.

    ``**kwargs`` readers are treated as accepting batch-progress hooks because
    wrapper functions can forward those hooks without naming them. That keeps
    stopped wrapped readers from being reported as opaque legacy calls whose
    skipped batches look complete.
    """
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            return True

        if parameter.name == name and parameter.kind in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }:
            return True

    return False


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


def _exact_exif_metadata_for_path(
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
        _exact_exif_metadata_for_path(exif_map, sources.metadata_source)
        or _exact_exif_metadata_for_path(exif_map, sources.preview_source)
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
        return bool(_exact_exif_metadata_for_path(exif_map, path))

    return bool(exif_metadata_for_path(exif_map, path))


def load_viewer_folder_state(
        opened_file: Path,
        *,
        allow_folder_scan: bool,
) -> LoadedFolderState:
    """
    Build a fast filename-sorted state for photo-viewer startup.

    Standalone photo-viewer mode is intentionally scoped to the opened file's
    immediate folder so adjacent-file navigation stays predictable and fast. It
    still reuses the shared record builder and delayed metadata application
    path so direct-file startup handles dotted IDs and legacy metadata keys the
    same way as full culling loads.
    """
    opened_file = opened_file.expanduser().resolve()
    if not opened_file.is_file():
        raise FileNotFoundError(f'{opened_file} is not a file')

    if opened_file.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f'{opened_file.name} is not a supported photo file')

    folder = opened_file.parent
    if allow_folder_scan:
        files = sorted(
            [
                path
                for path in folder.iterdir()
                if (
                    path.is_file()
                    and path.suffix.lower() in SUPPORTED_EXTENSIONS
                )
            ],
            key=lambda path: path.name.lower(),
        )
        metadata_entries = metadata_module.read_folder_metadata(folder)
    else:
        files = [opened_file]
        metadata_entries = {}

    groups: dict[str, list[Path]] = {}
    for path in files:
        groups.setdefault(path.stem.lower(), []).append(path)

    records = [
        _build_photo_record(
            folder,
            grouped_files,
            {},
            focus_point_pending=True,
        )
        for _, grouped_files in sorted(
            groups.items(), key=operator.itemgetter(0)
        )
    ]
    # Use the freshly built viewer IDs for metadata repair, matching the
    # culling loader while preserving the viewer's direct-folder scope.
    normalized_metadata = metadata_module.normalize_metadata_entries(
        metadata_entries or {},
        valid_photo_ids=[photo.photo_id for photo in records],
    )
    _apply_normalized_metadata(records, normalized_metadata)
    sort_photo_records(
        records,
        PHOTO_SORT_MODE_FILENAME,
        sort_reversed=DEFAULT_PHOTO_SORT_REVERSED,
    )
    return LoadedFolderState(
        current_folder=folder,
        folder_label=folder.name,
        photos=records,
        photo_map={photo.photo_id: photo for photo in records},
        scenes=[],
        scene_source=None,
        scene_detection_done=False,
    )


def _build_photo_record(
        folder: Path,
        grouped_files: list[Path],
        exif_map: dict[str, dict[str, Any]],
        *,
        focus_point_pending: bool = False,
        exact_exif_lookup: bool = False,
) -> PhotoRecord:
    sources = _select_photo_group_sources(grouped_files)
    sorted_group_files = sources.sorted_group_files
    jpeg_files = sources.jpeg_files
    heif_files = sources.heif_files
    raw_files = sources.raw_files
    preview_source = sources.preview_source
    metadata_source = sources.metadata_source

    shared_stem = relative_photo_id(folder, preview_source)
    exact_source_metadata = _exact_exif_metadata_for_path(
        exif_map, metadata_source
    ) or _exact_exif_metadata_for_path(exif_map, preview_source)
    if exact_exif_lookup:
        # Path-keyed maps come from production EXIF reads. In that shape,
        # basename fallback can borrow EXIF from a same-named sibling folder,
        # so missing exact metadata must stay missing for this record.
        source_metadata = exact_source_metadata
    else:
        # Basename-only maps are still supported for legacy injected readers.
        source_metadata = (
            exact_source_metadata
            or exif_metadata_for_path(exif_map, metadata_source)
            or exif_metadata_for_path(exif_map, preview_source)
        )

    source_metadata = source_metadata or {}
    exif_display = build_photo_exif_display(
        source_metadata,
        jpeg_files=jpeg_files,
        heif_files=heif_files,
        raw_files=raw_files,
    )
    focus_point = exif_module.extract_focus_point(
        source_metadata, exif_display.image_width, exif_display.image_height
    )

    return PhotoRecord(
        photo_id=shared_stem,
        display_name=shared_stem,
        files=[
            relative_posix_path(folder, path) for path in sorted_group_files
        ],
        has_jpeg=bool(jpeg_files),
        has_raw=bool(raw_files),
        preview_source=preview_source,
        metadata_source=metadata_source,
        focus_point=focus_point,
        has_heif=bool(heif_files),
        has_raster=bool(jpeg_files or heif_files),
        focus_point_pending=focus_point_pending,
        capture_at=exif_display.capture_at,
        scene_id=None,
        image_width=exif_display.image_width,
        image_height=exif_display.image_height,
        exif_display=exif_display.exif_display,
    )


def _select_photo_group_sources(
        grouped_files: list[Path],
) -> PhotoGroupSources:
    """
    Return preview and metadata sources for one grouped photo.

    Folder loading reads one primary EXIF source per grouped photo before it
    builds records. Keeping source choice in this helper prevents that faster
    metadata pass from drifting away from the final ``PhotoRecord`` fields.
    """
    sorted_group_files = sorted(
        grouped_files, key=lambda path: path.name.lower()
    )
    raster_files = [
        path
        for path in sorted_group_files
        if path.suffix.lower() in RASTER_EXTENSIONS
    ]
    jpeg_files = [
        path for path in raster_files if path.suffix.lower() in JPEG_EXTENSIONS
    ]
    heif_files = [
        path for path in raster_files if path.suffix.lower() in HEIF_EXTENSIONS
    ]
    raw_files = [
        path
        for path in sorted_group_files
        if path.suffix.lower() in RAW_EXTENSIONS
    ]

    # Preserve alphabetical file listing, but choose previews by format
    # priority. JPEG is the safest raster source; HEIF is still preferred over
    # RAW because it avoids the slower RAW render path.
    if jpeg_files:
        preview_source = jpeg_files[0]
    elif heif_files:
        preview_source = heif_files[0]
    else:
        preview_source = raw_files[0]

    metadata_source = raw_files[0] if raw_files else preview_source
    return PhotoGroupSources(
        sorted_group_files=sorted_group_files,
        jpeg_files=jpeg_files,
        heif_files=heif_files,
        raw_files=raw_files,
        preview_source=preview_source,
        metadata_source=metadata_source,
    )


def _apply_normalized_metadata(
        records: list[PhotoRecord],
        normalized_metadata: dict[str, dict[str, Any]],
) -> None:
    """
    Apply already-normalized saved metadata to loaded photo records.

    ``normalize_metadata_entries`` performs key migration and value filtering,
    while this helper mutates the freshly built records. Keeping the mutation
    here lets record construction stay focused on filesystem and EXIF data, and
    makes the metadata migration order explicit in ``load_folder_state`` and
    ``load_viewer_folder_state``.
    """
    for photo in records:
        existing_metadata = normalized_metadata.get(photo.photo_id, {})
        rating = existing_metadata.get('rating')
        color_label = existing_metadata.get('color_label')
        flag = existing_metadata.get('flag')
        photo.rating = (
            rating
            if isinstance(rating, int) and MIN_RATING <= rating <= MAX_RATING
            else None
        )
        photo.color_label = (
            color_label if color_label in COLOR_LABELS else None
        )
        photo.flag = flag if flag in {'picked', 'rejected'} else None


def build_photo_exif_display(
        source_metadata: dict[str, Any],
        *,
        jpeg_files: list[Path],
        heif_files: list[Path] | None = None,
        raw_files: list[Path],
) -> PhotoExifDisplay:
    """Build culling-compatible formatted EXIF rows for one photo group."""
    image_width, image_height = exif_module.resolve_image_size(source_metadata)
    capture_at = exif_module.parse_capture_time(source_metadata)
    exif_display: dict[str, str] = {}
    _add_capture_time_display(exif_display, capture_at)
    exif_display.update(exif_module.format_exif_display(source_metadata))
    _add_resolution_display(exif_display, image_width, image_height)
    _add_file_size_display(
        exif_display,
        jpeg_files,
        heif_files or [],
        raw_files,
    )
    return PhotoExifDisplay(
        capture_at=capture_at,
        image_width=image_width,
        image_height=image_height,
        exif_display=exif_display,
    )


def _add_capture_time_display(
        exif_display: dict[str, str],
        capture_at: datetime | None,
) -> None:
    if capture_at is None:
        return

    capture_time = capture_at.strftime('%Y-%m-%d, %I:%M:%S %p')
    exif_display['Captured'] = capture_time.replace(', 0', ', ', 1)


def _add_resolution_display(
        exif_display: dict[str, str],
        image_width: int | None,
        image_height: int | None,
) -> None:
    if image_width is None or image_height is None:
        return

    megapixels = (image_width * image_height) / 1_000_000
    exif_display['Resolution'] = (
        f'{image_width} x {image_height} pixels ({megapixels:.1f} MP)'
    )


def _add_file_size_display(
        exif_display: dict[str, str],
        jpeg_files: list[Path],
        heif_files: list[Path],
        raw_files: list[Path],
) -> None:
    parts: list[str] = []
    jpeg_size = sum(path.stat().st_size for path in jpeg_files)
    heif_size = sum(path.stat().st_size for path in heif_files)
    raw_size = sum(path.stat().st_size for path in raw_files)
    if jpeg_size:
        parts.append(f'JPG: {_format_file_size(jpeg_size)}')

    if heif_size:
        parts.append(f'HEIF: {_format_file_size(heif_size)}')

    if raw_size:
        parts.append(f'RAW: {_format_file_size(raw_size)}')

    if parts:
        exif_display['File Size'] = ', '.join(parts)


def _format_file_size(size_bytes: int) -> str:
    one_mb = 1024 * 1024
    if size_bytes >= one_mb:
        return f'{size_bytes / one_mb:.1f} MB'

    size_kb = max(1, round(size_bytes / 1024))
    return f'{size_kb} KB'


def normalize_sort_mode(sort_mode: object) -> str:
    """Return a supported photo sort mode, falling back to the default."""
    if sort_mode in PHOTO_SORT_MODES:
        return str(sort_mode)

    return DEFAULT_PHOTO_SORT_MODE


def normalize_sort_reversed(sort_reversed: object) -> bool:
    """Return a supported photo sort direction, falling back to ascending."""
    if isinstance(sort_reversed, bool):
        return sort_reversed

    if isinstance(sort_reversed, str):
        normalized = sort_reversed.strip().casefold()
        if normalized in {'1', 'true', 'yes', 'on'}:
            return True

        if normalized in {'0', 'false', 'no', 'off', ''}:
            return DEFAULT_PHOTO_SORT_REVERSED

    return DEFAULT_PHOTO_SORT_REVERSED


def sort_photo_records(
        records: list[PhotoRecord],
        sort_mode: object,
        *,
        sort_reversed: object = DEFAULT_PHOTO_SORT_REVERSED,
) -> None:
    """Sort photo records in place according to a supported sort mode."""
    normalized_sort_mode = normalize_sort_mode(sort_mode)
    reverse = normalize_sort_reversed(sort_reversed)
    if normalized_sort_mode == PHOTO_SORT_MODE_FILENAME:
        records.sort(
            key=lambda photo: (
                photo.display_name.casefold(),
                photo.display_name,
            ),
            reverse=reverse,
        )
        return

    timed_records = [
        photo for photo in records if photo.capture_at is not None
    ]
    untimed_records = [photo for photo in records if photo.capture_at is None]

    def capture_sort_key(photo: PhotoRecord) -> tuple[datetime, str, str]:
        assert photo.capture_at is not None
        return (
            photo.capture_at,
            photo.display_name.casefold(),
            photo.display_name,
        )

    # Unknown capture times stay after dated photos in both directions so the
    # reverse toggle means newest-first, not "unknowns first".
    timed_records.sort(
        key=capture_sort_key,
        reverse=reverse,
    )
    untimed_records.sort(
        key=lambda photo: (
            photo.display_name.casefold(),
            photo.display_name,
        ),
        reverse=reverse,
    )
    records[:] = [*timed_records, *untimed_records]


def reorder_scene_groups(
        scenes: list[SceneGroup], ordered_photo_ids: list[str]
) -> None:
    """Order existing scene groups to match the active photo order."""
    photo_position = {
        photo_id: index for index, photo_id in enumerate(ordered_photo_ids)
    }
    for scene in scenes:
        # Sort each scene's contents by the active photo order so its cover
        # photo and horizontal scene strip match the user's current sort mode.
        scene.photo_ids.sort(
            key=lambda photo_id: photo_position.get(
                photo_id, len(photo_position)
            )
        )

    # Scene groups keep their membership across sort changes, but their rows
    # must follow the earliest photo they contain in the active order.
    scenes.sort(
        key=lambda scene: min(
            photo_position.get(photo_id, len(photo_position))
            for photo_id in scene.photo_ids
        )
    )
    for index, scene in enumerate(scenes, start=1):
        # Scene ids are positional labels in this app, so rebuild them after
        # reordering groups to keep photo.scene_id references consistent.
        scene.scene_id = f'scene-{index:04d}'
