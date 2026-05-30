"""Folder access policy for system-opened photo files."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from easy_cull.ui.identity import APP_NAME

APPROVED_ROOTS_SETTINGS_KEY = 'photo_viewer/approved_roots'
COMMON_MAC_PARENT_NAMES = frozenset({
    'Desktop',
    'Documents',
    'Downloads',
    'Dropbox',
    'Movies',
    'Pictures',
})


class FolderAccessManager:
    """Manage user-approved roots for photo-viewer folder navigation."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = (
            settings if settings is not None else QSettings(APP_NAME, APP_NAME)
        )

    def ensure_access_for_file(
            self, file_path: Path, parent: QWidget | None = None
    ) -> bool:
        """
        Return whether EasyCull may scan the opened file's folder.

        Unsandboxed non-macOS builds can scan normally. On macOS we keep an
        app-level record of approved ancestor folders so the user sees our
        folder prompt only once per top-level location.
        """
        if sys.platform != 'darwin':
            return True

        resolved_file = file_path.expanduser().resolve()
        if self.is_file_approved(resolved_file):
            return True

        suggested_root = self.suggest_access_root(resolved_file)
        selected = QFileDialog.getExistingDirectory(
            parent,
            'Allow EasyCull to Browse This Folder',
            str(suggested_root),
        )
        if not selected:
            return False

        selected_root = Path(selected).expanduser().resolve()
        if not self._contains(selected_root, resolved_file.parent):
            QMessageBox.warning(
                parent,
                'Folder Access Not Granted',
                (
                    'Choose the opened photo folder or one of its parent'
                    ' folders to enable adjacent-photo navigation.'
                ),
            )
            return False

        self.add_approved_root(selected_root)
        return True

    def is_file_approved(self, file_path: Path) -> bool:
        """Return True when a file is inside a stored approved root."""
        resolved_parent = file_path.expanduser().resolve().parent
        return any(
            self._contains(root, resolved_parent)
            for root in self.approved_roots()
        )

    def approved_roots(self) -> list[Path]:
        """Return stored approved roots as existing absolute paths."""
        value = self._settings.value(APPROVED_ROOTS_SETTINGS_KEY, [])
        if isinstance(value, str):
            raw_roots = [value]
        elif isinstance(value, list):
            raw_roots = [str(item) for item in value]
        else:
            raw_roots = []

        roots: list[Path] = []
        for raw_root in raw_roots:
            try:
                root = Path(raw_root).expanduser().resolve()
            except OSError:
                continue

            if root.is_dir():
                roots.append(root)

        return roots

    def add_approved_root(self, root: Path) -> None:
        """Persist an approved root unless an existing root covers it."""
        resolved_root = root.expanduser().resolve()
        roots = self.approved_roots()
        if any(self._contains(existing, resolved_root) for existing in roots):
            return

        filtered_roots = [
            existing
            for existing in roots
            if not self._contains(resolved_root, existing)
        ]
        filtered_roots.append(resolved_root)
        self._settings.setValue(
            APPROVED_ROOTS_SETTINGS_KEY,
            [str(path) for path in filtered_roots],
        )

    @staticmethod
    def suggest_access_root(file_path: Path) -> Path:
        """Suggest a stable parent root for a system-opened photo."""
        resolved_file = file_path.expanduser().resolve()
        home = Path.home().expanduser().resolve()
        try:
            relative = resolved_file.relative_to(home)
        except ValueError:
            return resolved_file.parent

        if relative.parts and relative.parts[0] in COMMON_MAC_PARENT_NAMES:
            return home / relative.parts[0]

        return resolved_file.parent

    @staticmethod
    def _contains(root: Path, path: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return path == root

        return True
