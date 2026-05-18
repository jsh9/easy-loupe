from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from scripts.windows import build_app

if TYPE_CHECKING:
    import pytest


def test_windows_pyinstaller_command_prefers_module_when_binary_missing(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_app.shutil, 'which', lambda _name: None)

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
        '--collect-data',
        'easy_cull.ui.assets',
        str(build_app.ENTRYPOINT),
    ]


def test_windows_pyinstaller_command_supports_onefile(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_app.shutil, 'which', lambda _name: 'pyinstaller')

    assert build_app.pyinstaller_command(clean=False, onefile=True) == [
        'pyinstaller',
        '--onefile',
        '--noconfirm',
        '--windowed',
        '--name',
        'EasyCull',
        '--icon',
        str(build_app.ICON_PATH),
        '--collect-data',
        'easy_cull.ui.assets',
        str(build_app.ENTRYPOINT),
    ]
