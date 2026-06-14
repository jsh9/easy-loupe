"""EXIF metadata reading and display formatting for EasyLoupe."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess  # noqa: S404 - explicit exiftool integration
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

from easy_loupe.core.autofocus_points import extract_focus_point
from easy_loupe.core.records import (
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

EXIFTOOL_ENV_VAR = 'EASY_LOUPE_EXIFTOOL'
_BUNDLED_EXIFTOOL_CANDIDATES = (
    Path('easy_loupe/vendor/exiftool/windows/exiftool.exe'),
    Path('easy_loupe/vendor/exiftool/macos/exiftool'),
)
DEFAULT_EXIF_BATCH_SIZE = 150
ExifBatchProgressCallback = Callable[[int, int, int], None]
EXPOSURE_PROGRAM_LABELS = {
    1: 'Manual',
    2: 'Program',
    3: 'Aperture Priority',
    4: 'Shutter Priority',
    5: 'Creative',
    6: 'Action',
    7: 'Portrait',
    8: 'Landscape',
    9: 'Bulb',
}
EXPOSURE_COMPENSATION_KEYS = [
    'ExposureCompensation',
    'ExposureBiasValue',
]
EXPOSURE_COMPENSATION_DENOMINATOR = 3
EXPOSURE_COMPENSATION_TOLERANCE = 0.01


class _ExifToolBatchError(RuntimeError):
    """Recoverable failure while reading one ExifTool batch."""


class _ExifToolLaunchError(RuntimeError):
    """Tool-level ExifTool launch failure that should stop retries."""


def read_exif_metadata(
        files: list[Path],
        *,
        batch_size: int = DEFAULT_EXIF_BATCH_SIZE,
        batch_progress_callback: ExifBatchProgressCallback | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Read EXIF metadata for files using ExifTool.

    ``batch_progress_callback`` is called after each successful batch parse so
    folder loading can advance the UI while still using multi-file ExifTool
    subprocesses instead of one process per photo.
    """
    exiftool_path = _resolve_exiftool_path()
    if not exiftool_path or not files:
        return {}

    records: dict[str, dict[str, Any]] = {}
    batch_size = max(1, batch_size)
    total_batches = _batch_count(len(files), batch_size)
    for start in range(0, len(files), batch_size):
        batch_index = (start // batch_size) + 1
        batch = files[start : start + batch_size]
        batch_records, stop_after_batch = _read_exif_batch_with_recovery(
            exiftool_path, batch
        )
        records.update(batch_records)

        if stop_after_batch:
            break

        # Report the original configured batch after any split recovery
        # finishes. The UI shows top-level batch counts, while recursive
        # retries stay an internal salvage detail. Stopped batches are not
        # reported as complete because later configured batches were skipped.
        if batch_progress_callback is not None:
            batch_progress_callback(batch_index, total_batches, batch_size)

    return records


def _read_exif_batch_with_recovery(
        exiftool_path: str, files: list[Path]
) -> tuple[dict[str, dict[str, Any]], bool]:
    """
    Read one configured batch, splitting recoverable failures.

    A bad file can make ExifTool fail the whole subprocess. Retrying smaller
    chunks isolates that file while preserving metadata for the rest of the
    batch. ``OSError`` means the tool cannot be launched reliably, so callers
    should stop after keeping records parsed before this point.
    """
    try:
        return _read_exif_batch(exiftool_path, files), False
    except _ExifToolLaunchError:
        return {}, True
    except _ExifToolBatchError:
        if len(files) <= 1:
            return {}, False

    midpoint = len(files) // 2
    left_records, left_stop = _read_exif_batch_with_recovery(
        exiftool_path, files[:midpoint]
    )
    if left_stop:
        return left_records, True

    right_records, right_stop = _read_exif_batch_with_recovery(
        exiftool_path, files[midpoint:]
    )
    left_records.update(right_records)
    return left_records, right_stop


def _read_exif_batch(
        exiftool_path: str, files: list[Path]
) -> dict[str, dict[str, Any]]:
    command = [
        exiftool_path,
        '-j',
        '-n',
        '-struct',
        *[str(path) for path in files],
    ]
    try:
        result = subprocess.run(  # noqa: S603 - explicit exiftool argv over local files
            command,
            check=True,
            capture_output=True,
            text=True,
            **_exiftool_subprocess_kwargs(),
        )
    except OSError as exc:
        raise _ExifToolLaunchError from exc
    except subprocess.CalledProcessError as exc:
        raise _ExifToolBatchError from exc

    try:
        batch_records = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise _ExifToolBatchError from exc

    return _metadata_records_by_source(batch_records)


def _metadata_records_by_source(
        batch_records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for record in batch_records:
        source_file = record.get('SourceFile')
        if source_file:
            source_path = Path(source_file)
            # Recursive scans can contain duplicate filenames in different
            # subfolders, so folder loading needs a resolved-path key. Keep
            # the basename key for existing flat-folder tests and callers that
            # stub EXIF maps by filename.
            records[str(source_path.expanduser().resolve())] = record
            records[source_path.name] = record

    return records


def _batch_count(item_count: int, batch_size: int) -> int:
    """Return the number of positive-sized batches needed for item count."""
    if item_count <= 0:
        return 0

    batch_size = max(1, batch_size)
    return ((item_count - 1) // batch_size) + 1


def _exiftool_subprocess_kwargs() -> dict[str, Any]:
    """
    Return platform-specific subprocess options for launching ExifTool.

    EasyLoupe is built as a windowed Qt app on Windows, but ExifTool is a
    separate console executable. Without these flags, Windows may briefly show
    a black terminal window every time the app reads photo metadata. The flags
    below ask Windows to start that helper process without creating or showing
    a console window.

    Non-Windows Python builds do not expose these constants/classes, so this
    helper returns an empty dict there and subprocess.run uses its normal
    behavior.
    """
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', None)
    startupinfo_class = getattr(subprocess, 'STARTUPINFO', None)
    startf_use_show_window = getattr(subprocess, 'STARTF_USESHOWWINDOW', None)
    sw_hide = getattr(subprocess, 'SW_HIDE', None)

    # These names exist only on Windows. If they are missing, there is no
    # Windows console to hide and no extra subprocess options are needed.
    if creationflags is None and startupinfo_class is None:
        return {}

    kwargs: dict[str, Any] = {}
    if creationflags is not None:
        # CREATE_NO_WINDOW is the main fix for console executables launched
        # from a GUI app: create the process without a visible console.
        kwargs['creationflags'] = creationflags

    if (
        startupinfo_class is not None
        and startf_use_show_window is not None
        and sw_hide is not None
    ):
        # STARTUPINFO is a second Windows hint that says "if a window would be
        # shown for this process, start it hidden." It is harmless alongside
        # CREATE_NO_WINDOW and gives us a little more coverage across runtimes.
        startupinfo = startupinfo_class()
        startupinfo.dwFlags |= startf_use_show_window
        startupinfo.wShowWindow = sw_hide
        kwargs['startupinfo'] = startupinfo

    return kwargs


def _resolve_exiftool_path() -> str | None:
    """Return the preferred ExifTool executable path for this environment."""
    env_path = os.environ.get(EXIFTOOL_ENV_VAR)
    if env_path:
        return env_path

    bundled_path = _resolve_bundled_exiftool_path()
    if bundled_path is not None:
        return str(bundled_path)

    return shutil.which('exiftool')


def _resolve_bundled_exiftool_path() -> Path | None:
    """Return the PyInstaller-packaged ExifTool path when present."""
    roots = []
    pyinstaller_root = getattr(sys, '_MEIPASS', None)
    if pyinstaller_root:
        pyinstaller_path = Path(pyinstaller_root)
        roots.extend([
            pyinstaller_path,
            pyinstaller_path.parent / 'Resources',
            pyinstaller_path.parent / 'Frameworks',
        ])

    executable = getattr(sys, 'executable', None)
    if executable:
        executable_dir = Path(executable).resolve().parent
        roots.extend([
            executable_dir,
            executable_dir.parent / 'Resources',
            executable_dir.parent / 'Frameworks',
        ])

    roots.append(Path(__file__).resolve().parents[2])

    for root in roots:
        for candidate in _BUNDLED_EXIFTOOL_CANDIDATES:
            path = root / candidate
            if path.is_file():
                return path

    return None


def format_exif_display(metadata: dict[str, Any]) -> dict[str, str]:
    """
    Return human-readable EXIF fields for the overlay display.

    Returns a dict of label → formatted string for fields that are present.
    Example keys: 'Camera Model', 'Lens Model', 'Aperture', 'Shutter Speed',
    'Shooting Mode', 'Exposure Compensation', 'ISO', 'Focal Length', and 'GPS'.
    """
    result: dict[str, str] = {}

    camera_make = _first_string(metadata, ['Make'])
    if camera_make:
        result['Camera Make'] = camera_make

    camera_model = _first_string(metadata, ['Model', 'CameraModelName'])
    if camera_model:
        result['Camera Model'] = camera_model

    lens_id = _first_string(metadata, ['LensID', 'LensType'])
    if lens_id:
        result['Lens ID'] = lens_id

    lens_make = _first_string(metadata, ['LensMake'])
    if lens_make:
        result['Lens Make'] = lens_make

    lens_model = _first_string(metadata, ['LensModel', 'Lens'])
    if lens_model:
        result['Lens Model'] = lens_model

    focal = _coerce_float(metadata.get('FocalLength'))
    if focal is not None:
        result['Focal Length'] = f'{focal:g}\u00a0mm'

    f_number = _coerce_float(metadata.get('FNumber'))
    if f_number is not None:
        result['Aperture'] = f'\u0192/{f_number:g}'

    exposure = _coerce_float(metadata.get('ExposureTime'))
    if exposure is not None:
        if exposure > 0 and exposure < 1:
            denom = round(1 / exposure)
            result['Shutter Speed'] = f'1/{denom}\u00a0s'
        else:
            result['Shutter Speed'] = f'{exposure:g}\u00a0s'

    shooting_mode = _format_shooting_mode(metadata.get('ExposureProgram'))
    if shooting_mode:
        result['Shooting Mode'] = shooting_mode

    exposure_compensation = _format_exposure_compensation(metadata)
    if exposure_compensation:
        result['Exposure Compensation'] = exposure_compensation

    iso = metadata.get('ISO')
    if iso is not None:
        result['ISO'] = str(iso)

    gps = _format_gps(metadata)
    if gps:
        result['GPS'] = gps

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


def _format_shooting_mode(value: Any) -> str:
    """Return a readable exposure program label for standard EXIF values."""
    program = _coerce_int(value)
    if program is None:
        return ''

    return EXPOSURE_PROGRAM_LABELS.get(program, '')


def _coerce_int(value: Any) -> int | None:
    """Convert an integral scalar value to int when possible."""
    if isinstance(value, int):
        return value

    if isinstance(value, float) and value.is_integer():
        return int(value)

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None

        try:
            numeric = float(text)
        except ValueError:
            return None

        if numeric.is_integer():
            return int(numeric)

    return None


def _format_exposure_compensation(metadata: dict[str, Any]) -> str:
    """Return the first usable exposure compensation as a display string."""
    # Prefer the canonical ExifTool key while keeping ExposureBiasValue as a
    # fallback because cameras can expose the same EV offset under either name.
    for key in EXPOSURE_COMPENSATION_KEYS:
        value = _coerce_rational_float(metadata.get(key))
        if value is not None:
            return _format_signed_third(value)

    return ''


def _coerce_rational_float(value: Any) -> float | None:
    """Convert decimal or simple fractional scalar values to float."""
    if isinstance(value, (int, float)):
        candidate = float(value)
        return candidate if math.isfinite(candidate) else None

    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    try:
        candidate = float(text)
    except ValueError:
        pass
    else:
        return candidate if math.isfinite(candidate) else None

    try:
        candidate = float(Fraction(text))
    except (ValueError, ZeroDivisionError):
        return None

    return candidate if math.isfinite(candidate) else None


def _format_signed_third(value: float) -> str:
    """
    Format an EV offset as camera-style thirds or a signed decimal fallback.

    Cameras usually step exposure compensation in thirds, but EXIF readers can
    return rounded floats, so comparisons use tolerance before falling back to
    raw decimal display.
    """
    if abs(value) < EXPOSURE_COMPENSATION_TOLERANCE:
        return '0'

    sign = '+' if value > 0 else '-'
    absolute = abs(value)
    nearest_whole = round(absolute)
    if abs(absolute - nearest_whole) < EXPOSURE_COMPENSATION_TOLERANCE:
        return f'{sign}{nearest_whole:g}'

    # Limit to thirds to match camera compensation dials; values that do not
    # round-trip within tolerance stay decimal instead of being guessed.
    fraction = Fraction(absolute).limit_denominator(
        EXPOSURE_COMPENSATION_DENOMINATOR
    )
    if abs(float(fraction) - absolute) >= EXPOSURE_COMPENSATION_TOLERANCE:
        return f'{value:+g}'

    whole = fraction.numerator // fraction.denominator
    remainder = fraction.numerator % fraction.denominator
    if whole and remainder:
        return f'{sign}{whole:g} {remainder}/{fraction.denominator}'

    if whole:
        return f'{sign}{whole:g}'

    return f'{sign}{remainder}/{fraction.denominator}'


def _first_string(metadata: dict[str, Any], keys: list[str]) -> str:
    """Return the first non-empty scalar value for the given EXIF keys."""
    for key in keys:
        value = metadata.get(key)
        if value is None:
            continue

        text = str(value).strip()
        if text:
            return text

    return ''


def _format_gps(metadata: dict[str, Any]) -> str:
    latitude = _coerce_float(metadata.get('GPSLatitude'))
    longitude = _coerce_float(metadata.get('GPSLongitude'))
    if latitude is None or longitude is None:
        return ''

    parts = [f'{latitude:.6f}º', f'{longitude:.6f}º']
    altitude = _coerce_float(metadata.get('GPSAltitude'))
    if altitude is not None:
        parts.append(f'{altitude:g}\u00a0m')

    return ', '.join(parts)
