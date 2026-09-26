from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QListWidgetItem,
    QWidget,
)

import easy_loupe.ui.thumbnail_lookahead as thumbnail_lookahead_module
import easy_loupe.ui.widgets as widgets_module

_DIRECTIONS = pytest.mark.parametrize('direction', ['down', 'up'])


class _ThumbnailListOwner:
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


def _prepare_click_on_row_6(widget: Any, app: Any) -> tuple[Any, Any, int]:
    """Place row 6 at the bottom edge with row 7 offscreen below it."""
    widget.setCurrentRow(5)
    target = widget.item(6)
    widget.scrollToItem(target, QAbstractItemView.PositionAtBottom)
    app.processEvents()
    assert not _row_fully_visible(widget, 7)
    position = widget.visualItemRect(target).center()
    return target, position, widget.verticalScrollBar().value()


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
@pytest.mark.parametrize('navigation', ['key', 'mouse', 'current', 'scroll'])
def test_thumbnail_navigation_reveals_neighbor_row(
        navigation: str, direction: str
) -> None:
    """
    Reveal the neighbor card in the direction of travel.

    Moving down shows the next card below the current one, while moving up
    shows the previous card above it. The current row and selection must stay
    on the navigated card, because culling actions use them.
    """
    app, widget = _create_scrollable_thumbnail_list()
    step = _step(direction)
    target = widget.item(6)
    neighbor_row = 6 + step
    widget.setCurrentRow(6 - step)
    if navigation == 'scroll':
        # Record the travel direction before re-scrolling the current row.
        widget.setCurrentRow(6)

    widget.scrollToItem(target, _edge_hint(direction))
    app.processEvents()
    assert not _row_fully_visible(widget, neighbor_row)

    if navigation == 'key':
        key = Qt.Key_Down if direction == 'down' else Qt.Key_Up
        QTest.keyClick(widget, key)
    elif navigation == 'mouse':
        QTest.mouseClick(
            widget.viewport(),
            Qt.LeftButton,
            Qt.NoModifier,
            widget.visualItemRect(target).center(),
        )
    elif navigation == 'current':
        widget.setCurrentRow(6)
    else:
        widget.scrollToItem(target)

    app.processEvents()
    assert widget.currentRow() == 6
    assert widget.selectedItems() == [target]
    assert _row_fully_visible(widget, 6)
    assert _row_fully_visible(widget, neighbor_row)
    assert (
        not widget
        .viewport()
        .rect()
        .intersects(widget.visualItemRect(widget.item(6 + 2 * step)))
    )
    widget.close()


def test_thumbnail_navigation_does_not_scroll_visible_successor() -> None:
    """
    Preserve position when the following card is already fully visible.

    This prevents lookahead from forcing every selection toward the bottom.
    """
    app, widget = _create_scrollable_thumbnail_list()
    before = widget.verticalScrollBar().value()
    widget.setCurrentRow(1)
    app.processEvents()

    assert _row_fully_visible(widget, 2)
    assert widget.verticalScrollBar().value() == before
    widget.close()


