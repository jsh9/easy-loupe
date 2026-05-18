"""Application entry point for EasyCull."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from easy_cull.ui.identity import (
    apply_app_identity,
    branded_argv,
    prepare_app_identity,
)
from easy_cull.ui.main_window.window import MainWindow


def main(argv: list[str] | None = None) -> int:
    """Launch the desktop application and return the Qt exit code."""
    prepare_app_identity()
    app = QApplication(branded_argv(argv))
    apply_app_identity(app)
    window = MainWindow()
    window.showMaximized()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
