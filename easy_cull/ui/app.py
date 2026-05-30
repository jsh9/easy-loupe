"""Application entry point for EasyCull."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, Signal
from PySide6.QtGui import QFileOpenEvent
from PySide6.QtWidgets import QApplication

from easy_cull.core.records import SUPPORTED_EXTENSIONS
from easy_cull.ui.identity import (
    apply_app_identity,
    branded_argv,
    prepare_app_identity,
)
from easy_cull.ui.main_window.window import MainWindow


class EasyCullApplication(QApplication):
    """QApplication subclass that forwards OS file-open events."""

    file_opened = Signal(object)

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self._pending_open_files: list[Path] = []

    def event(self, event: QEvent) -> bool:
        """Forward macOS Finder file-open events to the main window."""
        if event.type() == QEvent.Type.FileOpen and isinstance(
            event, QFileOpenEvent
        ):
            file_path = event.file()
            if file_path:
                path = Path(file_path)
                self._pending_open_files.append(path)
                self.file_opened.emit(path)
                return True

        return super().event(event)

    def take_pending_open_files(self) -> list[Path]:
        """Return file-open events received before the window was ready."""
        pending = list(self._pending_open_files)
        self._pending_open_files.clear()
        return pending


def _extract_startup_file(argv: list[str] | None) -> Path | None:
    source_argv = argv if argv is not None else sys.argv
    for raw_arg in source_argv[1:]:
        if raw_arg.startswith('-'):
            continue

        path = Path(raw_arg).expanduser()
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            return path

    return None


def main(argv: list[str] | None = None) -> int:
    """Launch the desktop application and return the Qt exit code."""
    prepare_app_identity()
    app = EasyCullApplication(branded_argv(argv))
    apply_app_identity(app)
    startup_file = _extract_startup_file(argv)
    pending_open_files = app.take_pending_open_files()
    if startup_file is None and pending_open_files:
        startup_file = pending_open_files[0]

    window = MainWindow(startup_file=startup_file)
    app.file_opened.connect(window.open_file_from_system)
    window.showMaximized()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
