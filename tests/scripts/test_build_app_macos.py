from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from scripts.build_app import build_app_macos as build_app

if TYPE_CHECKING:
    import pytest


def test_pyinstaller_command_prefers_module_when_binary_missing(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_app.shutil, 'which', lambda _name: None)
    monkeypatch.setattr(
        build_app,
        'ensure_exiftool_payload',
        lambda: build_app.EXIFTOOL_STAGE_EXE,
    )
    exiftool_binary = (
        f'{build_app.EXIFTOOL_STAGE_EXE}{build_app.os.pathsep}'
        f'{build_app.EXIFTOOL_BUNDLE_DIR}'
    )
    exiftool_lib = (
        f'{build_app.EXIFTOOL_STAGE_LIB}{build_app.os.pathsep}'
        f'{build_app.EXIFTOOL_BUNDLE_DIR}/lib'
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
        '--add-binary',
        exiftool_binary,
        '--add-data',
        exiftool_lib,
        '--collect-all',
        'PySide6',
        '--collect-all',
        'shiboken6',
        '--collect-data',
        'easy_cull.ui.assets',
        str(build_app.ENTRYPOINT),
    ]


def test_pyinstaller_command_uses_binary_when_available(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_app.shutil, 'which', lambda _name: 'pyinstaller')
    monkeypatch.setattr(
        build_app,
        'ensure_exiftool_payload',
        lambda: build_app.EXIFTOOL_STAGE_EXE,
    )
    exiftool_binary = (
        f'{build_app.EXIFTOOL_STAGE_EXE}{build_app.os.pathsep}'
        f'{build_app.EXIFTOOL_BUNDLE_DIR}'
    )
    exiftool_lib = (
        f'{build_app.EXIFTOOL_STAGE_LIB}{build_app.os.pathsep}'
        f'{build_app.EXIFTOOL_BUNDLE_DIR}/lib'
    )

    assert build_app.pyinstaller_command(clean=False) == [
        'pyinstaller',
        '--noconfirm',
        '--windowed',
        '--name',
        'EasyCull',
        '--icon',
        str(build_app.ICON_PATH),
        '--add-binary',
        exiftool_binary,
        '--add-data',
        exiftool_lib,
        '--collect-all',
        'PySide6',
        '--collect-all',
        'shiboken6',
        '--collect-data',
        'easy_cull.ui.assets',
        str(build_app.ENTRYPOINT),
    ]
