from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QListWidgetItem,
)

import easy_loupe.ui.widgets as widgets_module

_DIRECTIONS = pytest.mark.parametrize('direction', ['down', 'up'])


class _ThumbnailListOwner:
    """Stub owner that declines Shift range handling so Qt's default runs."""

    @staticmethod
    def extend_thumbnail_selection(_direction: int) -> bool:
        return False


def _create_scrollable_thumbnail_list() -> tuple[Any, Any]:
    """Build varied-height rows to exercise card geometry and spacing."""
    app = QApplication.instance() or QApplication([])
    widget = widgets_module.ThumbnailListWidget(_ThumbnailListOwner())
    widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
    widget.setSpacing(8)
    widget.resize(260, 360)
    for row in range(12):
        item = QListWidgetItem(f'IMG_{row:04d}')
        item.setSizeHint(QSize(220, 70 if row % 2 == 0 else 90))
        widget.addItem(item)

    widget.show()
    app.processEvents()
    return app, widget


def _step(direction: str) -> int:
    return 1 if direction == 'down' else -1


def _arrow_key(direction: str) -> Qt.Key:
    return Qt.Key_Down if direction == 'down' else Qt.Key_Up


def _edge_hint(direction: str) -> QAbstractItemView.ScrollHint:
    """Return the hint that pushes the neighbor just past the viewport."""
    if direction == 'down':
        return QAbstractItemView.ScrollHint.PositionAtBottom

    return QAbstractItemView.ScrollHint.PositionAtTop


def _row_fully_visible(widget: Any, row: int) -> bool:
    return (
        widget
        .viewport()
        .rect()
        .contains(widget.visualItemRect(widget.item(row)))
    )


def _row_intersects_viewport(widget: Any, row: int) -> bool:
    return (
        widget
        .viewport()
        .rect()
        .intersects(widget.visualItemRect(widget.item(row)))
    )


def _place_row_6_at_edge(widget: Any, app: Any, direction: str) -> int:
    """
    Show row 6 fully at the travel-side edge with its neighbor offscreen.

    The previous current row sits on the other side of row 6, so moving to row
    6 travels in ``direction``. Returns the scrollbar value.
    """
    step = _step(direction)
    widget.setCurrentRow(6 - step)
    widget.scrollToItem(widget.item(6), _edge_hint(direction))
    app.processEvents()
    assert _row_fully_visible(widget, 6)
    assert not _row_fully_visible(widget, 6 + step)
    return widget.verticalScrollBar().value()


def test_thumbnail_strip_owns_per_pixel_scrolling() -> None:
    """
    Keep the pixel scroll mode that lookahead overflow math depends on.

    With per-item scrolling, a pixel overflow would jump by that many rows, so
    the strip must not rely on its builder to choose the mode.
    """
    _, widget = _create_scrollable_thumbnail_list()
    assert widget.verticalScrollMode() == QAbstractItemView.ScrollPerPixel
    widget.close()


@_DIRECTIONS
def test_thumbnail_arrow_key_reveals_neighbor_row(direction: str) -> None:
    """
    Reveal the neighbor card in the direction of keyboard travel.

    Moving down shows the next card below the current one, while moving up
    shows the previous card above it. The strip scrolls only by the overflow,
    and the current row and selection stay on the navigated card, because
    culling actions use them.
    """
    app, widget = _create_scrollable_thumbnail_list()
    step = _step(direction)
    _place_row_6_at_edge(widget, app, direction)

    QTest.keyClick(widget, _arrow_key(direction))
    app.processEvents()

    assert widget.currentRow() == 6
    assert widget.selectedItems() == [widget.item(6)]
    assert _row_fully_visible(widget, 6)
    assert _row_fully_visible(widget, 6 + step)
    assert not _row_intersects_viewport(widget, 6 + 2 * step)
    widget.close()


@_DIRECTIONS
def test_thumbnail_page_key_reveals_neighbor_row(direction: str) -> None:
    """
    Treat Page Up/Down as keyboard travel that also reveals the neighbor.

    Paging lands several rows away, where Qt alone would leave the following
    card offscreen at the viewport edge.
    """
    app, widget = _create_scrollable_thumbnail_list()
    step = _step(direction)
    start_row = 2 if direction == 'down' else 9
    # Park the start row at the travel-side edge so the paged-to row begins
    # offscreen and Qt alone would stop it at the edge, hiding its neighbor.
    widget.setCurrentRow(start_row)
    widget.scrollToItem(widget.item(start_row), _edge_hint(direction))
    app.processEvents()

    key = Qt.Key_PageDown if direction == 'down' else Qt.Key_PageUp
    QTest.keyClick(widget, key)
    app.processEvents()

    current_row = widget.currentRow()
    # A one-row move would only repeat the arrow-key case.
    assert (current_row - start_row) * step > 1
    assert _row_fully_visible(widget, current_row)
    assert _row_fully_visible(widget, current_row + step)
    widget.close()


