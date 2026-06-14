from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never

import pytest

import easy_loupe.core.exif as core_exif_module


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
        'LensID': 'NIKKOR Z 50mm f/1.8 S',
        'LensMake': 'Nikon',
        'LensModel': 'NIKKOR Z 50mm f/1.8 S',
        'FNumber': '2.8',
        'ExposureTime': '0.004',
        'ISO': 800,
        'FocalLength': '50',
        'GPSLatitude': 40.712776,
        'GPSLongitude': -74.005974,
        'GPSAltitude': 12.4,
    }

    assert core_exif_module.format_exif_display(metadata) == {
        'Camera Make': 'NIKON CORPORATION',
        'Camera Model': 'Z 8',
        'Lens ID': 'NIKKOR Z 50mm f/1.8 S',
        'Lens Make': 'Nikon',
        'Lens Model': 'NIKKOR Z 50mm f/1.8 S',
        'Focal Length': '50\u00a0mm',
        'Aperture': '\u0192/2.8',
        'Shutter Speed': '1/250\u00a0s',
        'ISO': '800',
        'GPS': '40.712776º, -74.005974º, 12.4\u00a0m',
    }


def test_format_exif_display_uses_lens_fallback_and_long_exposure() -> None:
    metadata = {
        'Make': 'Canon',
        'Lens': 'RF 24-70mm F2.8L IS USM',
        'ExposureTime': 2,
    }

    assert core_exif_module.format_exif_display(metadata) == {
        'Camera Make': 'Canon',
        'Lens Model': 'RF 24-70mm F2.8L IS USM',
        'Shutter Speed': '2\u00a0s',
    }


def test_format_exif_display_omits_missing_fields() -> None:
    assert core_exif_module.format_exif_display({}) == {}


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
        / 'easy_loupe'
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
    monkeypatch.setattr(core_exif_module.shutil, 'which', lambda _name: None)

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


def test_exiftool_subprocess_kwargs_are_empty_without_windows_support(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Non-Windows platforms should launch ExifTool normally.

    The console-popup problem is Windows-specific. On macOS/Linux, Python's
    subprocess module does not provide the Windows-only constants used to hide
    a helper process window, so EasyLoupe should pass no extra options.
    """
    # Remove the Windows-only subprocess attributes even if the test happens to
    # run on Windows, so this test behaves like a non-Windows Python runtime.
    for attr in [
        'CREATE_NO_WINDOW',
        'STARTUPINFO',
        'STARTF_USESHOWWINDOW',
        'SW_HIDE',
    ]:
        monkeypatch.delattr(core_exif_module.subprocess, attr, raising=False)

    assert core_exif_module._exiftool_subprocess_kwargs() == {}


def test_exiftool_subprocess_kwargs_hide_windows_console(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Windows should launch ExifTool without showing a terminal window.

    The app itself is a PySide/Qt GUI, but ExifTool is a separate console
    program. This test fakes the Windows-only subprocess constants/classes and
    checks that EasyLoupe asks Windows to keep that helper process hidden.
    """

    class FakeStartupInfo:
        """Tiny stand-in for subprocess.STARTUPINFO used on Windows."""

        def __init__(self) -> None:
            self.dwFlags = 0
            self.wShowWindow = None

    # These values mirror the shape of Windows subprocess attributes without
    # requiring the test suite to actually run on Windows.
    monkeypatch.setattr(
        core_exif_module.subprocess,
        'CREATE_NO_WINDOW',
        0x08000000,
        raising=False,
    )
    monkeypatch.setattr(
        core_exif_module.subprocess,
        'STARTUPINFO',
        FakeStartupInfo,
        raising=False,
    )
    monkeypatch.setattr(
        core_exif_module.subprocess,
        'STARTF_USESHOWWINDOW',
        1,
        raising=False,
    )
    monkeypatch.setattr(
        core_exif_module.subprocess,
        'SW_HIDE',
        0,
        raising=False,
    )

    kwargs = core_exif_module._exiftool_subprocess_kwargs()

    assert kwargs['creationflags'] == 0x08000000
    assert kwargs['startupinfo'].dwFlags == 1
    assert kwargs['startupinfo'].wShowWindow == 0


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


def test_read_exif_metadata_returns_records_keyed_by_path_and_filename(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
) -> None:
    """
    Verify EXIF results are keyed by resolved path and basename.

    Recursive scans need path keys for duplicate filenames, while basename keys
    preserve existing flat-folder callers and test stubs.
    """
    first = tmp_path / 'IMG_6100.JPG'
    second = tmp_path / 'IMG_6101.JPG'
    first.write_bytes(b'jpeg')
    second.write_bytes(b'jpeg')
    captured_command: list[str] = []
    captured_kwargs: dict[str, Any] = {}
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
        captured_kwargs.update(_kwargs)
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
        str(first.resolve()): {'SourceFile': str(first), 'Make': 'Canon'},
        'IMG_6100.JPG': {'SourceFile': str(first), 'Make': 'Canon'},
        str(second.resolve()): {
            'SourceFile': str(second),
            'Make': 'NIKON CORPORATION',
        },
        'IMG_6101.JPG': {
            'SourceFile': str(second),
            'Make': 'NIKON CORPORATION',
        },
    }
    assert captured_command[:4] == ['/usr/bin/exiftool', '-j', '-n', '-struct']
    assert captured_kwargs['check'] is True
    assert captured_kwargs['capture_output'] is True
    assert captured_kwargs['text'] is True


