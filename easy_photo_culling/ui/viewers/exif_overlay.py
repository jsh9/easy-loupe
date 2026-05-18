"""EXIF overlay widget stubs for future viewer enhancements."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget


class ExifOverlayWidget(QWidget):
    """
    Semi-transparent EXIF info panel floating over the photo viewer.

    Planned feature (future implementation):
    - Displays camera, lens, aperture, shutter, ISO, focal length.
    - Populated via exif.format_exif_display() when a photo is loaded.
    - Toggled on/off with a keyboard shortcut (TBD, e.g. 'I').
    - Hidden automatically in browse mode.
    - Fades in/out using QPropertyAnimation on the windowOpacity property.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # TODO: implement EXIF overlay rendering  # noqa: TD003
        self.hide()
