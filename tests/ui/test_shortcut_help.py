from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QSizePolicy,
    QWidget,
)

import easy_loupe.ui.shortcut_help as shortcut_help_module
from easy_loupe.ui.shortcut_help import (
    ShortcutHelpContext,
    ShortcutHelpOverlay,
    shortcut_help_groups,
    shortcut_help_title,
)

if TYPE_CHECKING:
    import pytest


def test_shortcut_help_catalog_covers_each_context() -> None:
    """
    Verify every shortcut-help context has curated grouped content.

    The overlay is product-facing documentation, so this guards against adding
    an empty context or dropping the common help-dismissal shortcuts.
    """
    for context in ShortcutHelpContext:
        groups = shortcut_help_groups(context)
        assert shortcut_help_title(context)
        assert groups
        rows = [row for group in groups for row in group.rows]
        assert any(row.shortcut == '?' for row in rows)
        assert any(row.shortcut == 'Esc' for row in rows)

    photo_viewer_rows = [
        row
        for group in shortcut_help_groups(ShortcutHelpContext.PHOTO_VIEWER)
        for row in group.rows
    ]
    assert any(row.shortcut == 'G / Enter' for row in photo_viewer_rows)

    empty_rows = [
        row
        for group in shortcut_help_groups(ShortcutHelpContext.CULLING_EMPTY)
        for row in group.rows
    ]
    assert any(row.shortcut == 'Ctrl+O' for row in empty_rows)

    compare_rows = [
        row
        for group in shortcut_help_groups(ShortcutHelpContext.COMPARE_GRID)
        for row in group.rows
    ]
    assert any(row.shortcut == 'Arrow keys' for row in compare_rows)


def test_shortcut_help_formats_modifier_labels_for_platform(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify visible shortcut labels use Cmd only on macOS."""
    monkeypatch.setattr(shortcut_help_module.sys, 'platform', 'win32')

    assert shortcut_help_module.shortcut_modifier_label() == 'Ctrl'
    assert shortcut_help_module.format_shortcut_label('Ctrl+O') == 'Ctrl+O'
    assert shortcut_help_module.format_shortcut_label('Shift+F') == 'Shift+F'

    monkeypatch.setattr(shortcut_help_module.sys, 'platform', 'darwin')

    assert shortcut_help_module.shortcut_modifier_label() == 'Cmd'
    assert shortcut_help_module.format_shortcut_label('Ctrl+O') == 'Cmd+O'
    assert (
        shortcut_help_module.format_shortcut_label('Ctrl+Shift+F')
        == 'Cmd+Shift+F'
    )
    assert (
        shortcut_help_module.format_shortcut_label('Ctrl+Z / Ctrl+Y')
        == 'Cmd+Z / Cmd+Y'
    )
    assert shortcut_help_module.format_shortcut_label('Shift+F') == 'Shift+F'


def test_shortcut_help_overlay_renders_mac_modifier_labels(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify rendered table labels use macOS shortcut modifier text."""
    monkeypatch.setattr(shortcut_help_module.sys, 'platform', 'darwin')
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(1000, 800)
    parent.show()
    overlay = ShortcutHelpOverlay(parent)

    overlay.show_context(ShortcutHelpContext.CULLING_VIEW)
    app.processEvents()

    shortcut_texts = {
        label.text()
        for label in overlay.findChildren(QLabel, 'shortcutHelpShortcutLabel')
    }
    assert 'Cmd+O' in shortcut_texts
    assert 'Cmd+Shift+F' in shortcut_texts
    assert 'Cmd+Z / Cmd+Y' in shortcut_texts
    assert 'Shift+F' in shortcut_texts
    assert 'Ctrl+O' not in shortcut_texts

    parent.close()
    app.processEvents()


def test_shortcut_help_overlay_renders_tables_and_tracks_geometry() -> None:
    """
    Verify the shared overlay builds grouped tables with stable geometry.

    The overlay must cover the whole content area while its centered panel
    stays at 90 percent of the parent in both dimensions.
    """
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(1000, 800)
    parent.show()
    overlay = ShortcutHelpOverlay(parent)

    overlay.show_context(ShortcutHelpContext.CULLING_VIEW)
    app.processEvents()

    assert overlay.objectName() == 'shortcutHelpOverlay'
    assert overlay.panel.objectName() == 'shortcutHelpPanel'
    assert overlay.scroll_area.objectName() == 'shortcutHelpScrollArea'
    assert overlay.content_widget.objectName() == 'shortcutHelpContent'
    assert overlay.geometry() == parent.rect()
    assert overlay.panel.width() == 900
    assert overlay.panel.height() == 720
    assert overlay.title_label.text() == 'Culling View Shortcuts'
    assert overlay._content_grid.itemAtPosition(0, 1) is not None
    assert (
        overlay._content_grid.itemAtPosition(0, 0).alignment() == Qt.AlignTop
    )
    assert overlay._content_grid.rowStretch(3) == 1

    groups = overlay.findChildren(QFrame, 'shortcutHelpGroup')
    assert groups
    assert groups[0].sizePolicy().verticalPolicy() == QSizePolicy.Maximum
    shortcut_labels = overlay.findChildren(QLabel, 'shortcutHelpShortcutLabel')
    assert shortcut_labels
    fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    assert shortcut_labels[0].font().family() == fixed_font.family()
    assert overlay._title_font_size() == 44
    assert overlay._group_title_font_size() == 30
    assert overlay._table_text_font_size() == 26

    tables = overlay.findChildren(QFrame, 'shortcutHelpTable')
    assert tables
    assert tables[0].layout().horizontalSpacing() == 0
    assert tables[0].layout().verticalSpacing() == 0
    assert overlay.findChildren(QFrame, 'shortcutHelpShortcutCell')
    assert overlay.findChildren(QFrame, 'shortcutHelpDescriptionCell')
    assert 'QFrame#shortcutHelpShortcutCell' in overlay.styleSheet()
    assert 'border-right: 1px solid' in overlay.styleSheet()

    overlay.toggle_context(ShortcutHelpContext.CULLING_VIEW)
    assert overlay.isHidden() is True

    overlay.toggle_context(ShortcutHelpContext.BROWSE)
    app.processEvents()
    assert overlay.isVisible() is True
    assert overlay.title_label.text() == 'Browse View Shortcuts'

    parent.resize(600, 500)
    overlay.update_geometry()
    app.processEvents()

    assert overlay.panel.width() == 540
    assert overlay.panel.height() == 450
    assert overlay._content_grid.itemAtPosition(0, 1) is None
    assert overlay._table_text_font_size() < 26
    parent.close()
    app.processEvents()
