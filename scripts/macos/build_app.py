"""Build the distributable macOS EasyCull.app with PyInstaller."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = 'EasyCull'
REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / f'{APP_NAME}.spec'
APP_PATH = REPO_ROOT / 'dist' / f'{APP_NAME}.app'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Build dist/EasyCull.app with PyInstaller.'
    )
    parser.add_argument(
        '--no-clean',
        action='store_true',
        help='keep previous PyInstaller build artifacts',
    )
    args = parser.parse_args(argv)

    command = pyinstaller_command(clean=not args.no_clean)
    subprocess.run(command, cwd=REPO_ROOT, check=True)
    print(APP_PATH)
    return 0


def pyinstaller_command(clean: bool = True) -> list[str]:
    """Return the PyInstaller command for the macOS app bundle."""
    pyinstaller = shutil.which('pyinstaller')
    base_command = (
        [pyinstaller]
        if pyinstaller is not None
        else [sys.executable, '-m', 'PyInstaller']
    )
    command = [
        *base_command,
        '--noconfirm',
        str(SPEC_PATH),
    ]
    if clean:
        command.insert(len(base_command), '--clean')

    return command


if __name__ == '__main__':
    raise SystemExit(main())
