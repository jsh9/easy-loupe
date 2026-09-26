"""
Keyboard-navigation neighbor lookahead for the vertical thumbnail strip.

After a keyboard move changes the current left-strip row, the strip also keeps
the neighboring row in the direction of travel fully visible, so users can see
the next (or previous) photo or scene stack before reaching it.

Only keyboard navigation reveals the neighbor. ``ThumbnailListWidget`` calls
this module after its own key presses, and ``MainWindow`` calls it after
Up/Down in the scene strip moves the left strip. Mouse clicks, list rebuilds,
and showing the strip again use plain Qt scrolling, so a clicked card never
moves to make room for its neighbor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QAbstractItemView

if TYPE_CHECKING:
    from PySide6.QtWidgets import QListWidget


def reveal_neighbor_after_move(
        list_widget: QListWidget, previous_row: int
) -> None:
    """
    Fit the current row and its neighbor after a keyboard move.

    ``previous_row`` is the current row before the key was handled. Callers run
    this after Qt has already scrolled the new current row into view, so this
    only adds the extra scroll for the neighbor. Keys that did not move the
    row, such as Up on the first row, leave the strip alone.
    """
    current_row = list_widget.currentRow()
    if previous_row < 0 or current_row < 0 or current_row == previous_row:
        return

    if (
        not list_widget.isVisible()
        # The overflow math uses pixels; per-item scrollbars use rows.
        or list_widget.verticalScrollMode()
        != QAbstractItemView.ScrollMode.ScrollPerPixel
    ):
        return

    direction = 1 if current_row > previous_row else -1
    current = list_widget.item(current_row)
    neighbor = list_widget.item(current_row + direction)
    # The first or last row has no neighbor to show, so Qt's own current-row
    # scroll is already the right placement.
    if current is None or neighbor is None:
        return

    current_rect = list_widget.visualItemRect(current)
    neighbor_rect = list_widget.visualItemRect(neighbor)
    if not current_rect.isValid() or not neighbor_rect.isValid():
        return

    # Use actual card bounds so taller scene stacks and the list spacing
    # between cards are included. A short viewport keeps Qt's current-row
    # placement instead of clipping the current card.
    top = min(current_rect.top(), neighbor_rect.top())
    bottom = max(current_rect.bottom(), neighbor_rect.bottom())
    viewport_rect = list_widget.viewport().rect()
    if bottom - top + 1 > viewport_rect.height():
        return

    # Qt already made the current card fully visible, so only the neighbor's
    # side can overflow: below when moving down, above when moving up.
    if bottom > viewport_rect.bottom():
        overflow = bottom - viewport_rect.bottom()
    elif top < viewport_rect.top():
        overflow = top - viewport_rect.top()
    else:
        return

    # Move the pixel scrollbar only by the overflow. Qt's EnsureVisible adds
    # spacing beyond the card, which can clip the current row when the two
    # cards fit exactly.
    scroll_bar = list_widget.verticalScrollBar()
    scroll_bar.setValue(scroll_bar.value() + overflow)
