from __future__ import annotations

from importlib import metadata as importlib_metadata
from typing import TYPE_CHECKING

from scripts.build_app import utils

if TYPE_CHECKING:
    import pytest

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


def test_runtime_dependency_names_walks_installed_runtime_closure(
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

    assert utils.runtime_dependency_names() == ['numpy', 'pillow', 'rawpy']
    assert utils.runtime_metadata_args() == [
        '--copy-metadata',
        'numpy',
        '--copy-metadata',
        'pillow',
        '--copy-metadata',
        'rawpy',
    ]
