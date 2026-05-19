from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Never

import pytest

import easy_cull.core.exif as core_exif_module

if TYPE_CHECKING:
    from pathlib import Path


def test_exif_module_exports_read_exif_metadata() -> None:
    assert hasattr(core_exif_module, 'read_exif_metadata')


def test_exif_module_re_exports_extract_focus_point() -> None:
    metadata = {
        'FocusLocation': {'x': 1600, 'y': 800},
        'ExifImageWidth': '4000',
        'ExifImageHeight': '2000',
    }

    assert core_exif_module.extract_focus_point(
        metadata, 4000, 2000
    ) == pytest.approx((0.4, 0.4))


def test_format_exif_display_returns_human_readable_fields() -> None:
    metadata = {
        'Make': 'NIKON CORPORATION',
        'Model': 'Z 8',
        'LensModel': 'NIKKOR Z 50mm f/1.8 S',
        'FNumber': '2.8',
        'ExposureTime': '0.004',
        'ISO': 800,
        'FocalLength': '50',
    }

    assert core_exif_module.format_exif_display(metadata) == {
        'Camera': 'NIKON CORPORATION Z 8',
        'Lens': 'NIKKOR Z 50mm f/1.8 S',
        'Aperture': '\u0192/2.8',
        'Shutter': '1/250\u00a0s',
        'ISO': '800',
        'Focal': '50\u00a0mm',
    }


def test_format_exif_display_uses_lens_fallback_and_long_exposure() -> None:
    metadata = {
        'Make': 'Canon',
        'Lens': 'RF 24-70mm F2.8L IS USM',
        'ExposureTime': 2,
    }

    assert core_exif_module.format_exif_display(metadata) == {
        'Camera': 'Canon',
        'Lens': 'RF 24-70mm F2.8L IS USM',
        'Shutter': '2\u00a0s',
    }


@pytest.mark.parametrize(
    ('metadata', 'expected'),
    [
        (
            {
                'ImageWidth': 6000,
                'ImageHeight': 4000,
                'ExifImageWidth': 5000,
                'ExifImageHeight': 3000,
            },
            (6000, 4000),
        ),
        (
            {
                'ExifImageWidth': '5000',
                'ExifImageHeight': '3000',
            },
            (5000, 3000),
        ),
        (
            {
                'ImageWidth': 'bad',
                'ImageHeight': None,
                'PreviewImageWidth': 1200.9,
                'PreviewImageHeight': 800.1,
            },
            (1200, 800),
        ),
        ({}, (None, None)),
    ],
)
def test_resolve_image_size_uses_known_dimensions_in_priority_order(
        metadata: dict[str, Any],
        expected: tuple[int | None, int | None],
) -> None:
    assert core_exif_module.resolve_image_size(metadata) == expected


