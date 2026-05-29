from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication, QLabel

from easy_cull.ui.theme import THEMES
from easy_cull.ui.viewers.exif_overlay import (
    CopyableGpsLabel,
    ExifOverlayWidget,
)
from tests.ui._helpers import render_widget_image


def test_exif_overlay_displays_rows_and_histogram() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = ExifOverlayWidget()
    histogram = (
        tuple(1.0 if index == 255 else 0.0 for index in range(256)),
        tuple(1.0 if index == 128 else 0.0 for index in range(256)),
        tuple(1.0 if index == 0 else 0.0 for index in range(256)),
    )

    overlay.set_content(
        {
            'Camera Model': 'Z 8',
            'ISO': '800',
        },
        histogram,
    )
    overlay.show()
    app.processEvents()

    assert overlay.exif_display() == {
        'Camera Model': 'Z 8',
        'ISO': '800',
    }
    assert overlay.histogram_plot.histogram() == histogram
    assert overlay.sizeHint().width() <= overlay.width()

    image = render_widget_image(overlay)
    assert image.width() == overlay.width()
    assert image.height() == overlay.height()

    overlay.close()


def test_exif_overlay_shows_empty_exif_state() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = ExifOverlayWidget()

    overlay.set_content({}, None)
    overlay.show()
    app.processEvents()

    assert overlay.exif_display() == {}
    assert any(
        label.text() == 'No EXIF info'
        for label in overlay.findChildren(QLabel)
    )
    assert overlay.histogram_plot.histogram() is None

    overlay.close()
    del app


def test_exif_overlay_keeps_dark_translucent_style_in_light_theme() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = ExifOverlayWidget()

    overlay.set_theme(THEMES['light'])

    assert 'background-color: rgba(13, 16, 20, 190)' in (overlay.styleSheet())
    assert 'color: rgba(255, 255, 255, 235)' in overlay.styleSheet()
    assert 'text-decoration' not in overlay.styleSheet()

    overlay.close()
    del app


def test_exif_overlay_gps_value_can_copy_displayed_text() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = ExifOverlayWidget()
    gps_text = '40.712776º, -74.005974º, 12.4\u00a0m'

    overlay.set_content({'GPS': gps_text}, None)
    overlay.show()
    app.processEvents()

    gps_label = overlay.findChild(CopyableGpsLabel)
    assert gps_label is not None
    assert gps_label.text() == gps_text
    assert gps_label.alignment() == (Qt.AlignLeft | Qt.AlignTop)

    menu = gps_label.show_copy_menu(QPointF(0, 0))
    actions = menu.actions()
    assert len(actions) == 1
    assert actions[0].text() == 'Copy'
    actions[0].trigger()

    assert QApplication.clipboard().text() == gps_text

    menu.close()
    overlay.close()
    del app
