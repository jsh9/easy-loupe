"""
Neighbor-card lookahead for the vertical thumbnail strip.

When the current left-strip row changes, the strip also keeps the neighboring
row in the direction of travel fully visible, so users can see the next (or
previous) photo or scene stack before reaching it. Mouse gestures delay that
scroll until the pointer has released and the double-click interval passes, so
the card under the pointer never moves while it can still be clicked.

``ThumbnailListWidget`` owns one ``ThumbnailLookahead`` and forwards Qt hooks
to it. The hooks cover two entry points: ``currentChanged`` catches Qt's
internal auto-scroll after keyboard, mouse, and programmatic current-row
changes, while ``scrollToItem`` catches Python callers that scroll without
changing the current row. Direct ``scrollTo`` calls and scrollbar changes
bypass both, which keeps wheel scrolling and explicit scroll restoration
untouched.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QAbstractItemView, QApplication

if TYPE_CHECKING:
    from collections.abc import Iterator

    from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget


def _mouse_settle_delay_ms() -> int:
    """Return how long a clicked card stays still before lookahead scrolls."""
    return QApplication.styleHints().mouseDoubleClickInterval()


class ThumbnailLookahead(QObject):
    """Scroll controller that reveals the neighbor of the current row."""

    def __init__(self, list_widget: QListWidget) -> None:
        super().__init__(list_widget)
        self._list = list_widget
        self._direction = 1
        self._suspend_depth = 0
        self._handling_mouse_event = False
        self._gesture_pending = False
        self._gesture_targets: list[QWidget] = []
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._finish_mouse_gesture)
        # Deactivation can arrive after release while the settle timer is
        # still queued, so listen at application level rather than via the
        # temporary press-target filter.
        QApplication.instance().applicationStateChanged.connect(
            self._handle_application_state_changed
        )

    def handle_current_changed(
            self, current_row: int, previous_row: int
    ) -> None:
        """Record the travel direction and reveal the following neighbor."""
        # Rebuilds report an invalid previous row, so they keep the last
        # direction instead of resetting lookahead to "next".
        if (
            current_row >= 0
            and previous_row >= 0
            and current_row != previous_row
        ):
            self._direction = 1 if current_row > previous_row else -1

        # Qt only scrolls the new current row into view when auto-scroll is
        # enabled; lookahead extends that scroll, so it follows the same rule.
        if self._list.hasAutoScroll():
            self.reveal_neighbor()

    def handle_scroll_request(
            self,
            item: QListWidgetItem,
            hint: QAbstractItemView.ScrollHint,
    ) -> None:
        """Extend default scrolls and let explicit positions win."""
        if hint != QAbstractItemView.ScrollHint.EnsureVisible:
            # Explicit anchors, such as scene-edit restoration, must not be
            # replaced by a mouse gesture that finishes afterwards.
            self.cancel_mouse_gesture()
            return

        if item is self._list.currentItem():
            self.reveal_neighbor()

    def handle_key_press(self) -> None:
        """Apply a pending click scroll before keyboard input moves cards."""
        # Keyboard input can move cards itself, so waiting out the
        # double-click interval no longer protects the clicked card.
        if self._settle_timer.isActive():
            self._finish_mouse_gesture()

    def begin_mouse_press(self, event: QMouseEvent) -> None:
        """Hold lookahead until the pressed left button is released."""
        self.cancel_mouse_gesture()
        if event.button() != Qt.MouseButton.LeftButton:
            # Right clicks open scene menus at the clicked card, so they add
            # no lookahead that could move the menu target.
            return

        viewport = self._list.viewport()
        # Qt delivers the release to the widget that received the press, even
        # when a thumbnail image child consumes it during minimap dragging.
        # Filtering that child plus the viewport, which receives directly
        # posted events, avoids an application-wide filter.
        targets = [viewport]
        child = viewport.childAt(event.position().toPoint())
        if child is not None:
            targets.append(child)

        self._gesture_pending = True
        self._gesture_targets = targets
        for target in targets:
            target.installEventFilter(self)

    @contextmanager
    def handle_mouse_event(self) -> Iterator[None]:
        """Block lookahead while Qt processes a press or release."""
        self._handling_mouse_event = True
        try:
            yield
        finally:
            self._handling_mouse_event = False

    @contextmanager
    def suspend(self) -> Iterator[None]:
        """Block lookahead while callers rebuild and restore scroll state."""
        self._suspend_depth += 1
        try:
            yield
        finally:
            self._suspend_depth -= 1

    def cancel_mouse_gesture(self) -> None:
        """Discard delayed scrolling when its gesture no longer applies."""
        self._settle_timer.stop()
        self._gesture_pending = False
        self._release_gesture_targets()

    def reveal_current_after_show(self) -> None:
        """Queue a current-row reveal once a reshown strip has geometry."""
        # Qt skips auto-scroll while the strip is hidden, such as in compare
        # mode, so the current card can be offscreen when the strip returns.
        QTimer.singleShot(0, self, self._reveal_current_if_visible)

    def reveal_neighbor(self) -> None:
        """Fit the current row and its neighbor when both fit together."""
        if not self._can_reveal():
            return

        current = self._list.currentItem()
        if current is None:
            return

        neighbor = self._list.item(self._list.currentRow() + self._direction)
        if neighbor is None:
            return

        current_rect = self._list.visualItemRect(current)
        neighbor_rect = self._list.visualItemRect(neighbor)
        if not current_rect.isValid() or not neighbor_rect.isValid():
            return

        # Use actual card bounds so taller scene stacks and the list spacing
        # between cards are included. A short viewport keeps Qt's
        # current-row placement instead of clipping the current card.
        top = min(current_rect.top(), neighbor_rect.top())
        bottom = max(current_rect.bottom(), neighbor_rect.bottom())
        viewport_rect = self._list.viewport().rect()
        if bottom - top + 1 > viewport_rect.height():
            return

        if bottom > viewport_rect.bottom():
            overflow = bottom - viewport_rect.bottom()
        elif top < viewport_rect.top():
            overflow = top - viewport_rect.top()
        else:
            return

        # Move the pixel scrollbar only by the overflow. Qt's EnsureVisible
        # adds spacing beyond the card, which can clip the current row when
        # the two cards fit exactly.
        scroll_bar = self._list.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.value() + overflow)

    def eventFilter(  # noqa: N802 - Qt API
            self, watched: QObject, event: QEvent
    ) -> bool:
        """Observe the pressed widget without consuming its events."""
        del watched
        if not self._gesture_pending:
            return False

        if event.type() in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
        }:
            # Another button joined the held gesture, so its outcome is no
            # longer a plain left click.
            self.cancel_mouse_gesture()
        elif (
            event.type() == QEvent.Type.MouseButtonRelease
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._release_gesture_targets()
            # Filters run before the receiver, and a second click may follow.
            # Waiting the double-click interval lets Qt finish release-time
            # selection and keeps a quick repeat click on the same card.
            self._settle_timer.start(_mouse_settle_delay_ms())

        return False

    def _can_reveal(self) -> bool:
        if (
            not self._list.isVisible()
            or self._suspend_depth
            or self._handling_mouse_event
            # The overflow math uses pixels; per-item scrollbars use rows.
            or self._list.verticalScrollMode()
            != QAbstractItemView.ScrollMode.ScrollPerPixel
        ):
            return False

        if self._gesture_pending:
            if (
                self._settle_timer.isActive()
                or QApplication.mouseButtons() & Qt.MouseButton.LeftButton
            ):
                return False

            # The button is up but no release reached the target, for example
            # because a modal dialog blocked it. Drop the stale gesture so it
            # cannot suppress later keyboard lookahead.
            self.cancel_mouse_gesture()

        return True

    def _finish_mouse_gesture(self) -> None:
        self.cancel_mouse_gesture()
        self.reveal_neighbor()

    def _handle_application_state_changed(
            self, state: Qt.ApplicationState
    ) -> None:
        # Activation can arrive during the click that activates the app, so
        # only leaving the active state cancels the pending scroll.
        if state != Qt.ApplicationState.ApplicationActive:
            self.cancel_mouse_gesture()

    def _release_gesture_targets(self) -> None:
        targets = self._gesture_targets
        self._gesture_targets = []
        for target in targets:
            try:
                target.removeEventFilter(self)
            except RuntimeError:
                # List rebuilds can delete the pressed card widget
                # mid-gesture; a deleted widget has no filter to remove.
                continue

    def _reveal_current_if_visible(self) -> None:
        current = self._list.currentItem()
        # The strip can be hidden again before this queued call runs, such
        # as when compare mode is re-entered right away.
        if current is not None and self._list.isVisible():
            self._list.scrollToItem(current)
