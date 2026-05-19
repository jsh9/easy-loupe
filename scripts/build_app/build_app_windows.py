"""Build the distributable Windows EasyCull executable with PyInstaller."""

from __future__ import annotations

import argparse
import shutil
import subprocess  # noqa: S404 - explicit PyInstaller/ExifTool integration
import sys
import zipfile
from pathlib import Path

from PIL import Image

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.build_app import utils

APP_NAME = utils.APP_NAME
EXIFTOOL_VERSION = utils.EXIFTOOL_VERSION
REPO_ROOT = utils.REPO_ROOT
ENTRYPOINT = utils.ENTRYPOINT
ICON_SOURCE = REPO_ROOT / 'easy_cull' / 'ui' / 'assets' / 'EasyCull.png'
ICON_PATH = REPO_ROOT / 'easy_cull' / 'ui' / 'assets' / 'EasyCull.ico'
APP_DIR = REPO_ROOT / 'dist' / APP_NAME
APP_PATH = REPO_ROOT / 'dist' / APP_NAME / f'{APP_NAME}.exe'
ONEFILE_PATH = REPO_ROOT / 'dist' / f'{APP_NAME}.exe'
EXIFTOOL_CACHE_DIR = utils.EXIFTOOL_CACHE_DIR
EXIFTOOL_STAGE_DIR = REPO_ROOT / 'build' / 'exiftool' / 'windows'
EXIFTOOL_STAGE_EXE = EXIFTOOL_STAGE_DIR / 'exiftool.exe'
EXIFTOOL_STAGE_FILES = EXIFTOOL_STAGE_DIR / 'exiftool_files'
EXIFTOOL_BUNDLE_DIR = 'easy_cull/vendor/exiftool/windows'
EXIFTOOL_WINDOWS_URL = (
    'https://sourceforge.net/projects/exiftool/files/'
    f'exiftool-{EXIFTOOL_VERSION}_64.zip/download'
)
EXIFTOOL_WINDOWS_ARCHIVE = (
    EXIFTOOL_CACHE_DIR / f'exiftool-{EXIFTOOL_VERSION}_64.zip'
)


def main(argv: list[str] | None = None) -> int:
    """Build the Windows EasyCull executable or print diagnostics."""
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
    exiftool_path = ensure_exiftool_payload()
    print(f'Bundled ExifTool: {exiftool_path}')
    run_preflight_check()
    command = pyinstaller_command(
        clean=not args.no_clean,
        onefile=args.onefile,
        windowed=not args.console,
    )
    subprocess.run(command, cwd=REPO_ROOT, check=True)  # noqa: S603
    if args.onefile:
        print(ONEFILE_PATH)
    else:
        print(APP_DIR)
        print(f'Run {APP_PATH} from inside this folder.')

    return 0


def ensure_exiftool_payload() -> Path:
    """Stage the Windows ExifTool executable and support files for bundling."""
    if EXIFTOOL_STAGE_EXE.exists() and EXIFTOOL_STAGE_FILES.is_dir():
        return EXIFTOOL_STAGE_EXE

    EXIFTOOL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    utils.download_file(
        EXIFTOOL_WINDOWS_URL,
        EXIFTOOL_WINDOWS_ARCHIVE,
        message=f'Downloading ExifTool {EXIFTOOL_VERSION} for Windows...',
    )

    extract_dir = EXIFTOOL_CACHE_DIR / f'windows-{EXIFTOOL_VERSION}'
    if extract_dir.exists():
        shutil.rmtree(extract_dir)

    extract_dir.mkdir(parents=True)
    with zipfile.ZipFile(EXIFTOOL_WINDOWS_ARCHIVE) as archive:
        archive.extractall(extract_dir)

    source_exe = next(extract_dir.rglob('exiftool(-k).exe'), None)
    source_files = next(
        (
            path
            for path in extract_dir.rglob('exiftool_files')
            if path.is_dir()
        ),
        None,
    )
    if source_exe is None or source_files is None:
        raise RuntimeError(
            'Downloaded ExifTool archive has unexpected layout.'
        )

    if EXIFTOOL_STAGE_DIR.exists():
        shutil.rmtree(EXIFTOOL_STAGE_DIR)

    EXIFTOOL_STAGE_DIR.mkdir(parents=True)
    shutil.copy2(source_exe, EXIFTOOL_STAGE_EXE)
    shutil.copytree(source_files, EXIFTOOL_STAGE_FILES)
    return EXIFTOOL_STAGE_EXE


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
        *,
        clean: bool = True,
        onefile: bool = False,
        windowed: bool = True,
) -> list[str]:
    """Return the PyInstaller command for the Windows executable."""
    command = utils.pyinstaller_base_command()
    if clean:
        command.append('--clean')

    if onefile:
        command.append('--onefile')

    exiftool_path = ensure_exiftool_payload()
    command.extend(
        utils.common_pyinstaller_args(
            icon_path=ICON_PATH,
            windowed=windowed,
        )
    )
    entrypoint = command.pop()
    command.extend([
        '--add-binary',
        utils.pyinstaller_source_and_dest(exiftool_path, EXIFTOOL_BUNDLE_DIR),
        '--add-data',
        utils.pyinstaller_source_and_dest(
            EXIFTOOL_STAGE_FILES,
            f'{EXIFTOOL_BUNDLE_DIR}/exiftool_files',
        ),
        entrypoint,
    ])

    return command


def run_preflight_check() -> None:
    """Fail early when PySide6 cannot import in the build environment."""
    subprocess.run(  # noqa: S603
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
    utils.print_common_diagnostics()

    if not APP_DIR.exists():
        print(f'Dist folder missing: {APP_DIR}')
        return

    print(f'Dist folder: {APP_DIR}')
    utils.print_path_matches(APP_DIR, 'QtWidgets.pyd')
    utils.print_path_matches(APP_DIR, 'Qt6Core.dll')
    utils.print_path_matches(APP_DIR, 'Qt6Gui.dll')
    utils.print_path_matches(APP_DIR, 'Qt6Widgets.dll')
    utils.print_path_matches(APP_DIR, 'qwindows.dll')
    utils.print_path_matches(APP_DIR, 'vcruntime*.dll')
    utils.print_path_matches(APP_DIR, 'msvcp*.dll')
    _print_exiftool_diagnostic()


def _print_exiftool_diagnostic() -> None:
    exiftool_path = (
        APP_DIR
        / '_internal'
        / 'easy_cull'
        / 'vendor'
        / 'exiftool'
        / 'windows'
        / 'exiftool.exe'
    )
    print(f'Bundled ExifTool: {exiftool_path}')
    if not exiftool_path.exists():
        print('Bundled ExifTool version: missing')
        return

    utils.print_exiftool_version(exiftool_path)


if __name__ == '__main__':
    raise SystemExit(main())
