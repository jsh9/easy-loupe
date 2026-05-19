"""Build the distributable macOS EasyCull.app with PyInstaller."""

from __future__ import annotations

import argparse
import shutil
import subprocess  # noqa: S404 - explicit PyInstaller/ExifTool integration
import sys
import tarfile
from pathlib import Path

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.build_app import utils

APP_NAME = utils.APP_NAME
EXIFTOOL_VERSION = utils.EXIFTOOL_VERSION
REPO_ROOT = utils.REPO_ROOT
ENTRYPOINT = utils.ENTRYPOINT
ICON_PATH = REPO_ROOT / 'easy_cull' / 'ui' / 'assets' / 'EasyCull.icns'
APP_PATH = REPO_ROOT / 'dist' / f'{APP_NAME}.app'
EXIFTOOL_CACHE_DIR = utils.EXIFTOOL_CACHE_DIR
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
    utils.download_file(
        EXIFTOOL_SOURCE_URL,
        EXIFTOOL_SOURCE_ARCHIVE,
        message=f'Downloading ExifTool {EXIFTOOL_VERSION} source...',
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
    exiftool_path = ensure_exiftool_payload()
    command = utils.pyinstaller_base_command()
    if clean:
        command.append('--clean')

    command.extend(utils.common_pyinstaller_args(icon_path=ICON_PATH))
    entrypoint = command.pop()
    command.extend([
        '--add-binary',
        utils.pyinstaller_source_and_dest(exiftool_path, EXIFTOOL_BUNDLE_DIR),
        '--add-data',
        utils.pyinstaller_source_and_dest(
            EXIFTOOL_STAGE_LIB,
            f'{EXIFTOOL_BUNDLE_DIR}/lib',
        ),
        entrypoint,
    ])

    return command


def mark_bundled_exiftool_executable() -> None:
    """Ensure the app-bundled exiftool script keeps executable bits."""
    for path in _bundled_exiftool_paths():
        path.chmod(path.stat().st_mode | 0o755)


def print_diagnostics() -> None:
    """Print diagnostics for investigating macOS packaging failures."""
    utils.print_common_diagnostics()

    if not APP_PATH.exists():
        print(f'App bundle missing: {APP_PATH}')
        return

    print(f'App bundle: {APP_PATH}')
    utils.print_path_matches(APP_PATH, 'QtWidgets*')
    utils.print_path_matches(APP_PATH, 'QtCore*')
    utils.print_path_matches(APP_PATH, 'QtGui*')
    utils.print_path_matches(APP_PATH, 'QtWidgets*')
    utils.print_path_matches(APP_PATH, 'libshiboken*')
    _print_exiftool_diagnostic()


def _print_exiftool_diagnostic() -> None:
    paths = _bundled_exiftool_paths()
    if not paths:
        print('Bundled ExifTool: missing')
        return

    exiftool_path = paths[0]
    print(f'Bundled ExifTool: {exiftool_path}')
    utils.print_exiftool_version(exiftool_path)


def _bundled_exiftool_paths() -> list[Path]:
    if not APP_PATH.exists():
        return []

    return [
        path
        for path in sorted(APP_PATH.rglob('exiftool'))
        if path.as_posix().endswith('easy_cull/vendor/exiftool/macos/exiftool')
    ]


if __name__ == '__main__':
    raise SystemExit(main())
