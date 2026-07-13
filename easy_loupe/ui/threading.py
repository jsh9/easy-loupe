"""
Qt thread lifecycle helpers shared by UI windows.

Qt can stop running a thread before the owner has received ``finished`` and
cleared its Python reference. Keep those states distinct so close paths can
wait for wrapper cleanup while replacement paths can detect inactive threads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


def thread_slot_active(thread: object | None) -> bool:
    """Return whether an owner still stores a thread reference."""
    return thread is not None


def thread_is_running(thread: object | None) -> bool:
    """Return whether a stored thread reference is currently running."""
    if thread is None:
        return False

    is_running = getattr(thread, 'isRunning', None)
    if callable(is_running):
        return bool(is_running())

    return True


def any_thread_slot_active(*threads: object | None) -> bool:
    """Return whether any owner still stores a thread reference."""
    return any(thread_slot_active(thread) for thread in threads)


def request_thread_shutdown(
        thread: object | None, worker: object | None
) -> None:
    """
    Ask a worker/thread pair to stop without clearing owner references.

    Owners clear their stored references from ``QThread.destroyed`` callbacks.
    Keeping that rule in one helper avoids app-close paths dropping the Python
    wrappers while Qt is still unwinding worker-thread object deletion.
    """
    if worker is not None:
        cancel = getattr(worker, 'cancel', None)
        if callable(cancel):
            cancel()

    if thread is None:
        return

    if thread_is_running(thread):
        quit_thread = getattr(thread, 'quit', None)
        if callable(quit_thread):
            quit_thread()

        return

    # A thread can stop before its queued owner cleanup runs, or it may never
    # have started if Quit was delivered during setup. Ensure its QObject
    # destruction is queued so close-time cleanup has a terminal signal to
    # observe instead of retaining the hidden window indefinitely.
    delete_thread = getattr(thread, 'deleteLater', None)
    if callable(delete_thread):
        delete_thread()


@dataclass(frozen=True)
class ThreadSlot:
    """Attr-backed owner slot for one Qt worker/thread pair."""

    owner: object
    name: str
    thread_attr: str
    worker_attr: str

    @property
    def thread(self) -> object | None:
        """The currently stored thread reference."""
        return getattr(self.owner, self.thread_attr, None)

    @property
    def worker(self) -> object | None:
        """The currently stored worker reference."""
        return getattr(self.owner, self.worker_attr, None)

    def is_active(self) -> bool:
        """Return whether the owner still holds a thread reference."""
        return thread_slot_active(self.thread)

    def request_shutdown(self) -> None:
        """Request close-time shutdown without clearing owner references."""
        request_thread_shutdown(self.thread, self.worker)

    def stop_for_replacement(self) -> None:
        """
        Request replacement shutdown and clear inactive stored slots.

        Replacement paths may drop already-stopped wrappers because the window
        remains alive. Close paths must keep them until finished cleanup runs.
        """
        thread = self.thread
        self.request_shutdown()
        if thread is None or not thread_is_running(thread):
            self.clear()

    def clear_if_current(
            self, finished_thread: object, finished_worker: object
    ) -> bool:
        """
        Clear the slot only when a finished pair is still current.

        Queued finished signals can arrive after replacement work stores a new
        pair, so identity matching keeps stale callbacks from clearing it.
        """
        if self.thread is finished_thread and self.worker is finished_worker:
            self.clear()
            return True

        return False

    def clear(self) -> None:
        """Clear the owner's stored thread and worker references."""
        setattr(self.owner, self.thread_attr, None)
        setattr(self.owner, self.worker_attr, None)


class ThreadSlotGroup:
    """Named collection of attr-backed Qt thread slots."""

    def __init__(self, slots: Iterable[ThreadSlot]) -> None:
        self._slots = {slot.name: slot for slot in slots}

    def slot(self, name: str) -> ThreadSlot:
        """Return a named thread slot."""
        return self._slots[name]

    def any_active(self) -> bool:
        """Return whether any slot still stores a thread reference."""
        return any(slot.is_active() for slot in self._slots.values())

    def request_shutdown_all(self) -> None:
        """Request close-time shutdown for every stored thread slot."""
        for slot in self._slots.values():
            slot.request_shutdown()

    def stop_all_for_replacement(self) -> None:
        """Request replacement shutdown for every stored thread slot."""
        for slot in self._slots.values():
            slot.stop_for_replacement()

    def clear_if_current(
            self,
            name: str,
            finished_thread: object,
            finished_worker: object,
    ) -> bool:
        """Clear a named slot only when a finished pair is still current."""
        return self.slot(name).clear_if_current(
            finished_thread, finished_worker
        )
