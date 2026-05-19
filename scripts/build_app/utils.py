"""Shared helpers for EasyCull PyInstaller build scripts."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess  # noqa: S404 - explicit PyInstaller/ExifTool integration
import sys
import urllib.request
from pathlib import Path

APP_NAME = 'EasyCull'
EXIFTOOL_VERSION = '13.58'
REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / 'easy_cull' / '__main__.py'
EXIFTOOL_CACHE_DIR = REPO_ROOT / 'build' / 'exiftool-cache'


def pyinstaller_base_command() -> list[str]:
    """Return the executable prefix for invoking PyInstaller."""
    pyinstaller = shutil.which('pyinstaller')
    return (
        [pyinstaller]
        if pyinstaller is not None
        else [sys.executable, '-m', 'PyInstaller']
    )


def common_pyinstaller_args(
        *,
        icon_path: Path,
        windowed: bool = True,
) -> list[str]:
    """Return PyInstaller arguments shared by macOS and Windows builds."""
    args = [
        '--noconfirm',
        '--name',
        APP_NAME,
        '--icon',
        str(icon_path),
        '--collect-all',
        'PySide6',
        '--collect-all',
        'shiboken6',
        '--collect-data',
        'easy_cull.ui.assets',
        str(ENTRYPOINT),
    ]
    if windowed:
        args.insert(1, '--windowed')

    return args


def download_file(url: str, destination: Path, *, message: str) -> None:
    """Download a build dependency into the local cache when missing."""
    EXIFTOOL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return

    print(message)
    urllib.request.urlretrieve(url, destination)  # noqa: S310


def print_common_diagnostics() -> None:
    """Print common build-environment diagnostics."""
    print(f'Platform: {platform.platform()}')
    print(f'Python: {sys.version}')
    print(f'Python executable: {sys.executable}')
    print(f'Repo root: {REPO_ROOT}')
    print_import_diagnostic('PyInstaller')
    print_import_diagnostic('PySide6')
    print_import_diagnostic('shiboken6')


def print_import_diagnostic(module_name: str) -> None:
    """Print a module version and import location, or its import error."""
    try:
        module = __import__(module_name)
    except ImportError as error:
        print(f'{module_name}: import failed: {error}')
        return

    version = getattr(module, '__version__', 'unknown')
    location = getattr(module, '__file__', 'unknown')
    print(f'{module_name}: version={version} location={location}')


def print_path_matches(root: Path, pattern: str) -> None:
    """Print up to ten paths under root matching a diagnostic glob pattern."""
    matches = sorted(root.rglob(pattern))
    print(f'{pattern}: {len(matches)}')
    for path in matches[:10]:
        print(f'  {path.relative_to(root)}')


def print_exiftool_version(exiftool_path: Path) -> None:
    """Print the version reported by a bundled ExifTool executable."""
    try:
        result = subprocess.run(  # noqa: S603 - known diagnostic path
            [str(exiftool_path), '-ver'],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        print(f'Bundled ExifTool version: failed: {error}')
        return

    print(f'Bundled ExifTool version: {result.stdout.strip()}')


def pyinstaller_source_and_dest(source: Path, dest: str) -> str:
    """Return a PyInstaller source/destination pair for this platform."""
    return f'{source}{os.pathsep}{dest}'
