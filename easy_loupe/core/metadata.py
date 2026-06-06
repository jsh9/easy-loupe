"""
Metadata persistence, normalization, and validation for EasyLoupe.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from easy_loupe.core.records import (
    COLOR_LABELS,
    MAX_RATING,
    METADATA_FILENAME,
    MIN_RATING,
    PhotoRecord,
    SceneGroup,
)
from easy_loupe.core.recursive_loading import normalize_photo_identifier

if TYPE_CHECKING:
    from pathlib import Path


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

    photos = data.get('photos')
    if not isinstance(photos, dict):
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for key, value in photos.items():
        if not isinstance(value, dict):
            continue

        photo_id = normalize_photo_identifier(key)
        if photo_id is None:
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
            normalized[photo_id] = entry

    return normalized


def normalize_scene_groups(
        data: Any, photo_ids: list[str]
) -> tuple[str | None, list[SceneGroup]]:
    """Normalize persisted scene groups for the current folder contents."""
    if not isinstance(data, dict):
        return None, []

    scenes_payload = data.get('scenes')
    if not isinstance(scenes_payload, dict):
        return None, []

    raw_groups = scenes_payload.get('groups')
    if not isinstance(raw_groups, list):
        return None, []

    source = scenes_payload.get('source')
    scene_source = source if isinstance(source, str) else None
    if not raw_groups:
        return scene_source, []

    valid_photo_ids = set(photo_ids)
    seen: set[str] = set()
    groups: list[list[str]] = []
    had_valid_saved_photo_id = False
    for raw_group in raw_groups:
        if not isinstance(raw_group, list):
            continue

        group_photo_ids: list[str] = []
        for raw_photo_id in raw_group:
            photo_id = normalize_photo_identifier(raw_photo_id)
            if photo_id is None:
                continue

            if photo_id not in valid_photo_ids or photo_id in seen:
                continue

            group_photo_ids.append(photo_id)
            seen.add(photo_id)

        if group_photo_ids:
            had_valid_saved_photo_id = True
            groups.append(group_photo_ids)

    if not had_valid_saved_photo_id:
        return None, []

    groups.extend([photo_id] for photo_id in photo_ids if photo_id not in seen)

    return scene_source, _scene_groups_from_photo_ids(groups)


def serialize_scene_groups(
        scenes: list[SceneGroup],
) -> list[list[str]]:
    """Serialize scene groups without persisting generated scene ids."""
    return [list(scene.photo_ids) for scene in scenes if scene.photo_ids]


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


def serialize_folder_metadata(
        photos: list[PhotoRecord],
        scenes: list[SceneGroup] | None = None,
        scene_source: str | None = None,
) -> dict[str, Any]:
    """Serialize the full folder metadata envelope."""
    payload: dict[str, Any] = {'photos': serialize_metadata_entries(photos)}
    if scenes:
        scene_payload: dict[str, Any] = {
            'groups': serialize_scene_groups(scenes)
        }
        if scene_source is not None:
            scene_payload['source'] = scene_source

        payload['scenes'] = scene_payload

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
    payload = serialize_folder_metadata(photos)
    metadata_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )


def write_folder_metadata(
        folder: Path,
        photos: list[PhotoRecord],
        scenes: list[SceneGroup] | None = None,
        scene_source: str | None = None,
) -> None:
    """Write the folder metadata envelope to disk."""
    metadata_path = folder / METADATA_FILENAME
    payload = serialize_folder_metadata(photos, scenes, scene_source)
    metadata_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )


def _scene_groups_from_photo_ids(
        groups: list[list[str]],
) -> list[SceneGroup]:
    return [
        SceneGroup(scene_id=f'scene-{index:04d}', photo_ids=photo_ids)
        for index, photo_ids in enumerate(groups, start=1)
    ]
