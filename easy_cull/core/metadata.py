"""
Metadata persistence, normalization, and validation for EasyCull.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from easy_cull.core.records import (
    COLOR_LABELS,
    MAX_RATING,
    METADATA_FILENAME,
    MIN_RATING,
    PhotoRecord,
)


def read_folder_metadata(folder: Path) -> dict[str, Any]:
    """
    Read and return raw metadata from the folder JSON file, or empty dict.
    """
    metadata_path = folder / METADATA_FILENAME
    if not metadata_path.exists():
        return {}

    try:
        data = json.loads(metadata_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return {}

    if not isinstance(data, dict):
        return {}

    return data


def normalize_metadata_entries(data: Any) -> dict[str, dict[str, Any]]:
    """Normalize persisted metadata into the current in-memory schema."""
    if not isinstance(data, dict):
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for key, value in data.items():
        if not isinstance(value, dict):
            continue

        stem = Path(str(key)).stem
        if not stem:
            continue

        entry: dict[str, Any] = {}
        rating = value.get('rating')
        if isinstance(rating, int) and MIN_RATING <= rating <= MAX_RATING:
            entry['rating'] = rating

        color_label = value.get('color_label')
        if color_label in COLOR_LABELS:
            entry['color_label'] = color_label

        flag = value.get('flag')
        if flag == 'reject':
            flag = 'rejected'

        if flag in {'picked', 'rejected'}:
            entry['flag'] = flag

        if entry:
            normalized[stem] = entry

    return normalized


def serialize_metadata_entries(
        photos: list[PhotoRecord],
) -> dict[str, dict[str, Any]]:
    """Serialize photo metadata to the persisted JSON entry shape."""
    payload: dict[str, dict[str, Any]] = {}
    for photo in photos:
        entry: dict[str, Any] = {}
        if photo.rating is not None:
            entry['rating'] = photo.rating

        if photo.color_label is not None:
            entry['color_label'] = photo.color_label

        if photo.flag is not None:
            entry['flag'] = photo.flag

        if entry:
            payload[photo.photo_id] = entry

    return payload


def validate_and_apply_metadata(
        photo: PhotoRecord,
        *,
        rating: Any = None,
        color_label: Any = None,
        flag: Any = None,
        fields: set[str],
) -> PhotoRecord:
    """Apply validated metadata updates to a photo record in place."""
    if 'rating' in fields:
        if rating is None:
            photo.rating = None
        elif isinstance(rating, int) and MIN_RATING <= rating <= MAX_RATING:
            photo.rating = rating
        else:
            raise ValueError(
                'rating must be null or an integer between 1 and 5'
            )

    if 'color_label' in fields:
        if color_label is None:
            photo.color_label = None
        elif color_label in COLOR_LABELS:
            photo.color_label = color_label
        else:
            raise ValueError(
                'color_label must be null, "red", "yellow",'
                ' "green", "blue", or "purple"'
            )

    if 'flag' in fields:
        if flag is None:
            photo.flag = None
        elif flag == 'reject':
            photo.flag = 'rejected'
        elif flag in {'picked', 'rejected'}:
            photo.flag = flag
        else:
            raise ValueError('flag must be null, "picked", or "rejected"')

    return photo


def write_metadata(folder: Path, photos: list[PhotoRecord]) -> None:
    """Serialize and write photo metadata to the folder JSON file."""
    metadata_path = folder / METADATA_FILENAME
    payload = serialize_metadata_entries(photos)
    metadata_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
