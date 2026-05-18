"""Application entry point for EasyCull."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from easy_cull.ui.main_window.window import MainWindow


def main(argv: list[str] | None = None) -> int:
    """Launch the desktop application and return the Qt exit code."""
    app = QApplication(argv or sys.argv)
    window = MainWindow()
    window.showMaximized()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
