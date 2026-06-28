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
        # Window close belongs in every help context, but disabled quit must
        # not be advertised as an available command.
        assert any(row.shortcut.startswith('Ctrl+W') for row in rows)
        assert not any('Ctrl+Q' in row.shortcut for row in rows)

    photo_viewer_rows = [
        row
        for group in shortcut_help_groups(ShortcutHelpContext.PHOTO_VIEWER)
        for row in group.rows
    ]
    assert any(row.shortcut == 'G / Enter' for row in photo_viewer_rows)
    assert any(row.shortcut == 'J' for row in photo_viewer_rows)

    empty_rows = [
        row
        for group in shortcut_help_groups(ShortcutHelpContext.CULLING_EMPTY)
        for row in group.rows
    ]
    assert any(row.shortcut == 'Ctrl+O' for row in empty_rows)

    no_scene_rows = [
        row
        for group in shortcut_help_groups(
            ShortcutHelpContext.CULLING_VIEW_NO_SCENES
        )
        for row in group.rows
    ]
    assert any(row.shortcut == 'Ctrl+Shift+M' for row in no_scene_rows)
    assert any(row.shortcut == 'J' for row in no_scene_rows)
    assert not any(row.shortcut == 'Left / Right' for row in no_scene_rows)
    assert not any(
        row.shortcut == 'Shift+Left / Shift+Right' for row in no_scene_rows
    )
    # Shift+Up/Down exists before and after scene detection, but it targets
    # different navigation lists. Lock both descriptions so the context-aware
    # help copy follows the active selection model.
    no_scene_shift_rows = [
        row.description
        for row in no_scene_rows
        if row.shortcut == 'Shift+Up / Shift+Down'
    ]
    assert no_scene_shift_rows == ['Extend the thumbnail selection']

    culling_rows = [
        row
        for group in shortcut_help_groups(ShortcutHelpContext.CULLING_VIEW)
        for row in group.rows
    ]
    assert any(row.shortcut == 'Left / Right' for row in culling_rows)
    assert any(row.shortcut == 'J' for row in culling_rows)
    assert any(
        row.shortcut == 'Shift+Left / Shift+Right' for row in culling_rows
    )
    culling_shift_rows = [
        row.description
        for row in culling_rows
        if row.shortcut == 'Shift+Up / Shift+Down'
    ]
    assert culling_shift_rows == ['Extend selection across scene-stack rows']

    browse_rows = [
        row
        for group in shortcut_help_groups(ShortcutHelpContext.BROWSE)
        for row in group.rows
    ]
    assert any(row.shortcut == 'Ctrl+O' for row in browse_rows)
    assert any(row.shortcut == 'Ctrl+D' for row in browse_rows)
    assert any(row.shortcut == 'Ctrl+Shift+E' for row in browse_rows)

    compare_rows = [
        row
        for group in shortcut_help_groups(ShortcutHelpContext.COMPARE_GRID)
        for row in group.rows
    ]
    assert any(row.shortcut == 'Arrow keys' for row in compare_rows)
    assert any(row.shortcut == 'J' for row in compare_rows)
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
    assert any(row.shortcut == 'G' for row in selected_compare_rows)
    assert any(row.shortcut == 'J' for row in selected_compare_rows)
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
    assert shortcut_help_module.format_shortcut_label('Ctrl+W') == 'Ctrl+W'
    assert shortcut_help_module.format_shortcut_label('Shift+F') == 'Shift+F'

    monkeypatch.setattr(shortcut_help_module.sys, 'platform', 'darwin')

    assert shortcut_help_module.shortcut_modifier_label() == 'Cmd'
    assert shortcut_help_module.format_shortcut_label('Ctrl+O') == 'Cmd+O'
    assert shortcut_help_module.format_shortcut_label('Ctrl+W') == 'Cmd+W'
    assert (
        shortcut_help_module.format_shortcut_label('Ctrl+Shift+F')
        == 'Cmd+Shift+F'
    )
    assert (
        shortcut_help_module.format_shortcut_label('Ctrl+Z / Ctrl+Y')
        == 'Cmd+Z / Cmd+Y'
    )
    assert shortcut_help_module.format_shortcut_label('Shift+F') == 'Shift+F'


def test_shortcut_help_catalog_adds_alt_f4_on_windows(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify Windows help exposes Alt+F4 as a close-window shortcut.

    The catalog is platform-specific, so this protects the Windows-only help
    row even when tests run on macOS or Linux.
    """
    monkeypatch.setattr(shortcut_help_module.sys, 'platform', 'win32')

    for context in ShortcutHelpContext:
        rows = [
            row
            for group in shortcut_help_groups(context)
            for row in group.rows
        ]
        assert any(row.shortcut == 'Ctrl+W / Alt+F4' for row in rows)


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
    assert 'Cmd+W' in shortcut_texts
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


def test_shortcut_help_overlay_top_aligns_and_scales_fonts(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify multi-column help tables shrink and resize without churn.

    The overlay uses intentionally large text, so this guards against future
    scaling changes that keep full-size text in cramped table columns. Resize
    events can also carry sub-pixel scale changes, so the test guards against
    rebuilding the grid when rendered integer metrics have not changed.
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

    # Count renders after the initial layout. A resize that keeps the same
    # integer font and cell metrics should update geometry only; a column-count
    # change still needs a full grid rebuild.
    render_call_count = 0
    original_render_groups = overlay._render_groups
    initial_signature = (
        overlay._column_count,
        overlay._applied_scale_metrics,
    )

    def layout_signature_for_width(
            parent_width: int,
    ) -> tuple[int, tuple[int, ...]]:
        panel_width = max(int(parent_width * 0.9), 1)
        panel_height = max(int(parent.height() * 0.9), 1)
        column_count = ShortcutHelpOverlay._column_count_for_width(panel_width)
        font_scale = ShortcutHelpOverlay._font_scale_for_size(
            panel_width,
            panel_height,
            column_count,
        )
        return (
            column_count,
            ShortcutHelpOverlay._scale_metrics(font_scale),
        )

    stable_resize_width: int | None = None
    for offset in range(1, 200):
        for candidate_width in (
            parent.width() + offset,
            parent.width() - offset,
        ):
            if candidate_width <= 0:
                continue

            if (
                layout_signature_for_width(candidate_width)
                == initial_signature
            ):
                stable_resize_width = candidate_width
                break

        if stable_resize_width is not None:
            break

    assert stable_resize_width is not None

    def count_render_groups(*args: object, **kwargs: object) -> None:
        nonlocal render_call_count
        render_call_count += 1
        original_render_groups(*args, **kwargs)

    monkeypatch.setattr(overlay, '_render_groups', count_render_groups)
    parent.resize(stable_resize_width, parent.height())
    overlay.update_geometry()
    assert render_call_count == 0

    parent.resize(1400, 800)
    overlay.update_geometry()
    assert render_call_count == 1
    assert overlay._column_count == 3

    parent.close()
    app.processEvents()
