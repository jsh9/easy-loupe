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
    compare_esc_rows = [
        row.description for row in compare_rows if row.shortcut == 'Esc'
    ]
    assert compare_esc_rows == [
        'Close this shortcut reference; press Esc again to exit compare view'
    ]

    selected_compare_rows = [
        row
        for group in shortcut_help_groups(
            ShortcutHelpContext.COMPARE_SELECTED_PHOTO
        )
        for row in group.rows
    ]
    selected_compare_esc_rows = [
        row.description
        for row in selected_compare_rows
        if row.shortcut == 'Esc'
    ]
    assert selected_compare_esc_rows == [
        (
            'Close this shortcut reference; press Esc again to return to '
            'the comparison grid'
        )
    ]


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


def test_shortcut_help_formats_arrow_labels_and_spacing(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify arrow-key labels use glyphs and only arrow combos get spaced pluses.

    This protects the visual shortcut copy without changing canonical catalog
    values or the actual Qt shortcut registrations.
    """
    monkeypatch.setattr(shortcut_help_module.sys, 'platform', 'win32')

    assert shortcut_help_module.format_shortcut_label('Left / Up') == '← / ↑'
    assert (
        shortcut_help_module.format_shortcut_label('Right / Down') == '→ / ↓'
    )
    assert (
        shortcut_help_module.format_shortcut_label('Shift+Left / Shift+Right')
        == 'Shift + ← / Shift + →'
    )
    assert (
        shortcut_help_module.format_shortcut_label('Shift+Up / Shift+Down')
        == 'Shift + ↑ / Shift + ↓'
    )
    assert (
        shortcut_help_module.format_shortcut_label('Arrow keys')
        == '← / ↑ / ↓ / →'
    )
    assert (
        shortcut_help_module.format_shortcut_label('Ctrl+Shift+M')
        == 'Ctrl+Shift+M'
    )

    monkeypatch.setattr(shortcut_help_module.sys, 'platform', 'darwin')

    assert (
        shortcut_help_module.format_shortcut_label('Ctrl+Shift+M')
        == 'Cmd+Shift+M'
    )


def test_shortcut_help_overlay_renders_mac_modifier_labels(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify rendered labels combine macOS modifiers and arrow glyphs.

    This catches integration regressions where catalog rows stay canonical but
    the overlay forgets to apply display-only formatting before rendering.
    """
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
    assert 'Cmd+Shift+M' in shortcut_texts
    assert 'Cmd+Z / Cmd+Y' in shortcut_texts
    assert 'Shift+F' in shortcut_texts
    assert '← / →' in shortcut_texts
    assert 'Shift + ← / Shift + →' in shortcut_texts
    assert 'Shift + ↑ / Shift + ↓' in shortcut_texts
    assert 'Ctrl+O' not in shortcut_texts
    assert 'Left / Right' not in shortcut_texts
    assert 'Shift+Left / Shift+Right' not in shortcut_texts

    parent.close()
    app.processEvents()


def test_shortcut_help_overlay_renders_context_and_tracks_geometry() -> None:
    """
    Verify the shared overlay shows context rows and tracks parent geometry.

    This protects user-visible help content without locking the test to private
    grid coordinates, exact font sizes, or stylesheet fragments.
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
    assert 0 < overlay.panel.width() <= parent.width()
    assert 0 < overlay.panel.height() <= parent.height()
    assert overlay.title_label.text() == 'Culling View Shortcuts'
    shortcut_texts = {
        label.text()
        for label in overlay.findChildren(QLabel, 'shortcutHelpShortcutLabel')
    }
    description_texts = {
        label.text()
        for label in overlay.findChildren(
            QLabel, 'shortcutHelpDescriptionLabel'
        )
    }
    modifier = shortcut_help_module.shortcut_modifier_label()
    assert {f'{modifier}+O', f'{modifier}+D', '?', 'Esc'} <= shortcut_texts
    assert 'Open a photo folder' in description_texts
    assert 'Close this shortcut reference' in description_texts

    overlay.toggle_context(ShortcutHelpContext.CULLING_VIEW)
    assert overlay.isHidden() is True

    overlay.toggle_context(ShortcutHelpContext.BROWSE)
    app.processEvents()
    assert overlay.isVisible() is True
    assert overlay.title_label.text() == 'Browse View Shortcuts'

    parent.resize(600, 500)
    overlay.update_geometry()
    app.processEvents()

    assert overlay.geometry() == parent.rect()
    assert 0 < overlay.panel.width() <= parent.width()
    assert 0 < overlay.panel.height() <= parent.height()
    parent.close()
    app.processEvents()


def test_shortcut_help_overlay_top_aligns_and_scales_fonts() -> None:
    """
    Verify multi-column help tables shrink text when columns are narrow.

    The overlay uses intentionally large text, so this guards against future
    scaling changes that keep full-size text in cramped table columns.
    """
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(1000, 800)
    parent.show()
    overlay = ShortcutHelpOverlay(parent)

    overlay.show_context(ShortcutHelpContext.CULLING_VIEW)
    app.processEvents()

    first_grid_item = overlay._content_grid.itemAtPosition(0, 0)
    assert first_grid_item is not None
    assert first_grid_item.alignment() == Qt.AlignTop
    assert overlay._column_count == 2
    assert (
        overlay._table_text_font_size()
        < shortcut_help_module.TABLE_TEXT_FONT_SIZE_PX
    )

    groups = overlay.findChildren(QFrame, 'shortcutHelpGroup')
    assert groups
    assert groups[0].sizePolicy().verticalPolicy() == QSizePolicy.Maximum

    shortcut_labels = overlay.findChildren(
        QLabel,
        'shortcutHelpShortcutLabel',
    )
    assert shortcut_labels
    fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    assert shortcut_labels[0].font().family() == fixed_font.family()

    assert (
        ShortcutHelpOverlay._font_scale_for_size(1800, 1080, 3)
        == shortcut_help_module.MAX_FONT_SCALE
    )
    assert (
        ShortcutHelpOverlay._font_scale_for_size(900, 720, 2)
        < shortcut_help_module.MAX_FONT_SCALE
    )
    assert (
        ShortcutHelpOverlay._font_scale_for_size(100, 100, 1)
        == shortcut_help_module.MIN_FONT_SCALE
    )

    parent.close()
    app.processEvents()
