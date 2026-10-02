"""
Metadata persistence, normalization, and validation for EasyLoupe.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from easy_loupe.core.records import (
    COLOR_LABELS,
    FLAGS,
    MAX_RATING,
    METADATA_FILENAME,
    MIN_RATING,
    PhotoRecord,
    SceneGroup,
)
from easy_loupe.core.recursive_loading import (
    build_photo_id_group_index,
    normalize_photo_identifier,
    normalize_photo_identifier_for_valid_ids,
    resolve_photo_identifier_by_group_key,
)
from easy_loupe.core.rotation import (
    NO_ROTATION_DEGREES,
    ROTATION_METADATA_FIELD,
    normalize_rotation,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
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


def normalize_metadata_entries(
        data: Any, *, valid_photo_ids: Iterable[str] | None = None
) -> dict[str, dict[str, Any]]:
    """
    Normalize persisted photo metadata into the current in-memory schema.

    Saved metadata has existed in multiple key shapes over time: current
    extensionless photo IDs, older filename keys with extensions, and Windows
    separator variants. When ``valid_photo_ids`` is provided, keys are resolved
    against the IDs that were actually loaded from the current folder. That
    lets the loader prefer exact IDs such as ``IMG.0001`` before falling back
    to legacy extension stripping for keys such as ``IMG_0001.JPG``. Keys that
    still do not match fall back to a case-insensitive stem match, because a
    photo's ID follows the companion file that wins preview priority and can
    change case when a companion such as ``dsc01234.png`` appears next to
    ``DSC01234.ARW``. Exact and legacy matches always win over that fallback.

    Callers that do not have a loaded photo set can omit ``valid_photo_ids``;
    the function then keeps the historical generic normalization behavior.
    Invalid metadata values are ignored so corrupt or stale entries do not
    prevent the folder from loading.
    """
    if not isinstance(data, dict):
        return {}

    photos = data.get('photos')
    if not isinstance(photos, dict):
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    # Case-only matches are collected separately so an exact or legacy key for
    # the same photo wins regardless of the order keys were saved in.
    case_only_matches: dict[str, dict[str, Any]] = {}
    valid_photo_id_set = (
        set(valid_photo_ids) if valid_photo_ids is not None else None
    )
    photo_id_group_index = build_photo_id_group_index(valid_photo_id_set or ())
    for key, value in photos.items():
        if not isinstance(value, dict):
            continue

        target = normalized
        if valid_photo_id_set is None:
            photo_id = normalize_photo_identifier(key)
        else:
            # Loaded IDs are the only reliable way to tell a current dotted
            # stem such as IMG.0001 from a legacy filename key that needs
            # suffix stripping.
            photo_id = normalize_photo_identifier_for_valid_ids(
                key, valid_photo_id_set
            )
            if photo_id is None:
                photo_id = resolve_photo_identifier_by_group_key(
                    key, photo_id_group_index
                )
                target = case_only_matches

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

        if flag in FLAGS:
            entry['flag'] = flag

        # Rotation 0 is the default display, so only real quarter turns are
        # kept; that keeps an entry with no other data from surviving load.
        rotation = normalize_rotation(value.get(ROTATION_METADATA_FIELD))
        if rotation:
            entry[ROTATION_METADATA_FIELD] = rotation

        if entry:
            target[photo_id] = entry

    return {**case_only_matches, **normalized}


def normalize_scene_groups(
        data: Any, photo_ids: list[str]
) -> tuple[str | None, list[SceneGroup]]:
    """
    Normalize persisted scene groups for the current folder contents.

    Scene groups reference photo IDs directly, so they must be repaired when a
    folder changes or when older metadata used filename-like keys. The
    ``photo_ids`` argument is the authoritative loaded order for this folder:
    it is used to discard missing/stale IDs, deduplicate repeated IDs, repair
    legacy keys, and append any newly discovered photos as singleton scenes.

    Exact loaded IDs are preferred before extension stripping for the same
    reason as per-photo metadata: dotted stems such as ``IMG.0001`` are valid
    current IDs and must not be shortened to ``IMG``. Saved IDs that differ
    from a loaded ID only in stem case fall back to that loaded ID, matching
    :func:`normalize_metadata_entries`.
    """
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
    photo_id_group_index = build_photo_id_group_index(photo_ids)
    seen: set[str] = set()
    groups: list[list[str]] = []
    had_valid_saved_photo_id = False
    for raw_group in raw_groups:
        if not isinstance(raw_group, list):
            continue

        group_photo_ids: list[str] = []
        for raw_photo_id in raw_group:
            # Resolve against the loaded photo set so exact current IDs win
            # over legacy filename stripping, then case-only stem changes.
            photo_id = normalize_photo_identifier_for_valid_ids(
                raw_photo_id, valid_photo_ids
            ) or resolve_photo_identifier_by_group_key(
                raw_photo_id, photo_id_group_index
            )
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

        # Omit the default rotation so unrotated photos keep the historical
        # on-disk shape and clearing every field still removes the entry.
        if photo.rotation != NO_ROTATION_DEGREES:
            entry[ROTATION_METADATA_FIELD] = photo.rotation

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
        rotation: Any = None,
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
        elif flag in FLAGS:
            photo.flag = flag
        else:
            raise ValueError('flag must be null, "picked", or "rejected"')

    if ROTATION_METADATA_FIELD in fields:
        if rotation is None:
            photo.rotation = NO_ROTATION_DEGREES
        else:
            normalized_rotation = normalize_rotation(rotation)
            if normalized_rotation is None:
                raise ValueError('rotation must be null, 0, 90, 180, or 270')

            photo.rotation = normalized_rotation

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
