"""Core data records and shared constants for easy-photo-culling."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

JPEG_EXTENSIONS = {'.jpg', '.jpeg'}
RAW_EXTENSIONS = {'.cr3', '.nef'}
SUPPORTED_EXTENSIONS = JPEG_EXTENSIONS | RAW_EXTENSIONS
METADATA_FILENAME = 'easy-photo-culling.json'
COLOR_LABELS = {'red', 'yellow', 'green', 'blue', 'purple'}

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
    capture_at: datetime | None = None
    rating: int | None = None
    color_label: str | None = None
    flag: str | None = None
    scene_id: str | None = None
    image_width: int | None = None
    image_height: int | None = None

    def to_api_dict(self) -> dict[str, Any]:
        """Serialize the photo record to the API response shape."""
        return {
            'photo_id': self.photo_id,
            'display_name': self.display_name,
            'files': self.files,
            'has_jpeg': self.has_jpeg,
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
