"""Build the distributable Windows EasyCull executable with PyInstaller."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

APP_NAME = 'EasyCull'
REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / 'easy_cull' / '__main__.py'
ICON_SOURCE = REPO_ROOT / 'easy_cull' / 'ui' / 'assets' / 'EasyCull.png'
ICON_PATH = REPO_ROOT / 'easy_cull' / 'ui' / 'assets' / 'EasyCull.ico'
APP_PATH = REPO_ROOT / 'dist' / APP_NAME / f'{APP_NAME}.exe'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Build dist/EasyCull/EasyCull.exe with PyInstaller.'
    )
    parser.add_argument(
        '--onefile',
        action='store_true',
        help='build a single EasyCull.exe instead of a one-folder app',
    )
    parser.add_argument(
        '--no-clean',
        action='store_true',
        help='keep previous PyInstaller build artifacts',
    )
    args = parser.parse_args(argv)

    ensure_windows_icon()
    command = pyinstaller_command(
        clean=not args.no_clean,
        onefile=args.onefile,
    )
    subprocess.run(command, cwd=REPO_ROOT, check=True)
    print(REPO_ROOT / 'dist' / f'{APP_NAME}.exe' if args.onefile else APP_PATH)
    return 0


def ensure_windows_icon() -> None:
    """Create the Windows .ico asset from the app PNG when missing."""
    if ICON_PATH.exists():
        return

    with Image.open(ICON_SOURCE) as image:
        image.save(
            ICON_PATH,
            format='ICO',
            sizes=[(16, 16), (32, 32), (48, 48), (256, 256)],
        )


def pyinstaller_command(
        clean: bool = True,
        onefile: bool = False,
) -> list[str]:
    """Return the PyInstaller command for the Windows executable."""
    pyinstaller = shutil.which('pyinstaller')
    base_command = (
        [pyinstaller]
        if pyinstaller is not None
        else [sys.executable, '-m', 'PyInstaller']
    )
    command = [
        *base_command,
        '--noconfirm',
        '--windowed',
        '--name',
        APP_NAME,
        '--icon',
        str(ICON_PATH),
        '--collect-data',
        'easy_cull.ui.assets',
        str(ENTRYPOINT),
    ]
    if clean:
        command.insert(len(base_command), '--clean')
    if onefile:
        command.insert(len(base_command) + (1 if clean else 0), '--onefile')

    return command


if __name__ == '__main__':
    raise SystemExit(main())
