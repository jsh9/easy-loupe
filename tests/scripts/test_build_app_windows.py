from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from scripts.build_app import build_app_windows as build_app

if TYPE_CHECKING:
    import pytest


def test_windows_pyinstaller_command_prefers_module_when_binary_missing(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_app.shutil, 'which', lambda _name: None)
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
        'EasyCull',
        '--icon',
        str(build_app.ICON_PATH),
        '--collect-all',
        'PySide6',
        '--collect-all',
        'shiboken6',
        '--collect-data',
        'easy_cull.ui.assets',
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
        'EasyCull',
        '--icon',
        str(build_app.ICON_PATH),
        '--collect-all',
        'PySide6',
        '--collect-all',
        'shiboken6',
        '--collect-data',
        'easy_cull.ui.assets',
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
    monkeypatch.setattr(
        build_app,
        'ensure_exiftool_payload',
        lambda: build_app.EXIFTOOL_STAGE_EXE,
    )

    command = build_app.pyinstaller_command(windowed=False)

    assert '--windowed' not in command
    assert command[:3] == ['pyinstaller', '--clean', '--noconfirm']
