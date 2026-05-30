from __future__ import annotations

from typing import TYPE_CHECKING, Any

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


def test_folder_access_manager_prompts_only_on_macos(
        tmp_path: Path, monkeypatch: Any
) -> None:
    manager = folder_access_module.FolderAccessManager(_settings(tmp_path))
    photo = tmp_path / 'Shoot' / 'IMG_1000.JPG'
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b'jpg')
    monkeypatch.setattr(folder_access_module.sys, 'platform', 'linux')

    assert manager.ensure_access_for_file(photo) is True
