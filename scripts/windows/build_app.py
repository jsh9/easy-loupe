"""Build the distributable Windows EasyCull executable with PyInstaller."""

from __future__ import annotations

import argparse
import platform
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
APP_DIR = REPO_ROOT / 'dist' / APP_NAME
APP_PATH = REPO_ROOT / 'dist' / APP_NAME / f'{APP_NAME}.exe'
ONEFILE_PATH = REPO_ROOT / 'dist' / f'{APP_NAME}.exe'


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
    parser.add_argument(
        '--console',
        action='store_true',
        help='build a console executable for debugging startup failures',
    )
    parser.add_argument(
        '--diagnose',
        action='store_true',
        help='print build environment and dist folder diagnostics, then exit',
    )
    args = parser.parse_args(argv)

    if args.diagnose:
        print_diagnostics()
        return 0

    ensure_windows_icon()
    run_preflight_check()
    command = pyinstaller_command(
        clean=not args.no_clean,
        onefile=args.onefile,
        windowed=not args.console,
    )
    subprocess.run(command, cwd=REPO_ROOT, check=True)
    if args.onefile:
        print(ONEFILE_PATH)
    else:
        print(APP_DIR)
        print(f'Run {APP_PATH} from inside this folder.')
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
        windowed: bool = True,
) -> list[str]:
    """Return the PyInstaller command for the Windows executable."""
    pyinstaller = shutil.which('pyinstaller')
    base_command = (
        [pyinstaller]
        if pyinstaller is not None
        else [sys.executable, '-m', 'PyInstaller']
    )
    command = [*base_command]
    if clean:
        command.append('--clean')
    if onefile:
        command.append('--onefile')
    command.append('--noconfirm')
    if windowed:
        command.append('--windowed')
    command.extend(
        [
            '--name',
            APP_NAME,
            '--icon',
            str(ICON_PATH),
            '--collect-all',
            'PySide6',
            '--collect-all',
            'shiboken6',
            '--collect-data',
            'easy_cull.ui.assets',
            str(ENTRYPOINT),
        ]
    )

    return command


def run_preflight_check() -> None:
    """Fail early when PySide6 cannot import in the build environment."""
    subprocess.run(
        [
            sys.executable,
            '-c',
            (
                'import PySide6; '
                'from PySide6.QtWidgets import QApplication; '
                'print(f"PySide6 preflight OK: {PySide6.__version__}")'
            ),
        ],
        cwd=REPO_ROOT,
        check=True,
    )


def print_diagnostics() -> None:
    """Print diagnostics for investigating Windows packaging failures."""
    print(f'Platform: {platform.platform()}')
    print(f'Python: {sys.version}')
    print(f'Python executable: {sys.executable}')
    print(f'Repo root: {REPO_ROOT}')
    _print_import_diagnostic('PyInstaller')
    _print_import_diagnostic('PySide6')
    _print_import_diagnostic('shiboken6')

    if not APP_DIR.exists():
        print(f'Dist folder missing: {APP_DIR}')
        return

    print(f'Dist folder: {APP_DIR}')
    _print_path_matches('QtWidgets.pyd')
    _print_path_matches('Qt6Core.dll')
    _print_path_matches('Qt6Gui.dll')
    _print_path_matches('Qt6Widgets.dll')
    _print_path_matches('qwindows.dll')
    _print_path_matches('vcruntime*.dll')
    _print_path_matches('msvcp*.dll')


def _print_import_diagnostic(module_name: str) -> None:
    try:
        module = __import__(module_name)
    except ImportError as error:
        print(f'{module_name}: import failed: {error}')
        return

    version = getattr(module, '__version__', 'unknown')
    location = getattr(module, '__file__', 'unknown')
    print(f'{module_name}: version={version} location={location}')


def _print_path_matches(pattern: str) -> None:
    matches = sorted(APP_DIR.rglob(pattern))
    print(f'{pattern}: {len(matches)}')
    for path in matches[:10]:
        print(f'  {path.relative_to(APP_DIR)}')


if __name__ == '__main__':
    raise SystemExit(main())
