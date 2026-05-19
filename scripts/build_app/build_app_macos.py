"""Build the distributable macOS EasyCull.app with PyInstaller."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess  # noqa: S404 - explicit PyInstaller/ExifTool integration
import sys
import tarfile
import urllib.request
from pathlib import Path

APP_NAME = 'EasyCull'
EXIFTOOL_VERSION = '13.58'
REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / 'easy_cull' / '__main__.py'
ICON_PATH = REPO_ROOT / 'easy_cull' / 'ui' / 'assets' / 'EasyCull.icns'
APP_PATH = REPO_ROOT / 'dist' / f'{APP_NAME}.app'
EXIFTOOL_CACHE_DIR = REPO_ROOT / 'build' / 'exiftool-cache'
EXIFTOOL_STAGE_DIR = REPO_ROOT / 'build' / 'exiftool' / 'macos'
EXIFTOOL_STAGE_EXE = EXIFTOOL_STAGE_DIR / 'exiftool'
EXIFTOOL_STAGE_LIB = EXIFTOOL_STAGE_DIR / 'lib'
EXIFTOOL_BUNDLE_DIR = 'easy_cull/vendor/exiftool/macos'
EXIFTOOL_SOURCE_URL = (
    'https://sourceforge.net/projects/exiftool/files/'
    f'Image-ExifTool-{EXIFTOOL_VERSION}.tar.gz/download'
)
EXIFTOOL_SOURCE_ARCHIVE = (
    EXIFTOOL_CACHE_DIR / f'Image-ExifTool-{EXIFTOOL_VERSION}.tar.gz'
)


def main(argv: list[str] | None = None) -> int:
    """Build the macOS EasyCull app bundle or print diagnostics."""
    parser = argparse.ArgumentParser(
        description='Build dist/EasyCull.app with PyInstaller.'
    )
    parser.add_argument(
        '--no-clean',
        action='store_true',
        help='keep previous PyInstaller build artifacts',
    )
    parser.add_argument(
        '--diagnose',
        action='store_true',
        help='print build environment and app bundle diagnostics, then exit',
    )
    args = parser.parse_args(argv)

    if args.diagnose:
        print_diagnostics()
        return 0

    exiftool_path = ensure_exiftool_payload()
    print(f'Bundled ExifTool: {exiftool_path}')
    command = pyinstaller_command(clean=not args.no_clean)
    subprocess.run(command, cwd=REPO_ROOT, check=True)  # noqa: S603
    mark_bundled_exiftool_executable()
    print(APP_PATH)
    return 0


def ensure_exiftool_payload() -> Path:
    """Stage the platform-independent ExifTool payload for bundling."""
    if EXIFTOOL_STAGE_EXE.exists() and EXIFTOOL_STAGE_LIB.is_dir():
        return EXIFTOOL_STAGE_EXE

    EXIFTOOL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not EXIFTOOL_SOURCE_ARCHIVE.exists():
        print(f'Downloading ExifTool {EXIFTOOL_VERSION} source...')
        urllib.request.urlretrieve(  # noqa: S310
            EXIFTOOL_SOURCE_URL,
            EXIFTOOL_SOURCE_ARCHIVE,
        )

    extract_dir = EXIFTOOL_CACHE_DIR / f'macos-{EXIFTOOL_VERSION}'
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)
    with tarfile.open(EXIFTOOL_SOURCE_ARCHIVE, 'r:gz') as archive:
        archive.extractall(extract_dir, filter='data')

    source_exe = next(extract_dir.rglob('exiftool'), None)
    source_lib = next(
        (path for path in extract_dir.rglob('lib') if path.is_dir()),
        None,
    )
    if source_exe is None or source_lib is None:
        raise RuntimeError(
            'Downloaded ExifTool archive has unexpected layout.'
        )

    if EXIFTOOL_STAGE_DIR.exists():
        shutil.rmtree(EXIFTOOL_STAGE_DIR)
    EXIFTOOL_STAGE_DIR.mkdir(parents=True)
    shutil.copy2(source_exe, EXIFTOOL_STAGE_EXE)
    shutil.copytree(source_lib, EXIFTOOL_STAGE_LIB)
    EXIFTOOL_STAGE_EXE.chmod(EXIFTOOL_STAGE_EXE.stat().st_mode | 0o755)
    return EXIFTOOL_STAGE_EXE


def pyinstaller_command(*, clean: bool = True) -> list[str]:
    """Return the PyInstaller command for the macOS app bundle."""
    pyinstaller = shutil.which('pyinstaller')
    base_command = (
        [pyinstaller]
        if pyinstaller is not None
        else [sys.executable, '-m', 'PyInstaller']
    )
    exiftool_path = ensure_exiftool_payload()
    command = [*base_command]
    if clean:
        command.append('--clean')

    command.extend([
        '--noconfirm',
        '--windowed',
        '--name',
        APP_NAME,
        '--icon',
        str(ICON_PATH),
        '--add-binary',
        f'{exiftool_path}{os.pathsep}{EXIFTOOL_BUNDLE_DIR}',
        '--add-data',
        f'{EXIFTOOL_STAGE_LIB}{os.pathsep}{EXIFTOOL_BUNDLE_DIR}/lib',
        '--collect-all',
        'PySide6',
        '--collect-all',
        'shiboken6',
        '--collect-data',
        'easy_cull.ui.assets',
        str(ENTRYPOINT),
    ])

    return command


def mark_bundled_exiftool_executable() -> None:
    """Ensure the app-bundled exiftool script keeps executable bits."""
    for path in _bundled_exiftool_paths():
        path.chmod(path.stat().st_mode | 0o755)


def print_diagnostics() -> None:
    """Print diagnostics for investigating macOS packaging failures."""
    print(f'Platform: {platform.platform()}')
    print(f'Python: {sys.version}')
    print(f'Python executable: {sys.executable}')
    print(f'Repo root: {REPO_ROOT}')
    _print_import_diagnostic('PyInstaller')
    _print_import_diagnostic('PySide6')
    _print_import_diagnostic('shiboken6')

    if not APP_PATH.exists():
        print(f'App bundle missing: {APP_PATH}')
        return

    print(f'App bundle: {APP_PATH}')
    _print_path_matches('QtWidgets*')
    _print_path_matches('QtCore*')
    _print_path_matches('QtGui*')
    _print_path_matches('QtWidgets*')
    _print_path_matches('libshiboken*')
    _print_exiftool_diagnostic()


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
    matches = sorted(APP_PATH.rglob(pattern))
    print(f'{pattern}: {len(matches)}')
    for path in matches[:10]:
        print(f'  {path.relative_to(APP_PATH)}')


def _print_exiftool_diagnostic() -> None:
    paths = _bundled_exiftool_paths()
    if not paths:
        print('Bundled ExifTool: missing')
        return

    exiftool_path = paths[0]
    print(f'Bundled ExifTool: {exiftool_path}')
    try:
        result = subprocess.run(  # noqa: S603 - known bundled diagnostic path
            [str(exiftool_path), '-ver'],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        print(f'Bundled ExifTool version: failed: {error}')
        return

    print(f'Bundled ExifTool version: {result.stdout.strip()}')


def _bundled_exiftool_paths() -> list[Path]:
    if not APP_PATH.exists():
        return []

    return [
        path
        for path in sorted(APP_PATH.rglob('exiftool'))
        if path.as_posix().endswith(
            'easy_cull/vendor/exiftool/macos/exiftool'
        )
    ]


if __name__ == '__main__':
    raise SystemExit(main())
