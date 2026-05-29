"""Semi-transparent EXIF and histogram overlay for the photo viewer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from easy_cull.core.histogram import HISTOGRAM_CHANNEL_SIZE, RGBHistogram
from easy_cull.ui.theme import THEMES, ThemePalette

if TYPE_CHECKING:
    from PySide6.QtGui import QPaintEvent

OVERLAY_WIDTH = 360
HISTOGRAM_HEIGHT = 132
OVERLAY_PADDING = 12
HISTOGRAM_CHANNEL_COLORS = (
    QColor(255, 70, 70, 150),
    QColor(90, 220, 115, 150),
    QColor(80, 145, 255, 150),
)
MIN_EXIF_ROW_HEIGHT = 20


class HistogramPlotWidget(QWidget):
    """Paint a combined semi-transparent RGB histogram plot."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._histogram: RGBHistogram | None = None
        self._background_color = QColor(0, 0, 0, 65)
        self._border_color = QColor(255, 255, 255, 55)
        self._text_color = QColor(255, 255, 255, 170)
        self.setFixedHeight(HISTOGRAM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_histogram(self, histogram: RGBHistogram | None) -> None:
        """Set normalized RGB histogram data and schedule a repaint."""
        self._histogram = histogram
        self.update()

    def histogram(self) -> RGBHistogram | None:
        """Return the currently displayed histogram payload."""
        return self._histogram

    def set_theme(self, _theme: ThemePalette) -> None:
        """Apply frame colors that match the current overlay theme."""
        self._background_color = QColor(0, 0, 0, 65)
        self._border_color = QColor(255, 255, 255, 55)
        self._text_color = QColor(255, 255, 255, 170)

        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        """Draw the histogram frame, unavailable state, and RGB channels."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.fillRect(bounds, self._background_color)
        painter.setPen(QPen(self._border_color, 1))
        painter.drawRect(bounds)

        if self._histogram is None:
            painter.setPen(self._text_color)
            painter.drawText(bounds, Qt.AlignCenter, 'Histogram unavailable')
            return

        for channel, color in zip(
            self._histogram, HISTOGRAM_CHANNEL_COLORS, strict=True
        ):
            path = self._channel_path(channel, bounds)
            painter.setPen(QPen(color, 1.8))
            painter.drawPath(path)

    @staticmethod
    def _channel_path(
            channel: tuple[float, ...], bounds: QRectF
    ) -> QPainterPath:
        path = QPainterPath()
        if len(channel) != HISTOGRAM_CHANNEL_SIZE:
            return path

        width = max(bounds.width(), 1.0)
        height = max(bounds.height(), 1.0)
        for index, value in enumerate(channel):
            x = bounds.left() + (index / (HISTOGRAM_CHANNEL_SIZE - 1)) * width
            y = bounds.bottom() - max(0.0, min(1.0, value)) * height
            point = QPointF(x, y)
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)

        return path


class CopyableGpsLabel(QLabel):
    """GPS value label that offers a small copy menu."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName('exifOverlayGpsValue')
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Copy GPS')

    def copy_to_clipboard(self) -> None:
        """Copy the displayed GPS text to the application clipboard."""
        QApplication.clipboard().setText(self.text())

    def show_copy_menu(self, global_pos: QPointF) -> QMenu:
        """Show and return the copy menu for tests and mouse handlers."""
        menu = QMenu(self)
        copy_action = menu.addAction('Copy')
        copy_action.triggered.connect(self.copy_to_clipboard)
        menu.popup(global_pos.toPoint())
        return menu

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        """Show the GPS copy menu on left or right mouse press."""
        if event.button() in {
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
        }:
            self.show_copy_menu(event.globalPosition())
            event.accept()
            return

        super().mousePressEvent(event)


class ExifOverlayWidget(QFrame):
    """Floating pane showing EXIF rows above a combined RGB histogram."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName('exifOverlay')
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedWidth(OVERLAY_WIDTH)

        self._exif_display: dict[str, str] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            OVERLAY_PADDING,
            OVERLAY_PADDING,
            OVERLAY_PADDING,
            OVERLAY_PADDING,
        )
        layout.setSpacing(10)

        self._rows_widget = QWidget(self)
        self._rows_widget.setFocusPolicy(Qt.NoFocus)
        self._rows_layout = QGridLayout(self._rows_widget)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setHorizontalSpacing(10)
        self._rows_layout.setVerticalSpacing(4)
        layout.addWidget(self._rows_widget)

        self.histogram_plot = HistogramPlotWidget(self)
        layout.addWidget(self.histogram_plot)

        self.set_theme(THEMES['light'])
        self.set_content({}, None)
        self.hide()

    def set_content(
            self,
            exif_display: dict[str, str],
            histogram: RGBHistogram | None,
    ) -> None:
        """Replace displayed EXIF rows and histogram data."""
        self._exif_display = dict(exif_display)
        self._rebuild_rows()
        self.histogram_plot.set_histogram(histogram)
        self._sync_minimum_height()

    def exif_display(self) -> dict[str, str]:
        """Return a copy of the current EXIF display rows."""
        return dict(self._exif_display)

    def set_theme(self, theme: ThemePalette) -> None:
        """Apply colors for the semi-transparent overlay pane."""
        border = theme.button_border
        background = 'rgba(13, 16, 20, 190)'
        key_color = 'rgba(255, 255, 255, 185)'
        value_color = 'rgba(255, 255, 255, 235)'
        empty_color = 'rgba(255, 255, 255, 190)'

        self.setStyleSheet(
            f"""
            QFrame#exifOverlay {{
                background-color: {background};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QLabel#exifOverlayKey {{
                color: {key_color};
                font-weight: 700;
                font-size: 12px;
            }}
            QLabel#exifOverlayValue {{
                color: {value_color};
                font-size: 12px;
            }}
            QLabel#exifOverlayGpsValue {{
                color: {value_color};
                font-size: 12px;
            }}
            QLabel#exifOverlayEmpty {{
                color: {empty_color};
                font-size: 12px;
                font-style: italic;
            }}
            """
        )
        self.histogram_plot.set_theme(theme)

    def _rebuild_rows(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self._exif_display:
            empty_label = QLabel('No EXIF info', self._rows_widget)
            empty_label.setObjectName('exifOverlayEmpty')
            empty_label.setFocusPolicy(Qt.NoFocus)
            self._rows_layout.addWidget(empty_label, 0, 0, 1, 2)
            return

        for row, (label, value) in enumerate(self._exif_display.items()):
            key_label = QLabel(f'{label}:', self._rows_widget)
            key_label.setObjectName('exifOverlayKey')
            key_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
            key_label.setFocusPolicy(Qt.NoFocus)
            if label == 'GPS':
                value_label = CopyableGpsLabel(value, self._rows_widget)
            else:
                value_label = QLabel(value, self._rows_widget)
                value_label.setObjectName('exifOverlayValue')

            value_label.setWordWrap(True)
            value_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            value_label.setTextInteractionFlags(Qt.NoTextInteraction)
            value_label.setFocusPolicy(Qt.NoFocus)
            self._rows_layout.addWidget(key_label, row, 0)
            self._rows_layout.addWidget(value_label, row, 1)

        self._rows_layout.setColumnStretch(0, 0)
        self._rows_layout.setColumnStretch(1, 1)

    def _sync_minimum_height(self) -> None:
        row_count = max(len(self._exif_display), 1)
        layout_spacing = self.layout().spacing() if self.layout() else 0
        rows_spacing = self._rows_layout.verticalSpacing()
        rows_height = (
            row_count * MIN_EXIF_ROW_HEIGHT
            + max(row_count - 1, 0) * rows_spacing
        )
        minimum_height = (
            OVERLAY_PADDING * 2
            + rows_height
            + layout_spacing
            + HISTOGRAM_HEIGHT
        )
        self.setMinimumHeight(minimum_height)
