"""Folder scanning and photo-record construction for EasyCull."""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import easy_cull.core.exif as exif_module
import easy_cull.core.metadata as metadata_module
import easy_cull.core.preview as preview_module
from easy_cull.core.records import (
    COLOR_LABELS,
    JPEG_EXTENSIONS,
    MAX_RATING,
    MIN_RATING,
    RAW_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    PhotoRecord,
    SceneGroup,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@dataclass(slots=True)
class LoadedFolderState:
    """Loaded photo-library state produced from a folder scan."""

    current_folder: Path
    folder_label: str
    photos: list[PhotoRecord]
    photo_map: dict[str, PhotoRecord]
    scenes: list[SceneGroup]
    scene_detection_done: bool


def load_folder_state(
        folder: Path,
        *,
        metadata_entries: dict[str, Any] | None = None,
        folder_label: str | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
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

    records.sort(
        key=lambda photo: (
            preview_module.sort_timestamp(photo.capture_at),
            photo.display_name.lower(),
        )
    )
    photo_map = {photo.photo_id: photo for photo in records}
    return LoadedFolderState(
        current_folder=folder,
        folder_label=folder_label or folder.name,
        photos=records,
        photo_map=photo_map,
        scenes=[],
        scene_detection_done=False,
    )


def _build_photo_record(
        grouped_files: list[Path],
        exif_map: dict[str, dict[str, Any]],
        normalized_metadata: dict[str, dict[str, Any]],
) -> PhotoRecord:
    sorted_group_files = sorted(
        grouped_files, key=lambda path: path.name.lower()
    )
    jpeg_files = [
        path
        for path in sorted_group_files
        if path.suffix.lower() in JPEG_EXTENSIONS
    ]
    raw_files = [
        path
        for path in sorted_group_files
        if path.suffix.lower() in RAW_EXTENSIONS
    ]

    preview_source = jpeg_files[0] if jpeg_files else raw_files[0]
    metadata_source = raw_files[0] if raw_files else preview_source
    shared_stem = preview_source.stem

    source_metadata = (
        exif_map.get(metadata_source.name)
        or exif_map.get(preview_source.name)
        or {}
    )
    image_width, image_height = exif_module.resolve_image_size(source_metadata)
    focus_point = exif_module.extract_focus_point(
        source_metadata, image_width, image_height
    )
    capture_at = exif_module.parse_capture_time(source_metadata)

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
        capture_at=capture_at,
        rating=rating
        if isinstance(rating, int) and MIN_RATING <= rating <= MAX_RATING
        else None,
        color_label=color_label if color_label in COLOR_LABELS else None,
        flag=flag if flag in {'picked', 'rejected'} else None,
        scene_id=None,
        image_width=image_width,
        image_height=image_height,
    )