@_DIRECTIONS
@pytest.mark.parametrize('clicks', ['single', 'double'])
def test_thumbnail_click_on_edge_card_does_not_scroll(
        direction: str, clicks: str
) -> None:
    """
    Keep the strip still when the user clicks a card at its top or bottom.

    Lookahead is a keyboard-navigation aid. Scrolling after a click would move
    a card the user just pointed at, so clicking the bottom card must not
    reveal the card below it, and clicking the top card must not reveal the
    card above it. This is a regression test for user-reported strip jumps. The
    double-click case guards the second click of a quick repeat click.
    """
    app, widget = _create_scrollable_thumbnail_list()
    step = _step(direction)
    before = _place_row_6_at_edge(widget, app, direction)
    position = widget.visualItemRect(widget.item(6)).center()

    if clicks == 'single':
        QTest.mouseClick(
            widget.viewport(), Qt.LeftButton, Qt.NoModifier, position
        )
    else:
        QTest.mouseDClick(
            widget.viewport(), Qt.LeftButton, Qt.NoModifier, position
        )

    app.processEvents()
    assert widget.currentRow() == 6
    assert widget.verticalScrollBar().value() == before
    assert not _row_fully_visible(widget, 6 + step)
    widget.close()


@_DIRECTIONS
@pytest.mark.parametrize(
    'change', ['set-current-row', 'scroll-to-item', 'reshow']
)
def test_thumbnail_programmatic_changes_do_not_reveal_neighbor(
        direction: str, change: str
) -> None:
    """
    Leave non-keyboard current-row changes to plain Qt scrolling.

    Rebuilds, scene edits, and compare exit move the current row or reshow the
    strip without keyboard travel, so they must not add neighbor scrolling.
    """
    app, widget = _create_scrollable_thumbnail_list()
    step = _step(direction)
    before = _place_row_6_at_edge(widget, app, direction)

    if change == 'set-current-row':
        widget.setCurrentRow(6)
    elif change == 'scroll-to-item':
        widget.setCurrentRow(6)
        widget.scrollToItem(widget.item(6))
    else:
        # Move the current row while hidden, as compare mode does, so Qt's
        # own scroll-to-current on show runs without any added lookahead.
        widget.hide()
        widget.setCurrentRow(6)
        widget.show()

    app.processEvents()
    assert widget.currentRow() == 6
    assert widget.verticalScrollBar().value() == before
    assert not _row_fully_visible(widget, 6 + step)
    widget.close()


def test_thumbnail_keyboard_does_not_scroll_visible_neighbor() -> None:
    """
    Preserve position when the following card is already fully visible.

    This prevents lookahead from forcing every keyboard move toward the edge.
    """
    app, widget = _create_scrollable_thumbnail_list()
    widget.setCurrentRow(0)
    app.processEvents()
    before = widget.verticalScrollBar().value()

    QTest.keyClick(widget, Qt.Key_Down)
    app.processEvents()

    assert widget.currentRow() == 1
    assert _row_fully_visible(widget, 2)
    assert widget.verticalScrollBar().value() == before
    widget.close()


@_DIRECTIONS
@pytest.mark.parametrize(
    'boundary', ['end-row', 'short-viewport', 'exact-fit']
)
def test_thumbnail_keyboard_lookahead_prioritizes_current_row(
        boundary: str, direction: str
) -> None:
    """
    Keep the current card visible at list and viewport boundaries.

    Lookahead must tolerate a missing neighbor row or insufficient space. When
    two cards fit exactly, Qt's extra scroll padding must not clip the current
    card.
    """
    app, widget = _create_scrollable_thumbnail_list()
    step = _step(direction)
    target_row = 11 if direction == 'down' else 0
    pair: list[int] = []
    if boundary != 'end-row':
        target_row = 6
        height = 140
        if boundary == 'exact-fit':
            # Make the viewport exactly as tall as the two cards: their span
            # plus the frame the widget adds outside its viewport.
            pair = sorted([6, 6 + step])
            height = (
                widget.visualItemRect(widget.item(pair[1])).bottom()
                - widget.visualItemRect(widget.item(pair[0])).top()
                + 1
                + widget.height()
                - widget.viewport().height()
            )

        widget.resize(260, height)
        app.processEvents()

    widget.setCurrentRow(target_row - step)
    app.processEvents()
    QTest.keyClick(widget, _arrow_key(direction))
    app.processEvents()

    assert widget.currentRow() == target_row
    assert _row_fully_visible(widget, target_row)
    if boundary == 'short-viewport':
        assert not _row_fully_visible(widget, target_row + step)
    elif boundary == 'exact-fit':
        pair_rects = sorted(
            (widget.visualItemRect(widget.item(row)) for row in pair),
            key=lambda rect: rect.top(),
        )
        assert pair_rects[0].top() == 0
        assert pair_rects[1].bottom() == widget.viewport().rect().bottom()

    widget.close()