def test_read_exif_metadata_batches_files_and_reports_batch_progress(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
) -> None:
    """
    Verify ExifTool reads honor caller batch size and emit batch counts.

    Folder loading relies on this callback to keep large metadata reads from
    looking frozen while preserving a single ExifTool launch per batch.
    """
    first = tmp_path / 'IMG_6200.JPG'
    second = tmp_path / 'IMG_6201.JPG'
    first.write_bytes(b'jpeg')
    second.write_bytes(b'jpeg')
    commands: list[list[str]] = []
    progress_updates: list[tuple[int, int, int]] = []
    monkeypatch.delenv(core_exif_module.EXIFTOOL_ENV_VAR, raising=False)
    monkeypatch.setattr(
        core_exif_module,
        '_resolve_bundled_exiftool_path',
        lambda: None,
    )
    monkeypatch.setattr(
        core_exif_module.shutil, 'which', lambda _name: '/usr/bin/exiftool'
    )

    def fake_run(command: list[str], **_kwargs: Any) -> object:
        commands.append(command)
        source_file = command[-1]
        return type(
            'Result',
            (),
            {
                'stdout': core_exif_module.json.dumps([
                    {'SourceFile': source_file, 'Make': source_file}
                ])
            },
        )()

    monkeypatch.setattr(core_exif_module.subprocess, 'run', fake_run)

    metadata = core_exif_module.read_exif_metadata(
        [first, second],
        batch_size=1,
        batch_progress_callback=lambda index, total, size: (
            progress_updates.append((index, total, size))
        ),
    )

    assert progress_updates == [(1, 2, 1), (2, 2, 1)]
    assert [[command[-1]] for command in commands] == [
        [str(first)],
        [str(second)],
    ]
    assert metadata['IMG_6200.JPG']['SourceFile'] == str(first)
    assert metadata['IMG_6201.JPG']['SourceFile'] == str(second)


