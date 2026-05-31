"""Folder scanning and photo-record construction for EasyCull."""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import easy_cull.core.exif as exif_module
import easy_cull.core.metadata as metadata_module
from easy_cull.core.records import (
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


def load_folder_state(
        folder: Path,
        *,
        metadata_entries: dict[str, Any] | None = None,
        folder_label: str | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
        sort_mode: str = DEFAULT_PHOTO_SORT_MODE,
        sort_reversed: bool = DEFAULT_PHOTO_SORT_REVERSED,
        read_exif_metadata_fn: Callable[
            [list[Path]], dict[str, dict[str, Any]]
        ],
) -> LoadedFolderState:
    """Scan a folder, build photo records, and reset scene state."""
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        raise FileNotFoundError(f'{folder} is not a directory')

    if progress_callback:
        progress_callback('Scanning folder', 5)

    files = sorted(
        [
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ],
        key=lambda path: path.name.lower(),
    )

    groups: dict[str, list[Path]] = {}
    for path in files:
        groups.setdefault(path.stem.lower(), []).append(path)

    if progress_callback:
        progress_callback('Reading metadata', 20)

    if metadata_entries is None:
        metadata_entries = metadata_module.read_folder_metadata(folder)

    normalized_metadata = metadata_module.normalize_metadata_entries(
        metadata_entries or {}
    )
    exif_map = read_exif_metadata_fn(files)

    records: list[PhotoRecord] = []
    sorted_groups = sorted(groups.items(), key=operator.itemgetter(0))
    total_groups = max(len(sorted_groups), 1)
    for index, (_, grouped_files) in enumerate(sorted_groups, start=1):
        photo = _build_photo_record(
            grouped_files, exif_map, normalized_metadata
        )
        records.append(photo)
        if progress_callback:
            progress = 35 + int((index / total_groups) * 55)
            progress_callback('Building photo list', min(progress, 90))

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


def load_viewer_folder_state(
        opened_file: Path,
        *,
        allow_folder_scan: bool,
) -> LoadedFolderState:
    """Build a fast filename-sorted state for photo-viewer startup."""
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

    normalized_metadata = metadata_module.normalize_metadata_entries(
        metadata_entries or {}
    )
    records = [
        _build_photo_record(
            grouped_files,
            {},
            normalized_metadata,
            focus_point_pending=True,
        )
        for _, grouped_files in sorted(
            groups.items(), key=operator.itemgetter(0)
        )
    ]
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
        grouped_files: list[Path],
        exif_map: dict[str, dict[str, Any]],
        normalized_metadata: dict[str, dict[str, Any]],
        *,
        focus_point_pending: bool = False,
) -> PhotoRecord:
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

    preview_source = raster_files[0] if raster_files else raw_files[0]
    metadata_source = raw_files[0] if raw_files else preview_source
    shared_stem = preview_source.stem

    source_metadata = (
        exif_map.get(metadata_source.name)
        or exif_map.get(preview_source.name)
        or {}
    )
    exif_display = build_photo_exif_display(
        source_metadata,
        jpeg_files=jpeg_files,
        heif_files=heif_files,
        raw_files=raw_files,
    )
    focus_point = exif_module.extract_focus_point(
        source_metadata, exif_display.image_width, exif_display.image_height
    )

    existing_metadata = normalized_metadata.get(shared_stem, {})
    rating = existing_metadata.get('rating')
    color_label = existing_metadata.get('color_label')
    flag = existing_metadata.get('flag')

    return PhotoRecord(
        photo_id=shared_stem,
        display_name=shared_stem,
        files=[path.name for path in sorted_group_files],
        has_jpeg=bool(jpeg_files),
        has_raw=bool(raw_files),
        preview_source=preview_source,
        metadata_source=metadata_source,
        focus_point=focus_point,
        has_heif=bool(heif_files),
        has_raster=bool(raster_files),
        focus_point_pending=focus_point_pending,
        capture_at=exif_display.capture_at,
        rating=rating
        if isinstance(rating, int) and MIN_RATING <= rating <= MAX_RATING
        else None,
        color_label=color_label if color_label in COLOR_LABELS else None,
        flag=flag if flag in {'picked', 'rejected'} else None,
        scene_id=None,
        image_width=exif_display.image_width,
        image_height=exif_display.image_height,
        exif_display=exif_display.exif_display,
    )


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
