from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

import easy_loupe.core.grouped_exif as grouped_exif_module
from easy_loupe.core.photo_groups import select_photo_group_sources
from easy_loupe.progress import ProgressReporter, ProgressStageDefinition
from tests.core._helpers import create_jpeg

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ('photo_count', 'expected_batch_size'),
    [
        pytest.param(0, 20, id='empty-folder'),
        pytest.param(1, 20, id='single-photo'),
        pytest.param(100, 20, id='small-upper-bound'),
        pytest.param(101, 50, id='medium-lower-bound'),
        pytest.param(499, 50, id='medium-upper-bound'),
        pytest.param(500, 100, id='large-lower-bound'),
        pytest.param(3651, 100, id='large-folder'),
    ],
)
def test_metadata_batch_size_uses_grouped_photo_thresholds(
        photo_count: int, expected_batch_size: int
) -> None:
    """
    Verify metadata batch sizes are based on grouped photo counts.

    This protects the user-visible progress cadence where JPEG+RAW companions
    count as one photo, and the threshold edges are easy to regress.
    """
    assert (
        grouped_exif_module.metadata_batch_size_for_photo_count(photo_count)
        == expected_batch_size
    )


def test_grouped_exif_fallback_progress_combines_batch_counts(
        tmp_path: Path,
) -> None:
    """
    Verify grouped EXIF fallback extends the single metadata progress row.

    Primary RAW reads and fallback JPEG reads are two ExifTool passes, but the
    UI presents them as one metadata stage. This pins the extracted grouped
    EXIF API without needing full folder record construction.
    """
    photo_sources = []
    for index in range(21):
        raw_path = tmp_path / f'IMG_{index:04d}.CR3'
        jpeg_path = tmp_path / f'IMG_{index:04d}.JPG'
        raw_path.write_bytes(b'raw')
        create_jpeg(jpeg_path, 'white')
        photo_sources.append(select_photo_group_sources([raw_path, jpeg_path]))

    calls: list[list[str]] = []
    progress_snapshots = []
    reporter = ProgressReporter(
        'Loading folder',
        (ProgressStageDefinition('metadata', 'Loading EXIF data'),),
        snapshot_callback=progress_snapshots.append,
    )

    def fake_read_exif_metadata(
            files: list[Path],
            *,
            batch_size: int,
            batch_progress_callback: Any,
    ) -> dict[str, dict[str, Any]]:
        calls.append([path.name for path in files])
        assert batch_size == 20
        for batch_index in (1, 2):
            batch_progress_callback(batch_index, 2, batch_size)

        if all(path.suffix.lower() == '.cr3' for path in files):
            return {}

        return {str(path.resolve()): {'Model': 'fallback'} for path in files}

    result = grouped_exif_module.read_grouped_exif_metadata(
        fake_read_exif_metadata,
        photo_sources,
        reporter,
    )

    assert calls == [
        [f'IMG_{index:04d}.CR3' for index in range(21)],
        [f'IMG_{index:04d}.JPG' for index in range(21)],
    ]
    metadata_messages = [
        snapshot.current_message
        for snapshot in progress_snapshots
        if 'EXIF data' in snapshot.current_message
    ]
    metadata_stage = progress_snapshots[-1].stages[0]
    assert result.exact_exif_lookup is True
    assert (
        'Loading fallback EXIF data, batch 3 of 4 (20 photos per batch)'
        in metadata_messages
    )
    assert metadata_stage.status == 'complete'
    assert metadata_stage.count_text() == '4 of 4'