@pytest.mark.parametrize(
    'failure_mode',
    [
        pytest.param('subprocess-error', id='subprocess-error'),
        pytest.param('invalid-json', id='invalid-json'),
    ],
)
def test_read_exif_metadata_recovers_good_files_from_failed_batch(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        failure_mode: str,
) -> None:
    """
    Verify failed ExifTool batches are split until only bad files are skipped.

    One corrupt photo should not erase metadata for other files from the same
    configured batch, and later configured batches should still run.
    """
    files = [
        tmp_path / 'IMG_6300.JPG',
        tmp_path / 'BAD.JPG',
        tmp_path / 'IMG_6301.JPG',
        tmp_path / 'IMG_6302.JPG',
        tmp_path / 'IMG_6303.JPG',
    ]
    for path in files:
        path.write_bytes(b'jpeg')

    commands: list[list[str]] = []
    progress_updates: list[tuple[int, int, int]] = []
    monkeypatch.delenv(core_exif_module.EXIFTOOL_ENV_VAR, raising=False)
    monkeypatch.setattr(
        core_exif_module,
        '_resolve_bundled_exiftool_path',
        lambda: None,
    )
    monkeypatch.setattr(
        core_exif_module.shutil, 'which', lambda _name: '/usr/bin/exiftool'
    )

    def fake_run(command: list[str], **_kwargs: Any) -> object:
        commands.append(command)
        if any(Path(argument).name == 'BAD.JPG' for argument in command):
            if failure_mode == 'subprocess-error':
                raise core_exif_module.subprocess.CalledProcessError(
                    1, command
                )

            return type('Result', (), {'stdout': 'not-json'})()

        return type(
            'Result',
            (),
            {
                'stdout': core_exif_module.json.dumps([
                    {
                        'SourceFile': argument,
                        'Make': Path(argument).stem,
                    }
                    for argument in command[4:]
                ])
            },
        )()

    monkeypatch.setattr(core_exif_module.subprocess, 'run', fake_run)

    metadata = core_exif_module.read_exif_metadata(
        files,
        batch_size=3,
        batch_progress_callback=lambda index, total, size: (
            progress_updates.append((index, total, size))
        ),
    )

    assert progress_updates == [(1, 2, 3), (2, 2, 3)]
    command_names = [
        [Path(argument).name for argument in command[4:]]
        for command in commands
    ]
    assert command_names == [
        ['IMG_6300.JPG', 'BAD.JPG', 'IMG_6301.JPG'],
        ['IMG_6300.JPG'],
        ['BAD.JPG', 'IMG_6301.JPG'],
        ['BAD.JPG'],
        ['IMG_6301.JPG'],
        ['IMG_6302.JPG', 'IMG_6303.JPG'],
    ]
    assert 'BAD.JPG' not in metadata
    assert metadata['IMG_6300.JPG']['Make'] == 'IMG_6300'
    assert metadata['IMG_6301.JPG']['Make'] == 'IMG_6301'
    assert metadata['IMG_6302.JPG']['Make'] == 'IMG_6302'
    assert metadata['IMG_6303.JPG']['Make'] == 'IMG_6303'


def test_read_exif_metadata_stops_recovery_after_exiftool_launch_error(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
) -> None:
    """
    Verify launch errors keep earlier records and avoid recursive retries.

    ``OSError`` means ExifTool itself cannot be launched reliably, so the
    reader should not split the failed batch or attempt later configured
    batches. Stopped batches must not be reported as complete progress.
    """
    files = [
        tmp_path / 'IMG_6400.JPG',
        tmp_path / 'IMG_6401.JPG',
        tmp_path / 'IMG_6402.JPG',
        tmp_path / 'IMG_6403.JPG',
        tmp_path / 'IMG_6404.JPG',
    ]
    for path in files:
        path.write_bytes(b'jpeg')

    commands: list[list[str]] = []
    progress_updates: list[tuple[int, int, int]] = []
    monkeypatch.delenv(core_exif_module.EXIFTOOL_ENV_VAR, raising=False)
    monkeypatch.setattr(
        core_exif_module,
        '_resolve_bundled_exiftool_path',
        lambda: None,
    )
    monkeypatch.setattr(
        core_exif_module.shutil, 'which', lambda _name: '/usr/bin/exiftool'
    )

    def fake_run(command: list[str], **_kwargs: Any) -> object:
        commands.append(command)
        if any(Path(argument).name == 'IMG_6402.JPG' for argument in command):
            raise OSError('exiftool launch failed')

        return type(
            'Result',
            (),
            {
                'stdout': core_exif_module.json.dumps([
                    {
                        'SourceFile': argument,
                        'Make': Path(argument).stem,
                    }
                    for argument in command[4:]
                ])
            },
        )()

    monkeypatch.setattr(core_exif_module.subprocess, 'run', fake_run)

    metadata = core_exif_module.read_exif_metadata(
        files,
        batch_size=2,
        batch_progress_callback=lambda index, total, size: (
            progress_updates.append((index, total, size))
        ),
    )

    assert progress_updates == [(1, 3, 2)]
    command_names = [
        [Path(argument).name for argument in command[4:]]
        for command in commands
    ]
    assert command_names == [
        ['IMG_6400.JPG', 'IMG_6401.JPG'],
        ['IMG_6402.JPG', 'IMG_6403.JPG'],
    ]
    assert metadata == {
        str(files[0].resolve()): {
            'SourceFile': str(files[0]),
            'Make': 'IMG_6400',
        },
        'IMG_6400.JPG': {
            'SourceFile': str(files[0]),
            'Make': 'IMG_6400',
        },
        str(files[1].resolve()): {
            'SourceFile': str(files[1]),
            'Make': 'IMG_6401',
        },
        'IMG_6401.JPG': {
            'SourceFile': str(files[1]),
            'Make': 'IMG_6401',
        },
    }


