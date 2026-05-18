"""Scene-detection orchestration for EasyCull."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, cast

from easy_cull.core.records import (
    SCENE_FALLBACK_HASH_DISTANCE,
    SCENE_FALLBACK_HISTOGRAM_MATCH,
    SCENE_FALLBACK_TIME_GAP_SECONDS,
    SCENE_HISTOGRAM_MATCH,
    SCENE_HISTOGRAM_TIME_GAP_SECONDS,
    SCENE_MAX_TIME_GAP_SECONDS,
    SCENE_PRIMARY_HASH_DISTANCE,
    SCENE_PRIMARY_TIME_GAP_SECONDS,
    PhotoRecord,
    SceneGroup,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

try:
    import imagehash
except ImportError:  # pragma: no cover - handled by dependency installation
    imagehash = cast('Any', None)

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = cast('Any', None)


def detect_scenes(
        photos: list[PhotoRecord],
        get_preview_path_fn: Callable[[str, str], Path],
        progress_callback: Callable[[str, int], None] | None = None,
        *,
        analysis_features_fn: Callable[[PhotoRecord], tuple[Any, list[float]]]
        | None = None,
) -> list[SceneGroup]:
    """Detect scene boundaries across a list of photos."""
    if analysis_features_fn is None:

        def analysis_features_fn(
                photo: PhotoRecord,
        ) -> tuple[Any, list[float]]:
            return _analysis_features(photo, get_preview_path_fn)

    if progress_callback:
        progress_callback('preparing files', 5)

    features: dict[str, tuple[Any, list[float]]] = {}
    total_photos = max(len(photos), 1)
    for index, photo in enumerate(photos, start=1):
        features[photo.photo_id] = analysis_features_fn(photo)
        if progress_callback:
            progress = 5 + int((index / total_photos) * 70)
            progress_callback(
                'extracting previews/features', min(progress, 75)
            )

    scene_groups: list[SceneGroup] = []
    current_scene: SceneGroup | None = None
    previous_photo: PhotoRecord | None = None

    for index, photo in enumerate(photos, start=1):
        if current_scene is None:
            current_scene = SceneGroup(
                scene_id=f'scene-{index:04d}', photo_ids=[photo.photo_id]
            )
            photo.scene_id = current_scene.scene_id
            previous_photo = photo
            if progress_callback:
                progress_callback('grouping scenes', 80)

            continue

        assert previous_photo is not None
        if _should_merge_scene(previous_photo, photo, features):
            current_scene.photo_ids.append(photo.photo_id)
        else:
            scene_groups.append(current_scene)
            current_scene = SceneGroup(
                scene_id=f'scene-{index:04d}', photo_ids=[photo.photo_id]
            )

        photo.scene_id = current_scene.scene_id
        previous_photo = photo
        if progress_callback:
            progress = 80 + int((index / total_photos) * 19)
            progress_callback('grouping scenes', min(progress, 99))

    if current_scene is not None:
        scene_groups.append(current_scene)

    if progress_callback:
        progress_callback('done', 100)

    return scene_groups


def _analysis_features(
        photo: PhotoRecord,
        get_preview_path_fn: Callable[[str, str], Path],
) -> tuple[Any, list[float]]:
    """Compute perceptual hash and colour histogram for a photo."""
    preview_path = get_preview_path_fn(photo.photo_id, 'fit')
    with Image.open(preview_path) as image:
        rgb = image.convert('RGB')
        resized = rgb.resize((96, 96), Image.Resampling.LANCZOS)
        if imagehash is None:
            raise RuntimeError('imagehash is required for scene detection')

        perceptual_hash = imagehash.phash(resized, hash_size=8)
        histogram = resized.histogram()
        bins_per_channel = 16
        combined: list[float] = []
        for channel_start in (0, 256, 512):
            channel = histogram[channel_start : channel_start + 256]
            combined.extend(
                float(
                    sum(channel[bucket : bucket + (256 // bins_per_channel)])
                )
                for bucket in range(0, 256, 256 // bins_per_channel)
            )

        total = sum(combined) or 1.0
        normalized = [value / total for value in combined]
        return perceptual_hash, normalized


def _should_merge_scene(
        previous_photo: PhotoRecord,
        current_photo: PhotoRecord,
        features: dict[str, tuple[Any, list[float]]],
) -> bool:
    """Return True if two adjacent photos belong to the same scene."""
    previous_hash, previous_histogram = features[previous_photo.photo_id]
    current_hash, current_histogram = features[current_photo.photo_id]
    hash_distance = previous_hash - current_hash
    histogram_similarity = _cosine_similarity(
        previous_histogram, current_histogram
    )
    time_gap = _capture_gap_seconds(
        previous_photo.capture_at, current_photo.capture_at
    )

    if time_gap is not None and time_gap > SCENE_MAX_TIME_GAP_SECONDS:
        return False

    if hash_distance <= SCENE_PRIMARY_HASH_DISTANCE and (
        time_gap is None or time_gap <= SCENE_PRIMARY_TIME_GAP_SECONDS
    ):
        return True

    if histogram_similarity >= SCENE_HISTOGRAM_MATCH and (
        time_gap is None or time_gap <= SCENE_HISTOGRAM_TIME_GAP_SECONDS
    ):
        return True

    return bool(
        hash_distance <= SCENE_FALLBACK_HASH_DISTANCE
        and histogram_similarity >= SCENE_FALLBACK_HISTOGRAM_MATCH
        and (time_gap is None or time_gap <= SCENE_FALLBACK_TIME_GAP_SECONDS)
    )


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0

    return numerator / (left_norm * right_norm)


def _capture_gap_seconds(
        previous: datetime | None, current: datetime | None
) -> float | None:
    if previous is None or current is None:
        return None

    return abs((current - previous).total_seconds())
