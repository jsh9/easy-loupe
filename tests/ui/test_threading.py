from __future__ import annotations

from easy_loupe.ui.threading import ThreadSlot, ThreadSlotGroup


class FakeOwner:
    """Simple attr container for thread-slot helper tests."""


class FakeThread:
    def __init__(self, *, running: bool) -> None:
        self.running = running
        self.quit_calls = 0

    def isRunning(self) -> bool:  # noqa: N802 - Qt API
        return self.running

    def quit(self) -> None:
        self.quit_calls += 1


class FakeWorker:
    def __init__(self) -> None:
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1


class FakeWorkerWithoutCancel:
    """Worker stand-in that deliberately has no cancel hook."""


def test_thread_slot_active_tracks_stored_reference_not_running_state() -> (
    None
):
    """
    Verify close waits for a stored thread slot even after isRunning is false.

    The crash regression depends on this distinction: Qt may stop a thread
    before the owner has received the cleanup callback that clears the wrapper.
    """
    owner = FakeOwner()
    owner.thread = FakeThread(running=False)
    owner.worker = FakeWorker()
    slot = ThreadSlot(owner, 'test', 'thread', 'worker')
    group = ThreadSlotGroup([slot])

    assert slot.is_active() is True
    assert group.any_active() is True


def test_thread_slot_close_shutdown_preserves_owner_references() -> None:
    """
    Verify close-time shutdown never clears owner references directly.

    Even a stopped thread remains active for close purposes until the normal
    finished cleanup callback clears the stored slot.
    """
    owner = FakeOwner()
    owner.thread = FakeThread(running=False)
    owner.worker = FakeWorker()
    slot = ThreadSlot(owner, 'test', 'thread', 'worker')

    slot.request_shutdown()

    assert owner.thread is not None
    assert owner.worker is not None
    assert owner.worker.cancel_calls == 1
    assert owner.thread.quit_calls == 0


def test_thread_slot_replacement_cleanup_clears_inactive_slot() -> None:
    """
    Verify replacement cleanup can drop an already-inactive thread slot.

    Replacement paths do not need to wait for window teardown safety, so they
    can clear an inactive slot and allow newer work to start.
    """
    owner = FakeOwner()
    owner.thread = FakeThread(running=False)
    owner.worker = FakeWorker()
    slot = ThreadSlot(owner, 'test', 'thread', 'worker')

    slot.stop_for_replacement()

    assert owner.thread is None
    assert owner.worker is None


def test_thread_slot_stale_finished_pair_does_not_clear_new_slot() -> None:
    """
    Verify stale finished callbacks cannot clear newer thread references.

    This protects replacement-style flows where a queued old finished signal
    may arrive after a new worker/thread pair has been stored.
    """
    owner = FakeOwner()
    old_thread = FakeThread(running=False)
    old_worker = FakeWorker()
    new_thread = FakeThread(running=True)
    new_worker = FakeWorker()
    owner.thread = new_thread
    owner.worker = new_worker
    slot = ThreadSlot(owner, 'test', 'thread', 'worker')

    cleared = slot.clear_if_current(old_thread, old_worker)

    assert cleared is False
    assert owner.thread is new_thread
    assert owner.worker is new_worker


def test_thread_slot_request_shutdown_allows_worker_without_cancel() -> None:
    """
    Verify cancel is optional while running threads still receive quit.

    File-operation workers currently drain to completion and do not expose a
    cancel hook, so lifecycle shutdown must tolerate workers without cancel().
    """
    owner = FakeOwner()
    owner.thread = FakeThread(running=True)
    owner.worker = FakeWorkerWithoutCancel()
    slot = ThreadSlot(owner, 'test', 'thread', 'worker')

    slot.request_shutdown()

    assert owner.thread.quit_calls == 1
    assert owner.thread is not None
    assert owner.worker is not None
