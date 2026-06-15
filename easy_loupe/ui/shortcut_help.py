"""Context-aware keyboard shortcut help overlay."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

THREE_COLUMN_PANEL_WIDTH = 1180
TWO_COLUMN_PANEL_WIDTH = 760
REFERENCE_PANEL_WIDTH = 900
REFERENCE_PANEL_HEIGHT = 720
MAX_FONT_SCALE = 1.0
MIN_FONT_SCALE = 0.6
TITLE_FONT_SIZE_PX = 44
GROUP_TITLE_FONT_SIZE_PX = 30
TABLE_TEXT_FONT_SIZE_PX = 26
SHORTCUT_COLUMN_WIDTH_PX = 170
CELL_HORIZONTAL_PADDING_PX = 12
CELL_VERTICAL_PADDING_PX = 8
MIN_SCALED_SIZE_PX = 1


class ShortcutHelpContext(StrEnum):
    """Shortcut-help contexts shown by EasyLoupe windows."""

    PHOTO_VIEWER = 'photo_viewer'
    CULLING_EMPTY = 'culling_empty'
    CULLING_VIEW = 'culling_view'
    BROWSE = 'browse'
    COMPARE_GRID = 'compare_grid'
    COMPARE_SELECTED_PHOTO = 'compare_selected_photo'


@dataclass(frozen=True, slots=True)
class ShortcutHelpRow:
    """One shortcut and its user-facing description."""

    shortcut: str
    description: str


@dataclass(frozen=True, slots=True)
class ShortcutHelpGroup:
    """A named group of related shortcut rows."""

    title: str
    rows: tuple[ShortcutHelpRow, ...]


HELP_DISMISSAL_GROUP = ShortcutHelpGroup(
    'Help',
    (
        ShortcutHelpRow('?', 'Show or hide this shortcut reference'),
        ShortcutHelpRow('Esc', 'Close this shortcut reference'),
    ),
)


def shortcut_help_title(context: ShortcutHelpContext) -> str:
    """Return the title for the requested shortcut-help context."""
    titles = {
        ShortcutHelpContext.PHOTO_VIEWER: 'Photo Viewer Shortcuts',
        ShortcutHelpContext.CULLING_EMPTY: 'EasyLoupe Shortcuts',
        ShortcutHelpContext.CULLING_VIEW: 'Culling View Shortcuts',
        ShortcutHelpContext.BROWSE: 'Browse View Shortcuts',
        ShortcutHelpContext.COMPARE_GRID: 'Compare Grid Shortcuts',
        ShortcutHelpContext.COMPARE_SELECTED_PHOTO: (
            'Selected Compare Photo Shortcuts'
        ),
    }
    return titles[context]


def shortcut_help_groups(
        context: ShortcutHelpContext,
) -> tuple[ShortcutHelpGroup, ...]:
    """Return grouped shortcut rows for the requested UI context."""
    groups = {
        ShortcutHelpContext.PHOTO_VIEWER: _photo_viewer_groups,
        ShortcutHelpContext.CULLING_EMPTY: _culling_empty_groups,
        ShortcutHelpContext.CULLING_VIEW: _culling_view_groups,
        ShortcutHelpContext.BROWSE: _browse_groups,
        ShortcutHelpContext.COMPARE_GRID: _compare_grid_groups,
        ShortcutHelpContext.COMPARE_SELECTED_PHOTO: (
            _compare_selected_photo_groups
        ),
    }
    return groups[context]()


def shortcut_modifier_label() -> str:
    """Return the platform-specific shortcut modifier display label."""
    if sys.platform == 'darwin':
        return 'Cmd'

    return 'Ctrl'


def format_shortcut_label(shortcut: str) -> str:
    """Return ``shortcut`` with platform-specific modifier names."""
    return shortcut.replace('Ctrl', shortcut_modifier_label())


class ShortcutHelpOverlay(QWidget):
    """Centered context-aware shortcut reference overlay."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName('shortcutHelpOverlay')
        self.hide()
        self._context: ShortcutHelpContext | None = None
        self._groups: tuple[ShortcutHelpGroup, ...] = ()
        self._column_count = 0
        self._rendered_row_count = 0
        self._font_scale = MAX_FONT_SCALE

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addStretch(1)

        center_layout = QHBoxLayout()
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addStretch(1)

        self.panel = QFrame(self)
        self.panel.setObjectName('shortcutHelpPanel')
        self.panel.setSizePolicy(
            QSizePolicy.Fixed,
            QSizePolicy.Fixed,
        )
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(24, 22, 24, 24)
        panel_layout.setSpacing(14)

        self.title_label = QLabel('', self.panel)
        self.title_label.setObjectName('shortcutHelpTitle')
        self.title_label.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(self.title_label)

        self.scroll_area = QScrollArea(self.panel)
        self.scroll_area.setObjectName('shortcutHelpScrollArea')
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        panel_layout.addWidget(self.scroll_area, 1)

        self.content_widget = QWidget(self.scroll_area)
        self.content_widget.setObjectName('shortcutHelpContent')
        self._content_grid = QGridLayout(self.content_widget)
        self._content_grid.setContentsMargins(0, 0, 0, 0)
        self._content_grid.setHorizontalSpacing(14)
        self._content_grid.setVerticalSpacing(14)
        self.scroll_area.setWidget(self.content_widget)

        center_layout.addWidget(self.panel)
        center_layout.addStretch(1)
        root_layout.addLayout(center_layout)
        root_layout.addStretch(1)
        self._apply_style()

    def show_context(self, context: ShortcutHelpContext) -> None:
        """Render and show shortcut help for ``context``."""
        self._context = context
        self._groups = shortcut_help_groups(context)
        self.title_label.setText(shortcut_help_title(context))
        self._render_groups(force=True)
        self.update_geometry()
        self.show()
        self.raise_()

    def toggle_context(self, context: ShortcutHelpContext) -> None:
        """Toggle the overlay, refreshing content when context changes."""
        if self.isVisible() and self._context == context:
            self.hide()
            return

        self.show_context(context)

    def update_geometry(self) -> None:
        """Fill the parent and size the centered panel to 90 percent."""
        parent = self.parentWidget()
        if parent is None:
            return

        parent_rect = parent.rect()
        self.setGeometry(parent_rect)
        width = max(int(parent_rect.width() * 0.9), 1)
        height = max(int(parent_rect.height() * 0.9), 1)
        self.panel.setFixedSize(width, height)
        column_count = self._column_count_for_width(width)
        font_scale = self._font_scale_for_size(width, height)
        scale_changed = font_scale != self._font_scale
        if scale_changed:
            self._font_scale = font_scale
            self._apply_style()

        if column_count != self._column_count or scale_changed:
            self._render_groups(force=True, column_count=column_count)

    def _render_groups(
            self,
            *,
            force: bool = False,
            column_count: int | None = None,
    ) -> None:
        next_column_count = column_count or self._column_count_for_width(
            self.panel.width()
        )
        if not force and next_column_count == self._column_count:
            return

        self._clear_content_grid()
        self._column_count = next_column_count
        for index, group in enumerate(self._groups):
            group_widget = self._build_group_widget(group)
            row = index // self._column_count
            column = index % self._column_count
            self._content_grid.addWidget(
                group_widget,
                row,
                column,
                Qt.AlignTop,
            )

        for column in range(self._column_count):
            self._content_grid.setColumnStretch(column, 1)

        self._rendered_row_count = (
            len(self._groups) + self._column_count - 1
        ) // self._column_count
        for row in range(self._rendered_row_count):
            self._content_grid.setRowStretch(row, 0)

        self._content_grid.setRowStretch(self._rendered_row_count, 1)

    def _clear_content_grid(self) -> None:
        while self._content_grid.count():
            item = self._content_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for row in range(self._rendered_row_count + 1):
            self._content_grid.setRowStretch(row, 0)

        for column in range(self._column_count):
            self._content_grid.setColumnStretch(column, 0)

        self._rendered_row_count = 0

    def _build_group_widget(self, group: ShortcutHelpGroup) -> QWidget:
        frame = QFrame(self.content_widget)
        frame.setObjectName('shortcutHelpGroup')
        frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)

        title = QLabel(group.title, frame)
        title.setObjectName('shortcutHelpGroupTitle')
        title.setWordWrap(True)
        layout.addWidget(title)

        table = QFrame(frame)
        table.setObjectName('shortcutHelpTable')
        table_layout = QGridLayout(table)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setHorizontalSpacing(0)
        table_layout.setVerticalSpacing(0)
        shortcut_font = QFontDatabase.systemFont(
            QFontDatabase.SystemFont.FixedFont
        )
        for row_index, row in enumerate(group.rows):
            shortcut_cell = QFrame(table)
            shortcut_cell.setObjectName('shortcutHelpShortcutCell')
            shortcut_layout = self._build_cell_layout(shortcut_cell)

            shortcut_label = QLabel(
                format_shortcut_label(row.shortcut),
                shortcut_cell,
            )
            shortcut_label.setObjectName('shortcutHelpShortcutLabel')
            shortcut_label.setFont(shortcut_font)
            shortcut_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            shortcut_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            shortcut_label.setMinimumWidth(self._shortcut_column_width())
            shortcut_label.setSizePolicy(
                QSizePolicy.Minimum,
                QSizePolicy.Preferred,
            )
            shortcut_layout.addWidget(shortcut_label, 0, Qt.AlignTop)

            description_cell = QFrame(table)
            description_cell.setObjectName('shortcutHelpDescriptionCell')
            description_layout = self._build_cell_layout(description_cell)

            description_label = QLabel(row.description, description_cell)
            description_label.setObjectName('shortcutHelpDescriptionLabel')
            description_label.setWordWrap(True)
            description_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            description_label.setSizePolicy(
                QSizePolicy.Expanding,
                QSizePolicy.Preferred,
            )
            description_layout.addWidget(description_label, 0, Qt.AlignTop)

            table_layout.addWidget(shortcut_cell, row_index, 0)
            table_layout.addWidget(description_cell, row_index, 1)

        table_layout.setColumnStretch(1, 1)
        layout.addWidget(table, 0, Qt.AlignTop)
        return frame

    def _build_cell_layout(self, cell: QFrame) -> QVBoxLayout:
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(
            self._scaled_size(CELL_HORIZONTAL_PADDING_PX),
            self._scaled_size(CELL_VERTICAL_PADDING_PX),
            self._scaled_size(CELL_HORIZONTAL_PADDING_PX),
            self._scaled_size(CELL_VERTICAL_PADDING_PX),
        )
        layout.setSpacing(0)
        return layout

    @staticmethod
    def _column_count_for_width(width: int) -> int:
        if width >= THREE_COLUMN_PANEL_WIDTH:
            return 3

        if width >= TWO_COLUMN_PANEL_WIDTH:
            return 2

        return 1

    @staticmethod
    def _font_scale_for_size(width: int, height: int) -> float:
        return min(
            MAX_FONT_SCALE,
            max(
                MIN_FONT_SCALE,
                min(
                    width / REFERENCE_PANEL_WIDTH,
                    height / REFERENCE_PANEL_HEIGHT,
                ),
            ),
        )

    def _scaled_size(self, size: int) -> int:
        return max(MIN_SCALED_SIZE_PX, int(size * self._font_scale))

    def _title_font_size(self) -> int:
        return self._scaled_size(TITLE_FONT_SIZE_PX)

    def _group_title_font_size(self) -> int:
        return self._scaled_size(GROUP_TITLE_FONT_SIZE_PX)

    def _table_text_font_size(self) -> int:
        return self._scaled_size(TABLE_TEXT_FONT_SIZE_PX)

    def _shortcut_column_width(self) -> int:
        return self._scaled_size(SHORTCUT_COLUMN_WIDTH_PX)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QWidget#shortcutHelpOverlay {{
                background-color: rgba(10, 12, 15, 96);
            }}
            QFrame#shortcutHelpPanel {{
                background-color: rgba(38, 42, 48, 238);
                border: 1px solid rgba(236, 241, 246, 80);
                border-radius: 8px;
            }}
            QLabel#shortcutHelpTitle {{
                color: #f4f7fa;
                font-size: {self._title_font_size()}px;
                font-weight: 700;
            }}
            QScrollArea#shortcutHelpScrollArea {{
                background: transparent;
                border: none;
            }}
            QWidget#shortcutHelpContent {{
                background: transparent;
            }}
            QFrame#shortcutHelpGroup {{
                background-color: rgba(22, 25, 30, 150);
                border: 1px solid rgba(236, 241, 246, 55);
                border-radius: 6px;
            }}
            QLabel#shortcutHelpGroupTitle {{
                color: #f4f7fa;
                font-size: {self._group_title_font_size()}px;
                font-weight: 700;
            }}
            QFrame#shortcutHelpTable {{
                background: transparent;
                border-top: 1px solid rgba(236, 241, 246, 80);
                border-left: 1px solid rgba(236, 241, 246, 80);
            }}
            QFrame#shortcutHelpShortcutCell,
            QFrame#shortcutHelpDescriptionCell {{
                background: transparent;
                border-right: 1px solid rgba(236, 241, 246, 80);
                border-bottom: 1px solid rgba(236, 241, 246, 80);
            }}
            QLabel#shortcutHelpShortcutLabel {{
                color: #f7f3c1;
                font-size: {self._table_text_font_size()}px;
                font-weight: 700;
                background: transparent;
            }}
            QLabel#shortcutHelpDescriptionLabel {{
                color: #e3e8ee;
                font-size: {self._table_text_font_size()}px;
                background: transparent;
            }}
            QScrollBar:vertical, QScrollBar:horizontal {{
                background: rgba(236, 241, 246, 24);
                border: none;
            }}
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
                background: rgba(236, 241, 246, 115);
                border-radius: 4px;
            }}
            """
        )


def _photo_viewer_groups() -> tuple[ShortcutHelpGroup, ...]:
    return (
        ShortcutHelpGroup(
            'Navigation',
            (
                ShortcutHelpRow('Left / Up', 'Open the previous photo'),
                ShortcutHelpRow('Right / Down', 'Open the next photo'),
                ShortcutHelpRow(
                    'G / Enter',
                    'Open the full culling workspace for this folder',
                ),
            ),
        ),
        ShortcutHelpGroup(
            'Inspection',
            (
                ShortcutHelpRow('Space / Z', 'Toggle fit and focus zoom'),
                ShortcutHelpRow('\\', 'Toggle split view'),
                ShortcutHelpRow('- / = / +', 'Zoom out or in'),
                ShortcutHelpRow('W / A / S / D', 'Pan the zoomed view'),
            ),
        ),
        ShortcutHelpGroup(
            'Overlays',
            (
                ShortcutHelpRow('F', 'Toggle the AF point marker'),
                ShortcutHelpRow(
                    'Shift+F',
                    'Recenter manual zoom on the AF point or image center',
                ),
                ShortcutHelpRow(
                    'Ctrl+Shift+F',
                    'Reset remembered zoom centers',
                ),
                ShortcutHelpRow('I', 'Toggle EXIF and histogram details'),
            ),
        ),
        HELP_DISMISSAL_GROUP,
    )


def _culling_empty_groups() -> tuple[ShortcutHelpGroup, ...]:
    return (
        ShortcutHelpGroup(
            'Library',
            (ShortcutHelpRow('Ctrl+O', 'Open a photo folder'),),
        ),
        HELP_DISMISSAL_GROUP,
    )


def _culling_view_groups() -> tuple[ShortcutHelpGroup, ...]:
    return (
        ShortcutHelpGroup(
            'Library',
            (
                ShortcutHelpRow('Ctrl+O', 'Open a photo folder'),
                ShortcutHelpRow('Ctrl+D', 'Detect scenes'),
                ShortcutHelpRow(
                    'Ctrl+Shift+E',
                    'Open the organizer and XMP export dialog',
                ),
            ),
        ),
        ShortcutHelpGroup(
            'View Modes',
            (
                ShortcutHelpRow('G', 'Enter browse view'),
                ShortcutHelpRow('C', 'Compare the current selection'),
                ShortcutHelpRow('Space / Z', 'Toggle fit and focus zoom'),
                ShortcutHelpRow('\\', 'Toggle split view'),
            ),
        ),
        _metadata_group(),
        ShortcutHelpGroup(
            'Scenes',
            (
                ShortcutHelpRow('Left / Right', 'Move within the scene strip'),
                ShortcutHelpRow(
                    'Shift+Left / Shift+Right',
                    'Extend the in-scene selection',
                ),
                ShortcutHelpRow(
                    'Shift+Up / Shift+Down',
                    'Extend selection across scene-stack rows',
                ),
                ShortcutHelpRow(
                    'Ctrl+Shift+M',
                    'Merge selected photos into a scene',
                ),
            ),
        ),
        _inspection_group(),
        HELP_DISMISSAL_GROUP,
    )


def _browse_groups() -> tuple[ShortcutHelpGroup, ...]:
    return (
        ShortcutHelpGroup(
            'Browse',
            (
                ShortcutHelpRow('Space', 'Return to fit view'),
                ShortcutHelpRow('C', 'Compare the current selection'),
            ),
        ),
        _metadata_group(),
        ShortcutHelpGroup(
            'Scenes',
            (
                ShortcutHelpRow(
                    'Ctrl+Shift+M',
                    'Merge selected photos into a scene',
                ),
            ),
        ),
        HELP_DISMISSAL_GROUP,
    )


def _compare_grid_groups() -> tuple[ShortcutHelpGroup, ...]:
    return (
        ShortcutHelpGroup(
            'Compare',
            (
                ShortcutHelpRow('Arrow keys', 'Move the active compare pane'),
                ShortcutHelpRow('Space', 'Open the active photo alone'),
                ShortcutHelpRow('Z', 'Toggle focus zoom for compared panes'),
                ShortcutHelpRow('G', 'Return to browse with the selection'),
                ShortcutHelpRow('Esc', 'Exit compare view'),
            ),
        ),
        ShortcutHelpGroup(
            'Inspection',
            (
                ShortcutHelpRow('- / = / +', 'Zoom active or locked panes'),
                ShortcutHelpRow('W / A / S / D', 'Pan active or locked panes'),
                ShortcutHelpRow('F', 'Toggle AF point markers'),
            ),
        ),
        _metadata_group(compare=True),
        HELP_DISMISSAL_GROUP,
    )


def _compare_selected_photo_groups() -> tuple[ShortcutHelpGroup, ...]:
    return (
        ShortcutHelpGroup(
            'Selected Photo',
            (
                ShortcutHelpRow(
                    'Space / Z',
                    'Toggle fit and 100 percent view',
                ),
                ShortcutHelpRow('Esc', 'Return to the comparison grid'),
            ),
        ),
        ShortcutHelpGroup(
            'Inspection',
            (
                ShortcutHelpRow('- / = / +', 'Zoom the selected photo'),
                ShortcutHelpRow('W / A / S / D', 'Pan the selected photo'),
                ShortcutHelpRow('F', 'Toggle the AF point marker'),
            ),
        ),
        _metadata_group(compare=True),
        HELP_DISMISSAL_GROUP,
    )


def _metadata_group(*, compare: bool = False) -> ShortcutHelpGroup:
    target = 'the active compare photo' if compare else 'selected photos'
    return ShortcutHelpGroup(
        'Metadata',
        (
            ShortcutHelpRow('1-5 / 0', f'Set or clear rating for {target}'),
            ShortcutHelpRow(
                '6-9 / `',
                f'Set or clear color label for {target}',
            ),
            ShortcutHelpRow(
                'P / X / U',
                f'Pick, reject, or clear flag for {target}',
            ),
            ShortcutHelpRow('Ctrl+Z / Ctrl+Y', 'Undo or redo metadata edits'),
        ),
    )


def _inspection_group() -> ShortcutHelpGroup:
    return ShortcutHelpGroup(
        'Inspection',
        (
            ShortcutHelpRow('- / = / +', 'Zoom out or in'),
            ShortcutHelpRow('W / A / S / D', 'Pan the zoomed view'),
            ShortcutHelpRow('F', 'Toggle the AF point marker'),
            ShortcutHelpRow(
                'Shift+F',
                'Recenter manual zoom on the AF point or image center',
            ),
            ShortcutHelpRow('Ctrl+Shift+F', 'Reset remembered zoom centers'),
            ShortcutHelpRow('I', 'Toggle EXIF and histogram details'),
        ),
    )
