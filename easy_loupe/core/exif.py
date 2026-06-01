"""EXIF metadata reading and display formatting for EasyLoupe."""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # noqa: S404 - explicit exiftool integration
import sys
from datetime import UTC, datetime
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


def read_exif_metadata(files: list[Path]) -> dict[str, dict[str, Any]]:
    """Read EXIF metadata for a list of files using exiftool."""
    exiftool_path = _resolve_exiftool_path()
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
                **_exiftool_subprocess_kwargs(),
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
    'ISO', 'Focal Length', and 'GPS'.
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