def test_thumbnail_quick_second_click_hits_unmoved_card(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep a clicked card still for the double-click interval.

    Scrolling right after release would move the next card under the pointer,
    so a quick second click would select a different photo.
    """
    monkeypatch.setattr(
        thumbnail_lookahead_module, '_mouse_settle_delay_ms', lambda: 150
    )
    app, widget = _create_scrollable_thumbnail_list()
    target, position, before = _prepare_click_on_row_6(widget, app)

    QTest.mouseClick(widget.viewport(), Qt.LeftButton, Qt.NoModifier, position)
    app.processEvents()
    assert widget.verticalScrollBar().value() == before
    assert widget.indexAt(position).row() == 6

    QTest.mouseClick(widget.viewport(), Qt.LeftButton, Qt.NoModifier, position)
    app.processEvents()
    assert widget.currentRow() == 6
    assert widget.selectedItems() == [target]
    assert widget.verticalScrollBar().value() == before

    QTest.qWait(400)
    assert _row_fully_visible(widget, 6)
    assert _row_fully_visible(widget, 7)
    widget.close()


def test_thumbnail_activation_keeps_pending_click_lookahead() -> None:
    """
    Keep click lookahead when the app becomes active.

    Clicking a background window can report activation during the click, so
    only leaving the active state may cancel the pending scroll.
    """
    app, widget = _create_scrollable_thumbnail_list()
    _, position, _ = _prepare_click_on_row_6(widget, app)

    QTest.mouseClick(widget.viewport(), Qt.LeftButton, Qt.NoModifier, position)
    app.applicationStateChanged.emit(Qt.ApplicationActive)
    app.processEvents()

    assert _row_fully_visible(widget, 7)
    widget.close()


@pytest.mark.parametrize('phase', ['held', 'released'])
@pytest.mark.parametrize(
    'interruption', ['deactivate', 'right-click', 'explicit-scroll']
)
def test_thumbnail_interruption_cancels_mouse_lookahead(
        phase: str, interruption: str
) -> None:
    """
    Discard interrupted mouse scrolling without disabling later navigation.

    Cancellation must work while the button is held and after release has
    queued completion, or new context menus and explicit anchors can jump.
    """
    app, widget = _create_scrollable_thumbnail_list()
    _, position, before = _prepare_click_on_row_6(widget, app)
    QTest.mousePress(widget.viewport(), Qt.LeftButton, Qt.NoModifier, position)
    if phase == 'released':
        QTest.mouseRelease(
            widget.viewport(), Qt.LeftButton, Qt.NoModifier, position
        )

    if interruption == 'deactivate':
        app.applicationStateChanged.emit(Qt.ApplicationInactive)
    elif interruption == 'right-click':
        QTest.mouseClick(
            widget.viewport(), Qt.RightButton, Qt.NoModifier, position
        )
    else:
        widget.scrollToItem(widget.item(6), QAbstractItemView.PositionAtBottom)

    if phase == 'held':
        QTest.mouseRelease(
            widget.viewport(), Qt.LeftButton, Qt.NoModifier, position
        )

    app.processEvents()
    assert widget.verticalScrollBar().value() == before
    QTest.keyClick(widget, Qt.Key_Down)
    app.processEvents()
    assert widget.currentRow() == 7
    assert _row_fully_visible(widget, 8)
    widget.close()


def test_thumbnail_lost_release_does_not_block_keyboard_lookahead() -> None:
    """
    Recover when a left-button release never reaches the strip.

    A modal dialog or another window can swallow the release. Without recovery,
    the stale gesture would suppress keyboard lookahead until the next click.
    """
    app, widget = _create_scrollable_thumbnail_list()
    _, position, _ = _prepare_click_on_row_6(widget, app)
    other_window = QWidget()
    other_window.resize(80, 80)
    other_window.show()
    app.processEvents()

    QTest.mousePress(widget.viewport(), Qt.LeftButton, Qt.NoModifier, position)
    # Releasing over another window clears Qt's global button state without
    # delivering a release to the strip, like a release a modal swallowed.
    QTest.mouseRelease(other_window, Qt.LeftButton)
    app.processEvents()
    assert not QApplication.mouseButtons() & Qt.LeftButton

    QTest.keyClick(widget, Qt.Key_Down)
    app.processEvents()
    assert widget.currentRow() == 7
    assert _row_fully_visible(widget, 8)
    other_window.close()
    widget.close()


def test_thumbnail_auto_scroll_disabled_skips_lookahead() -> None:
    """
    Follow Qt's auto-scroll setting for current-row lookahead.

    Lookahead extends Qt's own current-row scroll, so disabling auto-scroll
    must leave the strip position alone as well.
    """
    app, widget = _create_scrollable_thumbnail_list()
    _prepare_click_on_row_6(widget, app)
    widget.setAutoScroll(False)
    before = widget.verticalScrollBar().value()

    widget.setCurrentRow(6)
    app.processEvents()

    assert widget.verticalScrollBar().value() == before
    widget.close()


def test_thumbnail_suspended_lookahead_keeps_scroll_position() -> None:
    """
    Skip neighbor reveal while a caller rebuilds and restores the strip.

    Metadata and scene refreshes restore a captured position afterwards, so
    lookahead during the rebuild would only add a scroll to overwrite.
    """
    app, widget = _create_scrollable_thumbnail_list()
    _prepare_click_on_row_6(widget, app)
    before = widget.verticalScrollBar().value()

    with widget.suspend_lookahead():
        widget.setCurrentRow(6)
        widget.scrollToItem(widget.item(6))

    app.processEvents()
    assert widget.verticalScrollBar().value() == before
    assert not _row_fully_visible(widget, 7)
    widget.close()


def test_thumbnail_reshown_strip_reveals_current_and_neighbor() -> None:
    """
    Catch up on current-row changes made while the strip was hidden.

    Compare mode hides the strip, so Qt skips its auto-scroll. When the strip
    returns, the current card and its neighbor should be visible.
    """
    app, widget = _create_scrollable_thumbnail_list()
    widget.hide()
    widget.setCurrentRow(6)
    widget.show()
    app.processEvents()

    assert _row_fully_visible(widget, 6)
    assert _row_fully_visible(widget, 7)
    widget.close()


@_DIRECTIONS
@pytest.mark.parametrize(
    'boundary', ['end-row', 'short-viewport', 'exact-fit']
)
def test_thumbnail_navigation_prioritizes_current_row(
        boundary: str, direction: str
) -> None:
    """
    Keep the current card visible at list and viewport boundaries.

    Lookahead must tolerate a missing neighbor row or insufficient space. When
    two cards fit exactly, Qt's extra scroll padding must not clip the current
    card or cause repeated scroll requests to move it.
    """
    app, widget = _create_scrollable_thumbnail_list()
    step = _step(direction)
    target_row = 11 if direction == 'down' else 0
    if boundary != 'end-row':
        target_row = 6
        height = 140
        if boundary == 'exact-fit':
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
    widget.setCurrentRow(target_row)
    app.processEvents()
    target = widget.item(target_row)
    assert _row_fully_visible(widget, target_row)
    before = widget.verticalScrollBar().value()
    widget.scrollToItem(target)
    app.processEvents()
    assert widget.verticalScrollBar().value() == before
    viewport = widget.viewport().rect()
    if boundary == 'short-viewport':
        assert not _row_fully_visible(widget, target_row + step)
    elif boundary == 'exact-fit':
        pair_rects = sorted(
            (widget.visualItemRect(widget.item(row)) for row in pair),
            key=lambda rect: rect.top(),
        )
        assert pair_rects[0].top() == 0
        assert pair_rects[1].bottom() == viewport.bottom()

    widget.close()


@pytest.mark.parametrize(
    'hint',
    [QAbstractItemView.PositionAtTop, QAbstractItemView.PositionAtBottom],
    ids=['top', 'bottom'],
)
def test_thumbnail_scroll_preserves_explicit_position(hint: Any) -> None:
    """
    Honor explicit positioning even when the next card stays offscreen.

    Scene edits use explicit scroll anchors, which lookahead must not replace.
    """
    app, widget = _create_scrollable_thumbnail_list()
    widget.setCurrentRow(6)
    target = widget.currentItem()
    widget.scrollToItem(target, hint)
    app.processEvents()
    rect = widget.visualItemRect(target)
    viewport = widget.viewport().rect()
    if hint == QAbstractItemView.PositionAtTop:
        assert abs(rect.top() - viewport.top()) <= widget.spacing()
    else:
        assert abs(rect.bottom() - viewport.bottom()) <= widget.spacing()
        assert widget.visualItemRect(widget.item(7)).bottom() > (
            viewport.bottom()
        )

    widget.close()
