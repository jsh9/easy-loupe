"""Photo companion grouping helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from easy_loupe.core.records import (
    HEIF_EXTENSIONS,
    JPEG_EXTENSIONS,
    RASTER_EXTENSIONS,
    RAW_EXTENSIONS,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class PhotoGroupSources:
    """Source choices shared by metadata reading and record construction."""

    sorted_group_files: list[Path]
    jpeg_files: list[Path]
    heif_files: list[Path]
    raw_files: list[Path]
    preview_source: Path
    metadata_source: Path


def select_photo_group_sources(
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
