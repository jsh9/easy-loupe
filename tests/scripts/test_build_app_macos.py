from __future__ import annotations

import os
import plistlib
import sys
from typing import TYPE_CHECKING

from scripts.build_app import build_app_macos as build_app

if TYPE_CHECKING:
    from pathlib import Path

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
        f'{build_app.EXIFTOOL_STAGE_EXE}{os.pathsep}'
        f'{build_app.EXIFTOOL_BUNDLE_DIR}'
    )
    exiftool_lib = (
        f'{build_app.EXIFTOOL_STAGE_LIB}{os.pathsep}'
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
        '--collect-all',
        'PySide6',
        '--collect-all',
        'shiboken6',
        '--collect-data',
        'easy_cull.ui.assets',
        '--copy-metadata',
        'easy-cull',
        '--add-binary',
        exiftool_binary,
        '--add-data',
        exiftool_lib,
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
        f'{build_app.EXIFTOOL_STAGE_EXE}{os.pathsep}'
        f'{build_app.EXIFTOOL_BUNDLE_DIR}'
    )
    exiftool_lib = (
        f'{build_app.EXIFTOOL_STAGE_LIB}{os.pathsep}'
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
        '--collect-all',
        'PySide6',
        '--collect-all',
        'shiboken6',
        '--collect-data',
        'easy_cull.ui.assets',
        '--copy-metadata',
        'easy-cull',
        '--add-binary',
        exiftool_binary,
        '--add-data',
        exiftool_lib,
        str(build_app.ENTRYPOINT),
    ]


def test_document_type_entry_registers_supported_photo_extensions() -> None:
    entry = build_app.document_type_entry()

    assert entry['CFBundleTypeRole'] == 'Viewer'
    assert entry['LSHandlerRank'] == 'Alternate'
    assert {'jpg', 'heic', 'arw', 'rw2'} <= set(
        entry['CFBundleTypeExtensions']
    )


def test_inject_document_types_updates_info_plist(tmp_path: Path) -> None:
    app_path = tmp_path / 'EasyCull.app'
    contents = app_path / 'Contents'
    contents.mkdir(parents=True)
    info_plist = contents / 'Info.plist'
    with info_plist.open('wb') as file:
        plistlib.dump({'CFBundleName': 'EasyCull'}, file)

    build_app.inject_document_types(app_path)

    with info_plist.open('rb') as file:
        payload = plistlib.load(file)

    assert payload['CFBundleDocumentTypes'] == [
        build_app.document_type_entry()
    ]