@pytest.mark.parametrize(
    (
        'file_names',
        'recoverable_fail_names',
        'launch_fail_names',
        'expected_calls',
        'expected_record_names',
        'expected_stop',
    ),
    [
        pytest.param(
            ['IMG_6500.JPG', 'IMG_6501.JPG'],
            set(),
            set(),
            [['IMG_6500.JPG', 'IMG_6501.JPG']],
            ['IMG_6500.JPG', 'IMG_6501.JPG'],
            False,
            id='success-without-splitting',
        ),
        pytest.param(
            ['BAD.JPG'],
            {'BAD.JPG'},
            set(),
            [['BAD.JPG']],
            [],
            False,
            id='single-bad-file-skipped',
        ),
        pytest.param(
            ['IMG_6600.JPG', 'BAD.JPG', 'IMG_6601.JPG', 'IMG_6602.JPG'],
            {'BAD.JPG'},
            set(),
            [
                ['IMG_6600.JPG', 'BAD.JPG', 'IMG_6601.JPG', 'IMG_6602.JPG'],
                ['IMG_6600.JPG', 'BAD.JPG'],
                ['IMG_6600.JPG'],
                ['BAD.JPG'],
                ['IMG_6601.JPG', 'IMG_6602.JPG'],
            ],
            ['IMG_6600.JPG', 'IMG_6601.JPG', 'IMG_6602.JPG'],
            False,
            id='split-recovers-good-files',
        ),
        pytest.param(
            [
                'LAUNCH_FAIL.JPG',
                'IMG_6700.JPG',
                'IMG_6701.JPG',
                'IMG_6702.JPG',
            ],
            set(),
            {'LAUNCH_FAIL.JPG'},
            [
                [
                    'LAUNCH_FAIL.JPG',
                    'IMG_6700.JPG',
                    'IMG_6701.JPG',
                    'IMG_6702.JPG',
                ],
                ['LAUNCH_FAIL.JPG', 'IMG_6700.JPG'],
                ['LAUNCH_FAIL.JPG'],
            ],
            [],
            True,
            id='launch-error-stops-retries',
        ),
    ],
)
def test_read_exif_batch_with_recovery_handles_split_cases(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        file_names: list[str],
        recoverable_fail_names: set[str],
        launch_fail_names: set[str],
        expected_calls: list[list[str]],
        expected_record_names: list[str],
        expected_stop: bool,
) -> None:
    """
    Verify recursive batch recovery handles success, bad files, and launch
    loss.

    This pins the divide-and-conquer behavior independently of subprocess
    command construction while keeping each scenario in a compact table.
    """
    files = [tmp_path / file_name for file_name in file_names]
    calls: list[list[str]] = []

    def fake_read_batch(
            _exiftool_path: str, batch: list[Path]
    ) -> dict[str, dict[str, Any]]:
        batch_names = [path.name for path in batch]
        calls.append(batch_names)
        if any(name in launch_fail_names for name in batch_names):
            if len(batch) == 1:
                raise core_exif_module._ExifToolLaunchError

            raise core_exif_module._ExifToolBatchError

        if any(name in recoverable_fail_names for name in batch_names):
            raise core_exif_module._ExifToolBatchError

        return {path.name: {'SourceFile': str(path)} for path in batch}

    monkeypatch.setattr(core_exif_module, '_read_exif_batch', fake_read_batch)

    records, stop_after_batch = (
        core_exif_module._read_exif_batch_with_recovery(
            '/usr/bin/exiftool', files
        )
    )

    assert calls == expected_calls
    assert records == {
        file_name: {'SourceFile': str(tmp_path / file_name)}
        for file_name in expected_record_names
    }
    assert stop_after_batch is expected_stop


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
