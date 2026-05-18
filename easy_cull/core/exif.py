"""EXIF metadata reading and display formatting for EasyCull."""

from __future__ import annotations

import json
import shutil
import subprocess  # noqa: S404 - explicit exiftool integration
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from easy_cull.core.autofocus_points import extract_focus_point
from easy_cull.core.records import (
    DATE_SEPARATOR_REPLACEMENT_COUNT,
    MIN_CAPTURE_TIMESTAMP_CHAR_COUNT,
    TIMESTAMP_DATE_SEPARATOR_INDEX,
)

__all__ = [
    'extract_focus_point',
    'format_exif_display',
    'parse_capture_time',
    'read_exif_metadata',
    'resolve_image_size',
]


def read_exif_metadata(files: list[Path]) -> dict[str, dict[str, Any]]:
    """Read EXIF metadata for a list of files using exiftool."""
    exiftool_path = shutil.which('exiftool')
    if not exiftool_path or not files:
        return {}

    records: dict[str, dict[str, Any]] = {}
    batch_size = 150
    for start in range(0, len(files), batch_size):
        batch = files[start : start + batch_size]
        command = [
            exiftool_path,
            '-j',
            '-n',
            '-struct',
            *[str(path) for path in batch],
        ]
        try:
            result = subprocess.run(  # noqa: S603 - explicit exiftool argv over local files
                command,
                check=True,
                capture_output=True,
                text=True,
            )
        except (subprocess.CalledProcessError, OSError):
            return {}

        try:
            batch_records = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {}

        for record in batch_records:
            source_file = record.get('SourceFile')
            if source_file:
                records[Path(source_file).name] = record

    return records


def format_exif_display(metadata: dict[str, Any]) -> dict[str, str]:
    """
    Return human-readable EXIF fields for the overlay display.

    Returns a dict of label → formatted string for fields that are present.
    Example keys: 'Camera', 'Lens', 'Aperture', 'Shutter', 'ISO', 'Focal'.
    """
    result: dict[str, str] = {}

    camera_parts = [
        metadata.get('Make', ''),
        metadata.get('Model', ''),
    ]
    camera = ' '.join(p for p in camera_parts if p).strip()
    if camera:
        result['Camera'] = camera

    lens = metadata.get('LensModel') or metadata.get('Lens')
    if lens:
        result['Lens'] = str(lens)

    f_number = _coerce_float(metadata.get('FNumber'))
    if f_number is not None:
        result['Aperture'] = f'\u0192/{f_number:g}'

    exposure = _coerce_float(metadata.get('ExposureTime'))
    if exposure is not None:
        if exposure > 0 and exposure < 1:
            denom = round(1 / exposure)
            result['Shutter'] = f'1/{denom}\u00a0s'
        else:
            result['Shutter'] = f'{exposure:g}\u00a0s'

    iso = metadata.get('ISO')
    if iso is not None:
        result['ISO'] = str(iso)

    focal = _coerce_float(metadata.get('FocalLength'))
    if focal is not None:
        result['Focal'] = f'{focal:g}\u00a0mm'

    return result


def resolve_image_size(
        metadata: dict[str, Any],
) -> tuple[int | None, int | None]:
    """Return (width, height) from EXIF metadata, or (None, None)."""
    width_keys = [
        'ImageWidth',
        'ExifImageWidth',
        'RawImageWidth',
        'PreviewImageWidth',
    ]
    height_keys = [
        'ImageHeight',
        'ExifImageHeight',
        'RawImageHeight',
        'PreviewImageHeight',
    ]
    width = _first_int(metadata, width_keys)
    height = _first_int(metadata, height_keys)
    return width, height


def parse_capture_time(metadata: dict[str, Any]) -> datetime | None:
    """Parse a capture timestamp from EXIF metadata."""
    keys = [
        'SubSecDateTimeOriginal',
        'DateTimeOriginal',
        'SubSecCreateDate',
        'CreateDate',
    ]
    for key in keys:
        value = metadata.get(key)
        if not isinstance(value, str):
            continue

        candidate = value.strip().replace('T', ' ')
        # fmt: off
        if (
            len(candidate) >= MIN_CAPTURE_TIMESTAMP_CHAR_COUNT
            and candidate[TIMESTAMP_DATE_SEPARATOR_INDEX] in {':', '-'}
        ):
            candidate = candidate.replace(
                '-', ':', DATE_SEPARATOR_REPLACEMENT_COUNT
            )
            try:
                return datetime.strptime(
                    candidate[:MIN_CAPTURE_TIMESTAMP_CHAR_COUNT],
                    '%Y:%m:%d %H:%M:%S',
                ).replace(tzinfo=UTC)
            except ValueError:
                continue
        # fmt: on

    return None


def _first_int(metadata: dict[str, Any], keys: list[str]) -> int | None:
    """
    Return the first integer-like metadata value found for the given keys.
    """
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return int(value)

        if isinstance(value, str) and value.isdigit():
            return int(value)

    return None


def _coerce_float(value: Any) -> float | None:
    """Convert a scalar value to float when possible."""
    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None

    return None
