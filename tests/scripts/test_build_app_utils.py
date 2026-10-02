from __future__ import annotations

import re
import shutil
from importlib import metadata as importlib_metadata
from typing import TYPE_CHECKING

import pytest

from scripts.build_app import utils

if TYPE_CHECKING:
    from pathlib import Path

_FAKE_REQUIREMENTS = {
    'easy-loupe': [
        'Pillow>=10',
        'rawpy',
        'pytest>=8; extra == "dev"',
        'legacy-backport; python_version < "3.0"',
        'missing-dist',
    ],
    'rawpy': ['numpy>=1.26'],
    'numpy': [],
    'pillow': ['numpy'],
}


def _fake_requires(name: str) -> list[str]:
    if name not in _FAKE_REQUIREMENTS:
        raise importlib_metadata.PackageNotFoundError(name)

    return _FAKE_REQUIREMENTS[name]


def _fake_distribution(name: str) -> object:
    if name not in _FAKE_REQUIREMENTS:
        raise importlib_metadata.PackageNotFoundError(name)

    return object()


def test_collect_runtime_dependency_names_walks_installed_runtime_closure(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify packaged license metadata covers exactly the runtime closure.

    Packaged apps bundle each runtime dependency's ``.dist-info`` so its
    license files ship with the app. The walk must follow transitive
    requirements, normalize names, skip dev extras and markers that do not
    apply, and ignore distributions that are not installed, or PyInstaller
    would fail on a missing package or bundle dev-only tooling.
    """
    monkeypatch.setattr(utils.importlib_metadata, 'requires', _fake_requires)
    monkeypatch.setattr(
        utils.importlib_metadata, 'distribution', _fake_distribution
    )

    assert utils.collect_runtime_dependency_names() == [
        'numpy',
        'pillow',
        'rawpy',
    ]
    assert utils.build_runtime_metadata_args() == [
        '--copy-metadata',
        'numpy',
        '--copy-metadata',
        'pillow',
        '--copy-metadata',
        'rawpy',
    ]


def _write_complete_license_bundle(data_dir: Path) -> None:
    """Populate ``data_dir`` like a packaged app's data folder."""
    data_dir.mkdir()
    shutil.copy2(utils.LICENSE_PATH, data_dir)
    shutil.copy2(utils.THIRD_PARTY_NOTICES_PATH, data_dir)
    shutil.copytree(
        utils.THIRD_PARTY_LICENSES_DIR, data_dir / 'third_party_licenses'
    )
    for dist_info in ('easy_loupe-1.0.dist-info', 'Pillow-12.0.dist-info'):
        (data_dir / dist_info).mkdir()


def test_verify_bundled_licenses_accepts_complete_bundle(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify a packaged app with every license file passes the build check.

    Metadata folder names are matched after name normalization, because wheels
    spell distribution names inconsistently (``Pillow``, ``easy_loupe``).
    """
    monkeypatch.setattr(
        utils, 'collect_runtime_dependency_names', lambda: ['pillow']
    )
    data_dir = tmp_path / 'Resources'
    _write_complete_license_bundle(data_dir)

    utils.verify_bundled_licenses(data_dir)


def test_verify_bundled_licenses_reports_every_missing_file(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify the build fails and names each missing license file.

    The check inspects the built app rather than the PyInstaller arguments, so
    a license text or package metadata folder that never reached the app must
    stop the build instead of shipping an incomplete app. Paths use forward
    slashes on every OS so Windows build errors read the same.
    """
    monkeypatch.setattr(
        utils, 'collect_runtime_dependency_names', lambda: ['pillow']
    )
    data_dir = tmp_path / 'Resources'
    _write_complete_license_bundle(data_dir)
    (data_dir / 'third_party_licenses' / 'Python.txt').unlink()
    shutil.rmtree(data_dir / 'Pillow-12.0.dist-info')

    with pytest.raises(RuntimeError) as error:
        utils.verify_bundled_licenses(data_dir)

    message = str(error.value)
    assert 'third_party_licenses/Python.txt' in message
    assert 'pillow package metadata' in message


def test_third_party_notices_reference_every_bundled_license_text() -> None:
    """
    Verify ``THIRD_PARTY_NOTICES.md`` and ``third_party_licenses/`` agree.

    Every curated license text must be listed in the notices, and every text
    the notices point to must exist, so users are never sent to a file the
    packaged app does not contain.
    """
    notices = utils.THIRD_PARTY_NOTICES_PATH.read_text(encoding='utf-8')
    referenced = set(
        re.findall(r'third_party_licenses/([\w.-]+\.txt)', notices)
    )
    bundled = {path.name for path in utils.list_third_party_license_texts()}

    assert referenced == bundled


def test_license_checks_ignore_non_license_files_in_licenses_folder(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify OS-created files in ``third_party_licenses/`` are not required.

    Opening the folder in macOS Finder can create ``.DS_Store``. Treating it as
    a license text would fail the notices check and make every build require
    that file inside the packaged app.
    """
    licenses_dir = tmp_path / 'third_party_licenses'
    shutil.copytree(utils.THIRD_PARTY_LICENSES_DIR, licenses_dir)
    (licenses_dir / '.DS_Store').write_bytes(b'finder')
    monkeypatch.setattr(utils, 'THIRD_PARTY_LICENSES_DIR', licenses_dir)
    monkeypatch.setattr(
        utils, 'collect_runtime_dependency_names', lambda: ['pillow']
    )
    data_dir = tmp_path / 'Resources'
    _write_complete_license_bundle(data_dir)
    (data_dir / 'third_party_licenses' / '.DS_Store').unlink()

    assert '.DS_Store' not in {
        path.name for path in utils.list_third_party_license_texts()
    }
    utils.verify_bundled_licenses(data_dir)
