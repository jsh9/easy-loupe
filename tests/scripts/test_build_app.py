from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from scripts.macos import build_app

if TYPE_CHECKING:
    import pytest


def test_pyinstaller_command_prefers_module_when_binary_missing(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_app.shutil, 'which', lambda _name: None)

    assert build_app.pyinstaller_command() == [
        sys.executable,
        '-m',
        'PyInstaller',
        '--clean',
        '--noconfirm',
        str(build_app.SPEC_PATH),
    ]


def test_pyinstaller_command_uses_binary_when_available(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_app.shutil, 'which', lambda _name: 'pyinstaller')

    assert build_app.pyinstaller_command(clean=False) == [
        'pyinstaller',
        '--noconfirm',
        str(build_app.SPEC_PATH),
    ]
