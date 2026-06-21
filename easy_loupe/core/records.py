"""Core data records and shared constants for EasyLoupe."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

JPEG_EXTENSIONS = {'.jpg', '.jpeg'}
HEIF_EXTENSIONS = {'.heic', '.heif'}
RASTER_EXTENSIONS = JPEG_EXTENSIONS | HEIF_EXTENSIONS
RAW_EXTENSIONS = {
    '.3fr',
    '.arw',
    '.cr2',
    '.cr3',
    '.crw',
    '.dcr',
    '.dng',
    '.erf',
    '.fff',
    '.iiq',
    '.kdc',
    '.mef',
    '.mos',
    '.mrw',
    '.nef',
    '.nrw',
    '.orf',
    '.ori',
    '.pef',
    '.ptx',
    '.raf',
    '.raw',
    '.rw2',
    '.rwl',
    '.sr2',
    '.srf',
    '.srw',
    '.x3f',
}
SUPPORTED_EXTENSIONS = RASTER_EXTENSIONS | RAW_EXTENSIONS
METADATA_FILENAME = 'easy-loupe.json'
COLOR_LABEL_ORDER = ('red', 'yellow', 'green', 'blue', 'purple')
COLOR_LABELS = set(COLOR_LABEL_ORDER)
FLAG_ORDER = ('picked', 'rejected')
FLAGS = set(FLAG_ORDER)

THUMB_MAX_SIZE = 256
FIT_MAX_SIZE = 1800
MIN_RATING = 1
MAX_RATING = 5
PAIR_LENGTH = 2
MIN_CAPTURE_TIMESTAMP_CHAR_COUNT = 19
TIMESTAMP_DATE_SEPARATOR_INDEX = 4
DATE_SEPARATOR_REPLACEMENT_COUNT = 2

SCENE_MAX_TIME_GAP_SECONDS = 120
SCENE_PRIMARY_HASH_DISTANCE = 6
SCENE_PRIMARY_TIME_GAP_SECONDS = 45
SCENE_HISTOGRAM_MATCH = 0.985
SCENE_HISTOGRAM_TIME_GAP_SECONDS = 30
SCENE_FALLBACK_HASH_DISTANCE = 10
SCENE_FALLBACK_HISTOGRAM_MATCH = 0.95
SCENE_FALLBACK_TIME_GAP_SECONDS = 15


@dataclass(slots=True)
class PhotoRecord:
    """Loaded photo record with metadata and preview sources."""

    photo_id: str
    display_name: str
    files: list[str]
    has_jpeg: bool
    has_raw: bool
    preview_source: Path
    metadata_source: Path
    focus_point: tuple[float, float]
    has_heif: bool = False
    has_raster: bool = False
    focus_point_pending: bool = False
    capture_at: datetime | None = None
    rating: int | None = None
    color_label: str | None = None
    flag: str | None = None
    scene_id: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    exif_display: dict[str, str] = field(default_factory=dict)

    def to_api_dict(self) -> dict[str, Any]:
        """Serialize the photo record to the API response shape."""
        return {
            'photo_id': self.photo_id,
            'display_name': self.display_name,
            'files': self.files,
            'has_jpeg': self.has_jpeg,
            'has_heif': self.has_heif,
            'has_raster': self.has_raster,
            'has_raw': self.has_raw,
            'rating': self.rating,
            'color_label': self.color_label,
            'flag': self.flag,
            'focus_point': {
                'x': self.focus_point[0],
                'y': self.focus_point[1],
            },
            'scene_id': self.scene_id,
            'image_width': self.image_width,
            'image_height': self.image_height,
            'preview_version': self.preview_version,
        }

    @property
    def preview_version(self) -> str:
        """Return the cache version derived from the preview source mtime."""
        stat = self.preview_source.stat()
        return str(stat.st_mtime_ns)


@dataclass(slots=True)
class SceneGroup:
    """Detected scene group and its ordered photo ids."""

    scene_id: str
    photo_ids: list[str] = field(default_factory=list)

    def to_api_dict(self) -> dict[str, Any]:
        """Serialize the scene group to the API response shape."""
        return {
            'scene_id': self.scene_id,
            'photo_ids': self.photo_ids,
            'count': len(self.photo_ids),
            'cover_photo_id': self.photo_ids[0] if self.photo_ids else None,
        }
