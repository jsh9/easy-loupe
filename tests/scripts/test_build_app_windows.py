from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

from scripts.build_app import build_app_windows as build_app

if TYPE_CHECKING:
    from pathlib import Path


def test_windows_pyinstaller_command_prefers_module_when_binary_missing(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_app.shutil, 'which', lambda _name: None)
    # Pin the dependency-metadata args so the exact command does not
    # depend on which packages this test environment has installed.
    monkeypatch.setattr(
        build_app.utils,
        'runtime_metadata_args',
        lambda: ['--copy-metadata', 'pillow'],
    )
    monkeypatch.setattr(
        build_app,
        'ensure_exiftool_payload',
        lambda: build_app.EXIFTOOL_STAGE_EXE,
    )
    exiftool_binary = (
        f'{build_app.EXIFTOOL_STAGE_EXE}{os.pathsep}'
        f'{build_app.EXIFTOOL_BUNDLE_DIR}'
    )
    exiftool_files = (
        f'{build_app.EXIFTOOL_STAGE_FILES}{os.pathsep}'
        f'{build_app.EXIFTOOL_BUNDLE_DIR}/exiftool_files'
    )

    assert build_app.pyinstaller_command() == [
        sys.executable,
        '-m',
        'PyInstaller',
        '--clean',
        '--noconfirm',
        '--windowed',
        '--name',
        'EasyLoupe',
        '--icon',
        str(build_app.ICON_PATH),
        '--collect-all',
        'PySide6',
        '--collect-all',
        'shiboken6',
        '--collect-data',
        'easy_loupe.ui.assets',
        '--copy-metadata',
        'easy-loupe',
        '--copy-metadata',
        'pillow',
        '--add-data',
        f'{build_app.utils.LICENSE_PATH}{os.pathsep}.',
        '--add-data',
        f'{build_app.utils.THIRD_PARTY_NOTICES_PATH}{os.pathsep}.',
        '--add-data',
        (
            f'{build_app.utils.THIRD_PARTY_LICENSES_DIR}{os.pathsep}'
            'third_party_licenses'
        ),
        '--add-binary',
        exiftool_binary,
        '--add-data',
        exiftool_files,
        str(build_app.ENTRYPOINT),
    ]


def test_windows_pyinstaller_command_supports_onefile(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_app.shutil, 'which', lambda _name: 'pyinstaller')
    # Pin the dependency-metadata args so the exact command does not
    # depend on which packages this test environment has installed.
    monkeypatch.setattr(
        build_app.utils,
        'runtime_metadata_args',
        lambda: ['--copy-metadata', 'pillow'],
    )
    monkeypatch.setattr(
        build_app,
        'ensure_exiftool_payload',
        lambda: build_app.EXIFTOOL_STAGE_EXE,
    )
    exiftool_binary = (
        f'{build_app.EXIFTOOL_STAGE_EXE}{os.pathsep}'
        f'{build_app.EXIFTOOL_BUNDLE_DIR}'
    )
    exiftool_files = (
        f'{build_app.EXIFTOOL_STAGE_FILES}{os.pathsep}'
        f'{build_app.EXIFTOOL_BUNDLE_DIR}/exiftool_files'
    )

    assert build_app.pyinstaller_command(clean=False, onefile=True) == [
        'pyinstaller',
        '--onefile',
        '--noconfirm',
        '--windowed',
        '--name',
        'EasyLoupe',
        '--icon',
        str(build_app.ICON_PATH),
        '--collect-all',
        'PySide6',
        '--collect-all',
        'shiboken6',
        '--collect-data',
        'easy_loupe.ui.assets',
        '--copy-metadata',
        'easy-loupe',
        '--copy-metadata',
        'pillow',
        '--add-data',
        f'{build_app.utils.LICENSE_PATH}{os.pathsep}.',
        '--add-data',
        f'{build_app.utils.THIRD_PARTY_NOTICES_PATH}{os.pathsep}.',
        '--add-data',
        (
            f'{build_app.utils.THIRD_PARTY_LICENSES_DIR}{os.pathsep}'
            'third_party_licenses'
        ),
        '--add-binary',
        exiftool_binary,
        '--add-data',
        exiftool_files,
        str(build_app.ENTRYPOINT),
    ]


def test_windows_pyinstaller_command_supports_console_debug_build(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_app.shutil, 'which', lambda _name: 'pyinstaller')
    # Pin the dependency-metadata args so the exact command does not
    # depend on which packages this test environment has installed.
    monkeypatch.setattr(
        build_app.utils,
        'runtime_metadata_args',
        lambda: ['--copy-metadata', 'pillow'],
    )
    monkeypatch.setattr(
        build_app,
        'ensure_exiftool_payload',
        lambda: build_app.EXIFTOOL_STAGE_EXE,
    )

    command = build_app.pyinstaller_command(windowed=False)

    assert '--windowed' not in command
    assert command[:3] == ['pyinstaller', '--clean', '--noconfirm']


@pytest.mark.parametrize(
    ('argv', 'expected_verified_dirs'),
    [
        pytest.param([], ['one-folder'], id='one-folder'),
        pytest.param(['--onefile'], [], id='onefile'),
    ],
)
def test_windows_main_verifies_licenses_in_one_folder_builds(
        monkeypatch: pytest.MonkeyPatch,
        argv: list[str],
        expected_verified_dirs: list[str],
) -> None:
    """
    Verify Windows builds inspect the built app for license files.

    One-folder builds expose their data files under ``_internal``, so the build
    must fail there when license files are missing. One-file builds pack data
    inside the executable and cannot be inspected the same way.
    """
    verified_dirs: list[str] = []
    monkeypatch.setattr(build_app, 'ensure_windows_icon', lambda: None)
    monkeypatch.setattr(
        build_app,
        'ensure_exiftool_payload',
        lambda: build_app.EXIFTOOL_STAGE_EXE,
    )
    monkeypatch.setattr(build_app, 'run_preflight_check', lambda: None)
    monkeypatch.setattr(
        build_app, 'pyinstaller_command', lambda **_kwargs: ['pyinstaller']
    )
    monkeypatch.setattr(
        build_app.subprocess, 'run', lambda *_args, **_kwargs: None
    )

    def record_verified_dir(data_dir: Path) -> None:
        assert data_dir == build_app.APP_DIR / '_internal'
        verified_dirs.append('one-folder')

    monkeypatch.setattr(
        build_app.utils, 'verify_bundled_licenses', record_verified_dir
    )

    assert build_app.main(argv) == 0
    assert verified_dirs == expected_verified_dirs
