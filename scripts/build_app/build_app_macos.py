"""Build the distributable macOS EasyCull.app with PyInstaller."""

from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess  # noqa: S404 - explicit PyInstaller/ExifTool integration
import sys
import tarfile
from pathlib import Path

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.build_app import utils
from easy_cull.core.records import SUPPORTED_EXTENSIONS

APP_NAME = utils.APP_NAME
BUNDLE_IDENTIFIER = utils.BUNDLE_IDENTIFIER
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
PYSIDE_TOOL_APP_NAMES = ('Assistant', 'Designer', 'Linguist')
PRIVACY_USAGE_DESCRIPTIONS = {
    'NSDesktopFolderUsageDescription': (
        'EasyCull needs access to Desktop photo folders so you can navigate'
        ' adjacent photos opened from Finder.'
    ),
    'NSDocumentsFolderUsageDescription': (
        'EasyCull needs access to Documents photo folders so you can navigate'
        ' adjacent photos opened from Finder.'
    ),
    'NSDownloadsFolderUsageDescription': (
        'EasyCull needs access to Downloads photo folders so you can navigate'
        ' adjacent photos opened from Finder.'
    ),
    'NSRemovableVolumesUsageDescription': (
        'EasyCull needs access to removable photo volumes so you can review'
        ' and cull imported shoots.'
    ),
    'NSNetworkVolumesUsageDescription': (
        'EasyCull needs access to network photo volumes so you can review'
        ' and cull shared shoots.'
    ),
}


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
    remove_bundled_pyside_tool_apps()
    inject_info_plist_metadata()
    sign_app_bundle()
    verify_app_signature()
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
        '--osx-bundle-identifier',
        BUNDLE_IDENTIFIER,
    ])
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


def remove_bundled_pyside_tool_apps(app_path: Path = APP_PATH) -> None:
    """Remove unused Qt utility apps that break strict bundle verification."""
    for base in (
            app_path / 'Contents' / 'Frameworks' / 'PySide6',
            app_path / 'Contents' / 'Resources' / 'PySide6',
    ):
        for app_name in PYSIDE_TOOL_APP_NAMES:
            for candidate in (
                    base / f'{app_name}.app',
                    base / f'{app_name}__dot__app',
            ):
                if candidate.is_symlink() or candidate.is_file():
                    candidate.unlink()
                elif candidate.exists():
                    shutil.rmtree(candidate)


def document_type_entry() -> dict[str, object]:
    """Return the macOS document type registration for supported photos."""
    return {
        'CFBundleTypeExtensions': [
            extension.removeprefix('.')
            for extension in sorted(SUPPORTED_EXTENSIONS)
        ],
        'CFBundleTypeIconFile': ICON_PATH.name,
        'CFBundleTypeName': 'EasyCull Photo',
        'CFBundleTypeRole': 'Viewer',
        'LSHandlerRank': 'Alternate',
    }


def inject_info_plist_metadata(app_path: Path = APP_PATH) -> None:
    """Add EasyCull macOS bundle metadata to the built app plist."""
    info_plist = app_path / 'Contents' / 'Info.plist'
    if not info_plist.exists():
        raise FileNotFoundError(f'Info.plist missing: {info_plist}')

    with info_plist.open('rb') as file:
        payload = plistlib.load(file)

    payload['CFBundleIdentifier'] = BUNDLE_IDENTIFIER
    payload['CFBundleDocumentTypes'] = [document_type_entry()]
    payload.update(PRIVACY_USAGE_DESCRIPTIONS)
    with info_plist.open('wb') as file:
        plistlib.dump(payload, file)


def sign_app_bundle(app_path: Path = APP_PATH) -> None:
    """Ad-hoc sign the app after post-build plist and file mutations."""
    subprocess.run(  # noqa: S603 - fixed macOS signing command
        ['codesign', '--force', '--deep', '--sign', '-', str(app_path)],
        check=True,
    )


def verify_app_signature(app_path: Path = APP_PATH) -> None:
    """Verify the app signature and bundle identifier after signing."""
    subprocess.run(  # noqa: S603 - fixed macOS verification command
        [
            'codesign',
            '--verify',
            '--deep',
            '--strict',
            '--verbose=4',
            str(app_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(  # noqa: S603 - fixed macOS diagnostic command
        ['codesign', '-dv', '--verbose=4', str(app_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    identity_output = result.stderr or result.stdout
    expected = f'Identifier={BUNDLE_IDENTIFIER}'
    if expected not in identity_output:
        raise RuntimeError(
            f'Expected signed bundle identifier {BUNDLE_IDENTIFIER!r}.'
        )


def inject_document_types(app_path: Path = APP_PATH) -> None:
    """Backward-compatible wrapper for old tests and scripts."""
    inject_info_plist_metadata(app_path)


def print_diagnostics() -> None:
    """Print diagnostics for investigating macOS packaging failures."""
    utils.print_common_diagnostics()

    if not APP_PATH.exists():
        print(f'App bundle missing: {APP_PATH}')
        return

    print(f'App bundle: {APP_PATH}')
    _print_info_plist_diagnostic()
    _print_signing_diagnostic()
    utils.print_path_matches(APP_PATH, 'QtWidgets*')
    utils.print_path_matches(APP_PATH, 'QtCore*')
    utils.print_path_matches(APP_PATH, 'QtGui*')
    utils.print_path_matches(APP_PATH, 'QtWidgets*')
    utils.print_path_matches(APP_PATH, 'libshiboken*')
    _print_exiftool_diagnostic()


def _print_info_plist_diagnostic() -> None:
    info_plist = APP_PATH / 'Contents' / 'Info.plist'
    if not info_plist.exists():
        return

    with info_plist.open('rb') as file:
        payload = plistlib.load(file)

    print(f'Bundle ID: {payload.get("CFBundleIdentifier", "missing")}')
    document_types = payload.get('CFBundleDocumentTypes', [])
    print(f'Document types: {len(document_types)}')
    for key in sorted(PRIVACY_USAGE_DESCRIPTIONS):
        print(f'{key}: {"present" if payload.get(key) else "missing"}')


def _print_signing_diagnostic() -> None:
    try:
        verify_result = subprocess.run(  # noqa: S603 - known diagnostic path
            [
                'codesign',
                '--verify',
                '--deep',
                '--strict',
                '--verbose=4',
                str(APP_PATH),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        print(f'codesign verify: unavailable: {error}')
    else:
        if getattr(verify_result, 'returncode', 0) == 0:
            print('codesign verify: ok')
        else:
            output = (
                verify_result.stderr or verify_result.stdout
                or 'unknown error'
            )
            print(f'codesign verify: failed: {output.strip()}')

    try:
        result = subprocess.run(  # noqa: S603 - known diagnostic path
            ['codesign', '-dv', '--verbose=4', str(APP_PATH)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        print(f'codesign: unavailable: {error}')
        return

    signing_output = result.stderr or result.stdout
    for line in signing_output.splitlines():
        if line.startswith(('Identifier=', 'Signature=', 'TeamIdentifier=')):
            print(f'codesign {line}')

    try:
        entitlements = subprocess.run(  # noqa: S603 - known diagnostic path
            ['codesign', '-d', '--entitlements', ':-', str(APP_PATH)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        print(f'codesign entitlements: unavailable: {error}')
        return

    entitlement_output = entitlements.stdout.strip()
    if entitlement_output:
        print('Entitlements: present')
    else:
        print('Entitlements: none')


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
