from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QSettings

import easy_cull.ui.folder_access as folder_access_module

if TYPE_CHECKING:
    from pathlib import Path


def _settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat)


def test_folder_access_manager_persists_and_matches_approved_roots(
        tmp_path: Path,
) -> None:
    manager = folder_access_module.FolderAccessManager(_settings(tmp_path))
    root = tmp_path / 'Desktop'
    nested = root / 'Shoot' / 'Selects'
    nested.mkdir(parents=True)
    photo = nested / 'IMG_1000.JPG'
    photo.write_bytes(b'jpg')

    manager.add_approved_root(root)

    assert manager.is_file_approved(photo) is True
    assert manager.approved_roots() == [root.resolve()]


def test_folder_access_manager_suggests_common_home_parent(
        tmp_path: Path, monkeypatch: Any
) -> None:
    home = tmp_path / 'home'
    photo = home / 'Downloads' / 'Shoot' / 'IMG_1000.JPG'
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b'jpg')
    monkeypatch.setattr(folder_access_module.Path, 'home', lambda: home)

    assert (
        folder_access_module.FolderAccessManager.suggest_access_root(photo)
        == home / 'Downloads'
    )


@pytest.mark.parametrize('provider', ['Dropbox', 'OneDrive'])
def test_folder_access_manager_suggests_cloud_storage_provider_root(
        tmp_path: Path, monkeypatch: Any, provider: str
) -> None:
    """
    Resolve deeply nested File Provider photos to the provider root.

    This keeps Dropbox, OneDrive, and similar roots eligible for a macOS prompt
    instead of falling back to a one-off nested folder chooser.
    """
    home = tmp_path / 'home'
    photo = (
        home
        / 'Library'
        / 'CloudStorage'
        / provider
        / 'Shoots'
        / 'Trip'
        / 'IMG_1000.JPG'
    )
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b'jpg')
    monkeypatch.setattr(folder_access_module.Path, 'home', lambda: home)

    assert (
        folder_access_module.FolderAccessManager.suggest_access_root(photo)
        == home / 'Library' / 'CloudStorage' / provider
    )


def test_folder_access_manager_prompts_only_on_macos(
        tmp_path: Path, monkeypatch: Any
) -> None:
    manager = folder_access_module.FolderAccessManager(_settings(tmp_path))
    photo = tmp_path / 'Shoot' / 'IMG_1000.JPG'
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b'jpg')
    monkeypatch.setattr(folder_access_module.sys, 'platform', 'linux')

    assert manager.ensure_access_for_file(photo) is True


def test_folder_access_manager_uses_tcc_prompt_for_standard_root(
        tmp_path: Path, monkeypatch: Any
) -> None:
    manager = folder_access_module.FolderAccessManager(_settings(tmp_path))
    home = tmp_path / 'home'
    root = home / 'Documents'
    photo = root / 'Shoot' / 'IMG_1000.JPG'
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b'jpg')
    monkeypatch.setattr(folder_access_module.sys, 'platform', 'darwin')
    monkeypatch.setattr(folder_access_module.Path, 'home', lambda: home)
    monkeypatch.setattr(
        manager, '_confirm_access_root', lambda _parent, path: path == root
    )
    monkeypatch.setattr(
        manager,
        '_probe_folder_access',
        lambda path: path == root,
    )

    def fail_folder_chooser(*_args: object) -> str:
        raise AssertionError('folder chooser should not open')

    monkeypatch.setattr(
        folder_access_module.QFileDialog,
        'getExistingDirectory',
        fail_folder_chooser,
    )

    assert manager.ensure_access_for_file(photo) is True
    assert manager.approved_roots() == [root.resolve()]


def test_folder_access_manager_uses_macos_prompt_for_cloud_storage_root(
        tmp_path: Path, monkeypatch: Any
) -> None:
    """
    Use the OS-prompt path for File Provider roots.

    CloudStorage access should probe the provider root directly so macOS can
    grant access, and must not open EasyCull's native folder chooser first.
    """
    manager = folder_access_module.FolderAccessManager(_settings(tmp_path))
    home = tmp_path / 'home'
    root = home / 'Library' / 'CloudStorage' / 'Dropbox'
    photo = root / 'Shoot' / 'IMG_1000.JPG'
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b'jpg')
    monkeypatch.setattr(folder_access_module.sys, 'platform', 'darwin')
    monkeypatch.setattr(folder_access_module.Path, 'home', lambda: home)
    monkeypatch.setattr(
        manager, '_confirm_access_root', lambda _parent, path: path == root
    )
    monkeypatch.setattr(
        manager,
        '_probe_folder_access',
        lambda path: path == root,
    )

    def fail_folder_chooser(*_args: object) -> str:
        raise AssertionError('folder chooser should not open')

    monkeypatch.setattr(
        folder_access_module.QFileDialog,
        'getExistingDirectory',
        fail_folder_chooser,
    )

    assert manager.ensure_access_for_file(photo) is True
    assert manager.approved_roots() == [root.resolve()]