def test_resolve_exiftool_path_uses_environment_override(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(core_exif_module.EXIFTOOL_ENV_VAR, '/custom/exiftool')
    monkeypatch.setattr(
        core_exif_module,
        '_resolve_bundled_exiftool_path',
        lambda: pytest.fail('bundled path should not be checked'),
    )

    assert core_exif_module._resolve_exiftool_path() == '/custom/exiftool'


def test_resolve_exiftool_path_finds_pyinstaller_bundle(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
) -> None:
    bundled_exiftool = (
        tmp_path
        / 'easy_cull'
        / 'vendor'
        / 'exiftool'
        / 'windows'
        / 'exiftool.exe'
    )
    bundled_exiftool.parent.mkdir(parents=True)
    bundled_exiftool.write_text('exiftool')
    monkeypatch.delenv(core_exif_module.EXIFTOOL_ENV_VAR, raising=False)
    monkeypatch.setattr(
        core_exif_module.sys,
        '_MEIPASS',
        str(tmp_path),
        raising=False,
    )
    monkeypatch.setattr(
        core_exif_module.shutil, 'which', lambda _name: None
    )

    assert core_exif_module._resolve_exiftool_path() == str(bundled_exiftool)


def test_resolve_exiftool_path_falls_back_to_system_path(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(core_exif_module.EXIFTOOL_ENV_VAR, raising=False)
    monkeypatch.setattr(
        core_exif_module,
        '_resolve_bundled_exiftool_path',
        lambda: None,
    )
    monkeypatch.setattr(
        core_exif_module.shutil,
        'which',
        lambda name: '/usr/bin/exiftool' if name == 'exiftool' else None,
    )

    assert core_exif_module._resolve_exiftool_path() == '/usr/bin/exiftool'


@pytest.mark.parametrize(
    ('mode', 'stdout'),
    [
        pytest.param('missing', None, id='missing-exiftool'),
        pytest.param('subprocess-error', None, id='subprocess-error'),
        pytest.param('invalid-json', 'not-json', id='invalid-json'),
    ],
)
def test_read_exif_metadata_returns_empty_for_missing_and_failed_exiftool_paths(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        mode: str,
        stdout: str | None,
) -> None:
    source = tmp_path / 'IMG_6100.JPG'
    source.write_bytes(b'jpeg')
    monkeypatch.delenv(core_exif_module.EXIFTOOL_ENV_VAR, raising=False)
    monkeypatch.setattr(
        core_exif_module,
        '_resolve_bundled_exiftool_path',
        lambda: None,
    )

    if mode == 'missing':
        monkeypatch.setattr(
            core_exif_module.shutil, 'which', lambda _name: None
        )
    else:
        monkeypatch.setattr(
            core_exif_module.shutil, 'which', lambda _name: '/usr/bin/exiftool'
        )
        if mode == 'subprocess-error':

            def raise_called_process_error(
                    *_args: Any, **_kwargs: Any
            ) -> Never:
                raise core_exif_module.subprocess.CalledProcessError(
                    1, ['exiftool']
                )

            monkeypatch.setattr(
                core_exif_module.subprocess, 'run', raise_called_process_error
            )
        else:
            monkeypatch.setattr(
                core_exif_module.subprocess,
                'run',
                lambda *_args, **_kwargs: type(
                    'Result', (), {'stdout': stdout}
                )(),
            )

    assert core_exif_module.read_exif_metadata([source]) == {}


def test_read_exif_metadata_returns_records_keyed_by_filename(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
) -> None:
    first = tmp_path / 'IMG_6100.JPG'
    second = tmp_path / 'IMG_6101.JPG'
    first.write_bytes(b'jpeg')
    second.write_bytes(b'jpeg')
    captured_command: list[str] = []
    monkeypatch.delenv(core_exif_module.EXIFTOOL_ENV_VAR, raising=False)
    monkeypatch.setattr(
        core_exif_module,
        '_resolve_bundled_exiftool_path',
        lambda: None,
    )
    monkeypatch.setattr(
        core_exif_module.shutil, 'which', lambda _name: '/usr/bin/exiftool'
    )

    def fake_run(*args: Any, **_kwargs: Any) -> object:
        captured_command.extend(args[0])
        return type(
            'Result',
            (),
            {
                'stdout': core_exif_module.json.dumps([
                    {
                        'SourceFile': str(first),
                        'Make': 'Canon',
                    },
                    {
                        'SourceFile': str(second),
                        'Make': 'NIKON CORPORATION',
                    },
                    {'Make': 'Ignored Without SourceFile'},
                ])
            },
        )()

    monkeypatch.setattr(
        core_exif_module.subprocess,
        'run',
        fake_run,
    )

    assert core_exif_module.read_exif_metadata([first, second]) == {
        'IMG_6100.JPG': {'SourceFile': str(first), 'Make': 'Canon'},
        'IMG_6101.JPG': {
            'SourceFile': str(second),
            'Make': 'NIKON CORPORATION',
        },
    }
    assert captured_command[:4] == ['/usr/bin/exiftool', '-j', '-n', '-struct']


@pytest.mark.parametrize(
    ('metadata', 'expected'),
    [
        pytest.param(
            {'SubSecDateTimeOriginal': '2024:05:01 10:00:00.123'},
            datetime(2024, 5, 1, 10, 0, 0, tzinfo=UTC),
            id='subsec-datetime-original',
        ),
        pytest.param(
            {'DateTimeOriginal': '2024-05-01 10:00:00'},
            datetime(2024, 5, 1, 10, 0, 0, tzinfo=UTC),
            id='dash-separator',
        ),
        pytest.param(
            {'CreateDate': '2024-05-01T10:00:00'},
            datetime(2024, 5, 1, 10, 0, 0, tzinfo=UTC),
            id='t-separator',
        ),
        pytest.param(
            {'SubSecCreateDate': '2024:05:01 10:30:00.456'},
            datetime(2024, 5, 1, 10, 30, 0, tzinfo=UTC),
            id='subsec-create-date',
        ),
        pytest.param(
            {'DateTimeOriginal': 'short'},
            None,
            id='too-short-string',
        ),
        pytest.param(
            {'DateTimeOriginal': 12345},
            None,
            id='non-string-value',
        ),
        pytest.param(
            {},
            None,
            id='no-date-keys',
        ),
        pytest.param(
            {
                'SubSecDateTimeOriginal': '2024:05:01 09:00:00.000',
                'DateTimeOriginal': '2024:05:01 10:00:00',
            },
            datetime(2024, 5, 1, 9, 0, 0, tzinfo=UTC),
            id='subsec-takes-priority-over-datetime-original',
        ),
        pytest.param(
            {
                'SubSecDateTimeOriginal': 'invalid-date',
                'DateTimeOriginal': '2024:05:01 10:00:00',
            },
            datetime(2024, 5, 1, 10, 0, 0, tzinfo=UTC),
            id='invalid-preferred-value-falls-back',
        ),
    ],
)
def test_parse_capture_time_handles_date_formats_and_key_priority(
        metadata: dict[str, Any],
        expected: datetime | None,
) -> None:
    result = core_exif_module.parse_capture_time(metadata)
    assert result == expected
