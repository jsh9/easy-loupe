from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import easy_loupe.analysis.scenes as analysis_scenes_module


def test_analysis_scenes_module_exports_detect_scenes() -> None:
    assert hasattr(analysis_scenes_module, 'detect_scenes')


def test_analysis_scenes_detect_scenes_groups_and_assigns_scene_ids() -> None:
    """
    Verify scene grouping plus counted feature progress snapshots.

    This keeps the analysis-level progress contract covered while feature
    extraction and grouping share one orchestration path.
    """
    base_time = datetime(2024, 5, 1, 10, 0, 0, tzinfo=UTC)
    photos = [
        type(
            'Photo',
            (),
            {'photo_id': 'IMG_A', 'capture_at': base_time, 'scene_id': None},
        )(),
        type(
            'Photo',
            (),
            {
                'photo_id': 'IMG_B',
                'capture_at': base_time + timedelta(seconds=3),
                'scene_id': None,
            },
        )(),
        type(
            'Photo',
            (),
            {
                'photo_id': 'IMG_C',
                'capture_at': base_time + timedelta(seconds=90),
                'scene_id': None,
            },
        )(),
    ]
    fake_features = {
        'IMG_A': (FakeHash(0), [1.0, 0.0]),
        'IMG_B': (FakeHash(4), [0.99, 0.01]),
        'IMG_C': (FakeHash(18), [0.1, 0.9]),
    }
    progress_updates: list[tuple[str, int]] = []
    progress_snapshots = []

    scenes = analysis_scenes_module.detect_scenes(
        photos,
        lambda _photo_id, _kind: Path('/tmp/unused.jpg'),
        lambda message, progress: progress_updates.append((message, progress)),
        progress_snapshot_callback=progress_snapshots.append,
        analysis_features_fn=lambda photo: fake_features[photo.photo_id],
    )

    assert [scene.photo_ids for scene in scenes] == [
        ['IMG_A', 'IMG_B'],
        ['IMG_C'],
    ]
    assert photos[0].scene_id == photos[1].scene_id
    assert photos[2].scene_id != photos[1].scene_id
    assert progress_updates[-1] == ('done', 100)
    feature_snapshot = next(
        snapshot
        for snapshot in progress_snapshots
        if snapshot.current_message == 'Extracting preview features, 3 of 3'
    )
    assert feature_snapshot.stages[0].count_text() == '3 of 3'
    assert feature_snapshot.stages[0].status == 'complete'


def test_scene_merge_heuristics_cover_primary_histogram_fallback_and_gap() -> (
    None
):
    base_time = datetime(2024, 5, 1, 10, 0, 0, tzinfo=UTC)
    previous = type('Photo', (), {'photo_id': 'A', 'capture_at': base_time})()
    current = type(
        'Photo',
        (),
        {'photo_id': 'B', 'capture_at': base_time + timedelta(seconds=10)},
    )()
    far_apart = type(
        'Photo',
        (),
        {'photo_id': 'C', 'capture_at': base_time + timedelta(seconds=121)},
    )()
    no_time = type('Photo', (), {'photo_id': 'D', 'capture_at': None})()

    assert analysis_scenes_module._should_merge_scene(
        previous,
        current,
        {
            'A': (FakeHash(0), [1.0, 0.0]),
            'B': (FakeHash(5), [0.5, 0.5]),
        },
    )
    assert analysis_scenes_module._should_merge_scene(
        previous,
        current,
        {
            'A': (FakeHash(12), [1.0, 0.0]),
            'B': (FakeHash(30), [1.0, 0.0]),
        },
    )
    assert analysis_scenes_module._should_merge_scene(
        previous,
        current,
        {
            'A': (FakeHash(0), [1.0, 0.0]),
            'B': (FakeHash(9), [0.96, 0.28]),
        },
    )
    assert not analysis_scenes_module._should_merge_scene(
        previous,
        far_apart,
        {
            'A': (FakeHash(0), [1.0, 0.0]),
            'C': (FakeHash(0), [1.0, 0.0]),
        },
    )
    assert analysis_scenes_module._should_merge_scene(
        no_time,
        current,
        {
            'D': (FakeHash(0), [1.0, 0.0]),
            'B': (FakeHash(4), [0.5, 0.5]),
        },
    )


def test_cosine_similarity_returns_zero_for_zero_vectors() -> None:
    assert (
        analysis_scenes_module._cosine_similarity([0.0, 0.0], [1.0, 2.0])
        == 0.0
    )
    assert (
        analysis_scenes_module._cosine_similarity([1.0, 2.0], [0.0, 0.0])
        == 0.0
    )
    assert (
        analysis_scenes_module._cosine_similarity([0.0, 0.0], [0.0, 0.0])
        == 0.0
    )


class FakeHash:
    def __init__(self, value: int) -> None:
        self.value = value

    def __sub__(self, other: object) -> int:
        if isinstance(other, FakeHash):
            return abs(self.value - other.value)

        return NotImplemented
