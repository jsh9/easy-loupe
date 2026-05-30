"""Folder access policy for system-opened photo files."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox, QWidget

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
        if not self._confirm_access_root(parent, suggested_root):
            return False

        self.add_approved_root(suggested_root)
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

    def _confirm_access_root(self, parent: QWidget | None, root: Path) -> bool:
        dialog = QMessageBox(parent)
        dialog.setWindowTitle('Allow Folder Access?')
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText(
            f'Allow EasyCull to browse photos under {self.display_path(root)}?'
        )
        dialog.setInformativeText(
            'This lets the photo viewer navigate adjacent photos in that'
            ' folder tree without asking again.'
        )
        allow_button = dialog.addButton(
            'Allow', QMessageBox.ButtonRole.AcceptRole
        )
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(allow_button)
        dialog.exec()
        return dialog.clickedButton() is allow_button

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
    def display_path(path: Path) -> str:
        """Return a compact user-facing form of a path."""
        resolved_path = path.expanduser().resolve()
        home = Path.home().expanduser().resolve()
        try:
            relative = resolved_path.relative_to(home)
        except ValueError:
            return str(resolved_path)

        return '~' if not relative.parts else f'~/{relative}'

    @staticmethod
    def _contains(root: Path, path: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return path == root

        return True
