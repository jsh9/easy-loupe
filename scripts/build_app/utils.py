"""Shared helpers for EasyLoupe PyInstaller build scripts."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess  # noqa: S404 - explicit PyInstaller/ExifTool integration
import sys
import urllib.request
from importlib import metadata as importlib_metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

APP_NAME = 'EasyLoupe'
BUNDLE_IDENTIFIER = 'com.easyloupe.EasyLoupe'
EXIFTOOL_VERSION = '13.58'
REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / 'easy_loupe' / '__main__.py'
LICENSE_PATH = REPO_ROOT / 'LICENSE'
THIRD_PARTY_NOTICES_PATH = REPO_ROOT / 'THIRD_PARTY_NOTICES.md'
THIRD_PARTY_LICENSES_DIR = REPO_ROOT / 'third_party_licenses'
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
        'easy_loupe.ui.assets',
        '--copy-metadata',
        'easy-loupe',
        *runtime_metadata_args(),
        *license_data_args(),
        str(ENTRYPOINT),
    ]
    if windowed:
        args.insert(1, '--windowed')

    return args


def runtime_dependency_names(root: str = 'easy-loupe') -> list[str]:
    """
    Return the installed runtime dependency closure of ``root``, sorted.

    Requirements guarded by markers that do not apply to this build, such as
    the ``dev`` extra or another platform, are skipped, and so are dependencies
    that are not installed. Deriving the list from installed metadata keeps
    packaged license files in sync with ``pyproject.toml`` without a
    hand-maintained list.
    """
    names: set[str] = set()
    pending = [root]
    while pending:
        try:
            requirements = importlib_metadata.requires(pending.pop()) or []
        except importlib_metadata.PackageNotFoundError:
            continue

        for spec in requirements:
            requirement = Requirement(spec)
            if requirement.marker is not None and (
                not requirement.marker.evaluate({'extra': ''})
            ):
                continue

            name = canonicalize_name(requirement.name)
            if name not in names:
                names.add(name)
                pending.append(name)

    return sorted(name for name in names if _is_installed_distribution(name))


def _is_installed_distribution(name: str) -> bool:
    try:
        importlib_metadata.distribution(name)
    except importlib_metadata.PackageNotFoundError:
        return False

    return True


def runtime_metadata_args() -> list[str]:
    """
    Return PyInstaller args that bundle runtime dependency metadata.

    Each copied ``.dist-info`` folder carries that package's license files,
    which ``THIRD_PARTY_NOTICES.md`` points packaged-app users to.
    """
    args: list[str] = []
    for name in runtime_dependency_names():
        args.extend(['--copy-metadata', name])

    return args


def license_data_args() -> list[str]:
    """
    Return PyInstaller args that bundle EasyLoupe's license notices.

    ``third_party_licenses/`` holds license texts for bundled components whose
    Python package metadata does not carry them, such as the Python runtime,
    Qt, ExifTool, and native libraries inside dependency wheels.
    """
    return [
        '--add-data',
        pyinstaller_source_and_dest(LICENSE_PATH, '.'),
        '--add-data',
        pyinstaller_source_and_dest(THIRD_PARTY_NOTICES_PATH, '.'),
        '--add-data',
        pyinstaller_source_and_dest(
            THIRD_PARTY_LICENSES_DIR, THIRD_PARTY_LICENSES_DIR.name
        ),
    ]


def verify_bundled_licenses(data_dir: Path) -> None:
    """
    Fail the build when a packaged app is missing license files.

    ``data_dir`` is where PyInstaller placed data files: ``Contents/Resources``
    in the macOS app, or ``_internal`` in the Windows one-folder app.
    Inspecting the built artifact, rather than trusting the PyInstaller
    arguments, catches files that were never copied into the app.

    Raises
    ------
    RuntimeError
        If any expected license file or package metadata folder is missing.
    """
    expected_files = [
        data_dir / LICENSE_PATH.name,
        data_dir / THIRD_PARTY_NOTICES_PATH.name,
        *(
            data_dir / THIRD_PARTY_LICENSES_DIR.name / path.name
            for path in sorted(THIRD_PARTY_LICENSES_DIR.iterdir())
            if path.is_file()
        ),
    ]
    missing = [
        str(path.relative_to(data_dir))
        for path in expected_files
        if not path.is_file()
    ]
    bundled_metadata = {
        canonicalize_name(path.name.split('-', 1)[0])
        for path in data_dir.glob('*.dist-info')
    }
    missing.extend(
        f'{name} package metadata'
        for name in ['easy-loupe', *runtime_dependency_names()]
        if name not in bundled_metadata
    )
    if missing:
        raise RuntimeError(
            'Packaged app is missing license files: ' + ', '.join(missing)
        )


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
