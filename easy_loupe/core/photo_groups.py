"""Photo companion grouping helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from easy_loupe.core.records import (
    HEIF_EXTENSIONS,
    JPEG_EXTENSIONS,
    JXL_EXTENSIONS,
    PNG_EXTENSIONS,
    RASTER_EXTENSIONS,
    RAW_EXTENSIONS,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

# Display label and extensions for each supported format family, ordered by
# preview priority. JPEG is the safest raster source; every other raster is
# still preferred over RAW because it avoids the slower RAW render path. PNG
# comes last among rasters because it is usually a graphic or screenshot and
# decodes slowly at photo sizes. Preview selection and EXIF file-size rows in
# both culling and photo-viewer modes classify files only through this table,
# so they cannot disagree about a format.
PHOTO_FORMATS: tuple[tuple[str, set[str]], ...] = (
    ('JPG', JPEG_EXTENSIONS),
    ('HEIF', HEIF_EXTENSIONS),
    ('JXL', JXL_EXTENSIONS),
    ('PNG', PNG_EXTENSIONS),
    ('RAW', RAW_EXTENSIONS),
)


@dataclass(frozen=True, slots=True)
class PhotoGroupSources:
    """Source choices shared by metadata reading and record construction."""

    sorted_group_files: list[Path]
    jpeg_files: list[Path]
    heif_files: list[Path]
    raster_files: list[Path]
    raw_files: list[Path]
    preview_source: Path
    metadata_source: Path


def classify_photo_files(files: Iterable[Path]) -> dict[str, list[Path]]:
    """
    Group supported photo files by their ``PHOTO_FORMATS`` label.

    The result contains every label in ``PHOTO_FORMATS`` order, including empty
    ones, so callers can take the first non-empty format as the
    highest-priority one or render an ordered summary directly. Files keep
    their input order within each label, and unsupported extensions are
    skipped.
    """
    files_by_format: dict[str, list[Path]] = {
        label: [] for label, _ in PHOTO_FORMATS
    }
    for path in files:
        suffix = path.suffix.lower()
        for label, extensions in PHOTO_FORMATS:
            if suffix in extensions:
                files_by_format[label].append(path)
                break

    return files_by_format


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
    files_by_format = classify_photo_files(sorted_group_files)
    raw_files = files_by_format['RAW']

    # Preserve alphabetical file listing within each format, but choose the
    # preview from the first non-empty format in ``PHOTO_FORMATS`` priority.
    preview_source = next(
        files[0] for files in files_by_format.values() if files
    )
    metadata_source = raw_files[0] if raw_files else preview_source
    return PhotoGroupSources(
        sorted_group_files=sorted_group_files,
        jpeg_files=files_by_format['JPG'],
        heif_files=files_by_format['HEIF'],
        raster_files=[
            path
            for path in sorted_group_files
            if path.suffix.lower() in RASTER_EXTENSIONS
        ],
        raw_files=raw_files,
        preview_source=preview_source,
        metadata_source=metadata_source,
    )
