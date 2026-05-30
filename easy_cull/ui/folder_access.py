"""Folder access policy for system-opened photo files."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from easy_cull.ui.identity import APP_NAME

APPROVED_ROOTS_SETTINGS_KEY = 'photo_viewer/approved_roots'
MACOS_CLOUD_STORAGE_DIR = 'Library/CloudStorage'
COMMON_MAC_PARENT_NAMES = frozenset({
    'Desktop',
    'Documents',
    'Downloads',
    'Dropbox',
    'Movies',
    'Pictures',
})
STANDARD_TCC_PARENT_NAMES = frozenset({
    'Desktop',
    'Documents',
    'Downloads',
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

        return self.request_access_for_file(resolved_file, parent)

    def request_access_for_file(
            self, file_path: Path, parent: QWidget | None = None
    ) -> bool:
        """Prompt for and persist folder access when macOS allows scanning."""
        resolved_file = file_path.expanduser().resolve()
        suggested_root = self.suggest_access_root(resolved_file)
        if not self._confirm_access_root(parent, suggested_root):
            return False

        if self.is_macos_promptable_root(suggested_root):
            if not self._probe_folder_access(suggested_root):
                return False

            self.add_approved_root(suggested_root)
            return True

        return self._request_native_folder_access(
            resolved_file,
            suggested_root,
            parent,
        )

    def _request_native_folder_access(
            self,
            file_path: Path,
            suggested_root: Path,
            parent: QWidget | None,
    ) -> bool:
        """Prompt for and persist a native folder-selection grant."""
        selected_root = self._select_access_root(parent, suggested_root)
        if selected_root is None:
            return False

        if not self._contains(selected_root, file_path.parent):
            QMessageBox.warning(
                parent,
                'Folder Access Not Granted',
                (
                    'Choose the suggested folder or one of its parent folders'
                    ' to enable adjacent-photo navigation.'
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

    def _confirm_access_root(self, parent: QWidget | None, root: Path) -> bool:
        dialog = QMessageBox(parent)
        dialog.setWindowTitle('Allow Folder Access?')
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText(
            f'Allow EasyCull to browse photos under {self.display_path(root)}?'
        )
        allow_button = dialog.addButton(
            'Allow', QMessageBox.ButtonRole.AcceptRole
        )
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(allow_button)
        if self.is_macos_promptable_root(root):
            dialog.setInformativeText(
                'macOS may show a privacy or cloud-file-provider prompt after'
                ' you click Allow. This lets EasyCull navigate adjacent photos'
                ' in that folder tree without asking again.'
            )
        else:
            dialog.setInformativeText(
                'macOS requires selecting this folder once. This lets'
                ' EasyCull navigate adjacent photos in that folder tree'
                ' without asking again.'
            )

        dialog.exec()
        return dialog.clickedButton() is allow_button

    @staticmethod
    def _probe_folder_access(root: Path) -> bool:
        """
        Return True when macOS allows directory scanning for a root.

        On promptable macOS roots this read is what triggers the native TCC or
        File Provider prompt for builds with a valid bundle ID.
        """
        try:
            iterator = root.iterdir()
            try:
                next(iterator, None)
            finally:
                iterator.close()
        except PermissionError:
            return False

        return True

    @staticmethod
    def _select_access_root(
            parent: QWidget | None, suggested_root: Path
    ) -> Path | None:
        selected = QFileDialog.getExistingDirectory(
            parent,
            'Grant EasyCull Folder Access',
            str(suggested_root),
        )
        if not selected:
            return None

        return Path(selected).expanduser().resolve()

    @staticmethod
    def suggest_access_root(file_path: Path) -> Path:
        """Suggest a stable parent root for a system-opened photo."""
        resolved_file = file_path.expanduser().resolve()
        home = Path.home().expanduser().resolve()
        try:
            relative = resolved_file.relative_to(home)
        except ValueError:
            return resolved_file.parent

        cloud_root = FolderAccessManager._cloud_storage_provider_root(
            home, relative
        )
        if cloud_root is not None:
            return cloud_root

        if relative.parts and relative.parts[0] in COMMON_MAC_PARENT_NAMES:
            return home / relative.parts[0]

        return resolved_file.parent

    @staticmethod
    def is_standard_tcc_root(root: Path) -> bool:
        """Return True for home Desktop/Documents/Downloads roots."""
        relative = FolderAccessManager._relative_to_home(root)
        if relative is None:
            return False

        return len(relative.parts) == 1 and (
            relative.parts[0] in STANDARD_TCC_PARENT_NAMES
        )

    @staticmethod
    def is_macos_promptable_root(root: Path) -> bool:
        """Return True for roots that can use a macOS permission prompt."""
        if FolderAccessManager.is_standard_tcc_root(root):
            return True

        relative = FolderAccessManager._relative_to_home(root)
        if relative is None:
            return False

        return (
            FolderAccessManager._cloud_storage_provider_root(
                Path.home().expanduser().resolve(), relative
            )
            == root.expanduser().resolve()
        )

    @staticmethod
    def _relative_to_home(path: Path) -> Path | None:
        resolved_path = path.expanduser().resolve()
        home = Path.home().expanduser().resolve()
        try:
            relative = resolved_path.relative_to(home)
        except ValueError:
            return None

        return relative

    @staticmethod
    def _cloud_storage_provider_root(
            home: Path, relative: Path
    ) -> Path | None:
        cloud_parts = tuple(Path(MACOS_CLOUD_STORAGE_DIR).parts)
        if (
            len(relative.parts) <= len(cloud_parts)
            or relative.parts[: len(cloud_parts)] != cloud_parts
        ):
            return None

        # File Provider roots live one level below CloudStorage. Return that
        # provider root so one OS grant covers nested Dropbox/OneDrive shoots.
        return home.joinpath(*relative.parts[: len(cloud_parts) + 1])

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
