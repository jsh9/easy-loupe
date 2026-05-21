"""Thumbnail and scene-strip widget components for the desktop UI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsColorizeEffect,
    QLabel,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtGui import QPaintEvent

    from easy_cull.ui.theme import ThemePalette


class _SceneNavigator(Protocol):
    """Minimal interface required by SceneListWidget."""

    def navigate_global_from_scene(self, direction: int) -> bool: ...


class ThumbnailPreviewWidget(QWidget):
    """Thumbnail image widget with an optional visible-region overlay."""

    _MASK_COLOR = QColor(0, 0, 0, 112)
    _EDGE_COLOR = QColor('#ff3b30')

    def __init__(self, size: QSize, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size)
        self._pixmap = QPixmap()
        self._visible_region: tuple[float, float, float, float] | None = None

    def set_pixmap(self, pixmap: QPixmap) -> None:
        """Replace the displayed thumbnail pixmap and repaint."""
        self._pixmap = pixmap
        self.update()

    def set_visible_region_overlay(
            self, rect: tuple[float, float, float, float] | None
    ) -> None:
        """Store the normalized visible-region overlay for the thumbnail."""
        if rect is None:
            self._visible_region = None
        else:
            x, y, width, height = rect
            self._visible_region = (
                max(0.0, min(1.0, x)),
                max(0.0, min(1.0, y)),
                max(0.0, min(1.0, width)),
                max(0.0, min(1.0, height)),
            )

        self.update()

    def visible_region_overlay(
            self,
    ) -> tuple[float, float, float, float] | None:
        """Return the current normalized visible-region overlay."""
        return self._visible_region

    def displayed_image_rect(self) -> QRectF:
        """Return the on-widget rectangle occupied by the scaled image."""
        if self._pixmap.isNull():
            return QRectF()

        scaled = self._pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        return QRectF(
            (self.width() - scaled.width()) / 2,
            (self.height() - scaled.height()) / 2,
            scaled.width(),
            scaled.height(),
        )

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        """Paint the thumbnail image and optional visible-region overlay."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.Antialiasing, True)

        target = self.displayed_image_rect()
        if self._pixmap.isNull() or target.isEmpty():
            return

        scaled = self._pixmap.scaled(
            target.size().toSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        painter.drawPixmap(target.topLeft(), scaled)

        if self._visible_region is None:
            return

        x, y, width, height = self._visible_region
        overlay = QRectF(
            target.left() + (target.width() * x),
            target.top() + (target.height() * y),
            max(1.0, target.width() * width),
            max(1.0, target.height() * height),
        )
        overlay = overlay.intersected(target)
        if overlay.isEmpty():
            return

        painter.save()
        painter.setClipRect(target)

        painter.fillRect(
            QRectF(
                target.left(),
                target.top(),
                target.width(),
                max(0.0, overlay.top() - target.top()),
            ),
            self._MASK_COLOR,
        )
        painter.fillRect(
            QRectF(
                target.left(),
                overlay.top(),
                max(0.0, overlay.left() - target.left()),
                overlay.height(),
            ),
            self._MASK_COLOR,
        )
        painter.fillRect(
            QRectF(
                overlay.right(),
                overlay.top(),
                max(0.0, target.right() - overlay.right()),
                overlay.height(),
            ),
            self._MASK_COLOR,
        )
        painter.fillRect(
            QRectF(
                target.left(),
                overlay.bottom(),
                target.width(),
                max(0.0, target.bottom() - overlay.bottom()),
            ),
            self._MASK_COLOR,
        )

        pen = QPen(self._EDGE_COLOR)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(overlay.adjusted(0.5, 0.5, -0.5, -0.5))
        painter.restore()


class ThumbnailItemWidget(QWidget):
    """Thumbnail card widget with metadata and scene-stack badge support."""

    _IMAGE_TEXT_SPACING = 1
    _TEXT_ROW_SPACING = 8

    def __init__(
            self,
            *,
            thumb_path: Path,
            stem: str,
            metadata_text: str,
            frame_size: QSize,
            theme: ThemePalette,
            selected: bool = False,
            current: bool = False,
            rejected: bool = False,
            scene_count: int | None = None,
            stacked: bool = False,
            parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName('thumbRoot')
        self._frames: list[QFrame] = []
        self._image_widgets: list[ThumbnailPreviewWidget] = []
        self._front_image_widget: ThumbnailPreviewWidget | None = None
        self._badge: QLabel | None = None
        self._badge_frame: QFrame | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(self._IMAGE_TEXT_SPACING)

        stack_offset = 12 if stacked else 0
        stack_widget = QWidget(self)
        stack_widget.setFixedSize(
            frame_size.width() + stack_offset,
            frame_size.height() + stack_offset,
        )

        pixmap = QPixmap(str(thumb_path))
        if stacked:
            self._create_thumb_frame(
                stack_widget,
                pixmap=pixmap,
                frame_size=frame_size,
                offset=QPointF(12, 12),
            )
            self._create_thumb_frame(
                stack_widget,
                pixmap=pixmap,
                frame_size=frame_size,
                offset=QPointF(6, 6),
            )

        frame = self._create_thumb_frame(
            stack_widget,
            pixmap=pixmap,
            frame_size=frame_size,
            offset=QPointF(0, 0),
        )

        if scene_count is not None:
            self._badge = QLabel(str(scene_count), frame)
            self._badge_frame = frame

        root.addWidget(stack_widget, alignment=Qt.AlignCenter)

        text_widget = QWidget(self)
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(self._TEXT_ROW_SPACING)
        text_layout.setAlignment(Qt.AlignTop)

        self.name_label = QLabel(stem, text_widget)
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(False)
        self.name_label.setFixedHeight(self.name_label.fontMetrics().height())
        self.name_label.setStyleSheet(
            'QLabel { color: #e9eef3; font-weight: 600; }'
        )
        text_layout.addWidget(self.name_label)

        self.meta_label = QLabel(metadata_text, text_widget)
        self.meta_label.setAlignment(Qt.AlignCenter)
        self.meta_label.setTextFormat(Qt.RichText)
        self.meta_label.setFixedHeight(self.meta_label.fontMetrics().height())
        self.meta_label.setVisible(bool(metadata_text))
        text_layout.addWidget(self.meta_label)
        text_widget.setFixedHeight(
            self._reserved_text_height(text_layout.spacing())
        )
        root.addWidget(text_widget)
        self.apply_theme(
            theme, selected=selected, rejected=rejected, current=current
        )

    def _create_thumb_frame(
            self,
            parent: QWidget,
            *,
            pixmap: QPixmap,
            frame_size: QSize,
            offset: QPointF,
    ) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName('thumbFrame')
        frame.setFixedSize(frame_size)
        frame.move(int(offset.x()), int(offset.y()))
        self._frames.append(frame)

        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(8, 8, 8, 8)
        frame_layout.setSpacing(0)

        image_widget = ThumbnailPreviewWidget(
            QSize(frame_size.width() - 16, frame_size.height() - 16), frame
        )
        self._set_pixmap(image_widget, pixmap)
        self._image_widgets.append(image_widget)
        self._front_image_widget = image_widget
        frame_layout.addWidget(image_widget, alignment=Qt.AlignCenter)
        return frame

    @staticmethod
    def _set_pixmap(widget: ThumbnailPreviewWidget, pixmap: QPixmap) -> None:
        widget.set_pixmap(pixmap)

    def _reserved_text_height(self, row_spacing: int) -> int:
        """Reserve room for both text rows even when metadata is empty."""
        return (
            self.name_label.fontMetrics().height()
            + row_spacing
            + self.meta_label.fontMetrics().height()
        )

    def set_visible_region_overlay(
            self, rect: tuple[float, float, float, float] | None
    ) -> None:
        """Forward the visible-region overlay to the front thumbnail image."""
        if self._front_image_widget is not None:
            self._front_image_widget.set_visible_region_overlay(rect)

    def visible_region_overlay(
            self,
    ) -> tuple[float, float, float, float] | None:
        """Return the visible-region overlay from the front thumbnail image."""
        if self._front_image_widget is None:
            return None

        return self._front_image_widget.visible_region_overlay()

    def apply_theme(
            self,
            theme: ThemePalette,
            *,
            selected: bool,
            rejected: bool,
            current: bool = False,
    ) -> None:
        """Apply theme colors and selection state to the thumbnail card."""
        frame_background = (
            theme.selected_background if selected else theme.strip_background
        )
        border_color = theme.selected_name_color if current else 'transparent'
        name_color = (
            theme.selected_name_color if selected else theme.name_color
        )
        meta_color = (
            theme.selected_meta_color if selected else theme.meta_color
        )

        self.setStyleSheet(
            f"""
            QWidget#thumbRoot {{
                background-color: {frame_background};
                border: 2px solid {border_color};
                border-radius: 12px;
            }}
            """
        )
        for frame in self._frames:
            frame.setStyleSheet(
                f"""
                QFrame#thumbFrame {{
                    background-color: {frame_background};
                    border: none;
                    border-radius: 10px;
                }}
                """
            )

        self.name_label.setStyleSheet(
            f'QLabel {{ color: {name_color}; font-weight: 600; }}'
        )
        self.meta_label.setStyleSheet(f'QLabel {{ color: {meta_color}; }}')
        for image_widget in self._image_widgets:
            if rejected:
                effect = QGraphicsColorizeEffect(image_widget)
                effect.setColor(QColor('#8f98a2'))
                effect.setStrength(0.85)
                image_widget.setGraphicsEffect(effect)
            else:
                image_widget.setGraphicsEffect(None)

        if self._badge is not None:
            self._badge.setStyleSheet(
                f"""
                QLabel {{
                    background-color: {theme.badge_background};
                    color: {theme.badge_text_color};
                    border-radius: 10px;
                    padding: 2px 7px;
                    font-weight: 700;
                }}
                """
            )
            self._badge.adjustSize()
            badge_frame = self._badge_frame or self._badge.parentWidget()
            if badge_frame is not None:
                self._badge.move(
                    badge_frame.width() - self._badge.width() - 8, 8
                )
                self._badge.raise_()


class SceneListWidget(QListWidget):
    """Scene-strip list widget with custom vertical navigation handling."""

    def __init__(self, owner: _SceneNavigator) -> None:
        super().__init__()
        self._owner = owner

    def keyPressEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        """Handle up/down scene navigation before default list behavior."""
        from PySide6.QtCore import Qt as _Qt  # noqa: PLC0415
        from PySide6.QtGui import QKeyEvent  # noqa: PLC0415

        if not isinstance(event, QKeyEvent):
            super().keyPressEvent(event)  # type: ignore[arg-type]
            return

        # fmt: off
        if (
            event.key() == _Qt.Key_Up
            and self._owner.navigate_global_from_scene(-1)
        ):
            event.accept()
            return
        # fmt: on

        if (
            event.key() == _Qt.Key_Down
            and self._owner.navigate_global_from_scene(1)
        ):
            event.accept()
            return

        super().keyPressEvent(event)