def test_folder_access_manager_cloud_storage_denial_leaves_root_unapproved(
        tmp_path: Path, monkeypatch: Any
) -> None:
    """
    Avoid persisting File Provider roots when macOS denies the probe.

    Persisting only after a successful probe keeps EasyCull's approved-root
    preference aligned with actual OS access.
    """
    manager = folder_access_module.FolderAccessManager(_settings(tmp_path))
    home = tmp_path / 'home'
    root = home / 'Library' / 'CloudStorage' / 'OneDrive'
    photo = root / 'Shoot' / 'IMG_1000.JPG'
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b'jpg')
    monkeypatch.setattr(folder_access_module.sys, 'platform', 'darwin')
    monkeypatch.setattr(folder_access_module.Path, 'home', lambda: home)
    monkeypatch.setattr(
        manager, '_confirm_access_root', lambda _parent, _path: True
    )
    monkeypatch.setattr(manager, '_probe_folder_access', lambda _path: False)

    assert manager.ensure_access_for_file(photo) is False
    assert manager.approved_roots() == []


def test_folder_access_manager_tcc_denial_leaves_root_unapproved(
        tmp_path: Path, monkeypatch: Any
) -> None:
    manager = folder_access_module.FolderAccessManager(_settings(tmp_path))
    home = tmp_path / 'home'
    root = home / 'Desktop'
    photo = root / 'Shoot' / 'IMG_1000.JPG'
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b'jpg')
    monkeypatch.setattr(folder_access_module.sys, 'platform', 'darwin')
    monkeypatch.setattr(folder_access_module.Path, 'home', lambda: home)
    monkeypatch.setattr(
        manager, '_confirm_access_root', lambda _parent, _path: True
    )
    monkeypatch.setattr(manager, '_probe_folder_access', lambda _path: False)

    assert manager.ensure_access_for_file(photo) is False
    assert manager.approved_roots() == []


def test_folder_access_manager_nonstandard_root_uses_native_folder_chooser(
        tmp_path: Path, monkeypatch: Any
) -> None:
    manager = folder_access_module.FolderAccessManager(_settings(tmp_path))
    root = tmp_path / 'Documents'
    photo = root / 'Shoot' / 'IMG_1000.JPG'
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b'jpg')
    monkeypatch.setattr(folder_access_module.sys, 'platform', 'darwin')
    monkeypatch.setattr(
        manager, '_confirm_access_root', lambda _parent, path: path == root
    )
    monkeypatch.setattr(
        manager, '_select_access_root', lambda _parent, path: path
    )
    monkeypatch.setattr(
        manager, 'suggest_access_root', lambda _file_path: root
    )
    probe_calls: list[Path] = []
    monkeypatch.setattr(manager, '_probe_folder_access', probe_calls.append)

    assert manager.ensure_access_for_file(photo) is True
    assert manager.approved_roots() == [root.resolve()]
    assert probe_calls == []


def test_folder_access_manager_confirm_cancel_leaves_root_unapproved(
        tmp_path: Path, monkeypatch: Any
) -> None:
    manager = folder_access_module.FolderAccessManager(_settings(tmp_path))
    root = tmp_path / 'Documents'
    photo = root / 'Shoot' / 'IMG_1000.JPG'
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b'jpg')
    monkeypatch.setattr(folder_access_module.sys, 'platform', 'darwin')
    monkeypatch.setattr(
        manager, '_confirm_access_root', lambda _parent, _path: False
    )
    monkeypatch.setattr(
        manager, 'suggest_access_root', lambda _file_path: root
    )

    assert manager.ensure_access_for_file(photo) is False
    assert manager.approved_roots() == []


def test_folder_access_manager_native_cancel_leaves_root_unapproved(
        tmp_path: Path, monkeypatch: Any
) -> None:
    manager = folder_access_module.FolderAccessManager(_settings(tmp_path))
    root = tmp_path / 'Project'
    photo = root / 'Shoot' / 'IMG_1000.JPG'
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b'jpg')
    monkeypatch.setattr(folder_access_module.sys, 'platform', 'darwin')
    monkeypatch.setattr(
        manager, '_confirm_access_root', lambda _parent, _path: True
    )
    monkeypatch.setattr(
        manager, '_select_access_root', lambda _parent, _path: None
    )
    monkeypatch.setattr(
        manager, 'suggest_access_root', lambda _file_path: root
    )

    assert manager.ensure_access_for_file(photo) is False
    assert manager.approved_roots() == []


def test_folder_access_manager_invalid_native_root_is_rejected(
        tmp_path: Path, monkeypatch: Any
) -> None:
    manager = folder_access_module.FolderAccessManager(_settings(tmp_path))
    root = tmp_path / 'Project'
    invalid_root = tmp_path / 'Other'
    photo = root / 'Shoot' / 'IMG_1000.JPG'
    photo.parent.mkdir(parents=True)
    invalid_root.mkdir()
    photo.write_bytes(b'jpg')
    monkeypatch.setattr(folder_access_module.sys, 'platform', 'darwin')
    monkeypatch.setattr(
        manager, '_confirm_access_root', lambda _parent, _path: True
    )
    monkeypatch.setattr(
        manager, '_select_access_root', lambda _parent, _path: invalid_root
    )
    monkeypatch.setattr(
        manager, 'suggest_access_root', lambda _file_path: root
    )
    warning_calls: list[str] = []
    monkeypatch.setattr(
        folder_access_module.QMessageBox,
        'warning',
        lambda *_args: warning_calls.append('warning'),
    )

    assert manager.ensure_access_for_file(photo) is False
    assert manager.approved_roots() == []
    assert warning_calls == ['warning']
