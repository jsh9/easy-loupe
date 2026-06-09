from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import easy_loupe.ui.viewers.shell as shell_module
from easy_loupe.progress import ProgressStageSnapshot

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest


def test_build_viewer_shortcuts_wires_common_zoom_and_pan_controls() -> None:
    """Build the shared viewer shortcut set in the expected order."""
    shortcut_keys: list[object] = []
    callbacks: list[Callable[[], None]] = []
    zoom_calls: list[float] = []
    pan_calls: list[tuple[int, int]] = []

    def make_shortcut(key: object, callback: Callable[[], None]) -> object:
        shortcut_keys.append(key)
        callbacks.append(callback)
        return key

    shortcuts = shell_module.build_viewer_shortcuts(
        make_shortcut,
        zoom_step=zoom_calls.append,
        keyboard_pan_by=lambda x, y: pan_calls.append((x, y)),
    )

    assert shortcuts == ['-', '=', Qt.Key_Plus, 'W', 'A', 'S', 'D']
    for callback in callbacks:
        callback()

    assert zoom_calls == [0.8, 1.25, 1.25]
    assert pan_calls == [(0, -1), (-1, 0), (0, 1), (1, 0)]


def test_progress_stage_row_hides_zero_total_but_keeps_unknown_indeterminate() -> (
    None
):
    """
    Verify empty stages render as status-only rows without losing spinners.

    Zero-work stages should not show fake empty bars, while active unknown
    totals still need an indeterminate bar for long-running uncounted work.
    """
    app = QApplication.instance() or QApplication([])
    row = shell_module.ProgressStageRow(
        ProgressStageSnapshot(
            'empty', 'No work', current=0, total=0, status='complete'
        )
    )
    row.show()
    app.processEvents()

    assert row.count_label.isHidden() is True
    assert row.progress_bar.isHidden() is True

    row.update_stage(
        ProgressStageSnapshot(
            'unknown',
            'Scanning folder',
            current=None,
            total=None,
            status='active',
        )
    )
    app.processEvents()

    assert row.progress_bar.isVisible() is True
    assert row.progress_bar.minimum() == 0
    assert row.progress_bar.maximum() == 0

    row.close()


def test_resolve_widget_screen_prefers_window_handle_screen(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the native window handle screen before geometry fallback."""
    screen = object()

    class FakeHandle:
        @staticmethod
        def screen() -> object:
            return screen

    class FakeWidget:
        @staticmethod
        def windowHandle() -> FakeHandle:  # noqa: N802 - Qt-style fake
            return FakeHandle()

    def fail_screen_at(_point: object) -> object:
        raise AssertionError('screenAt fallback should not be used')

    monkeypatch.setattr(
        shell_module.QGuiApplication, 'screenAt', fail_screen_at
    )

    assert shell_module.resolve_widget_screen(FakeWidget()) is screen


def test_resolve_widget_screen_falls_back_to_frame_geometry(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use QGuiApplication.screenAt when no window-handle screen exists."""
    screen = object()
    center = object()
    points: list[object] = []

    class FakeGeometry:
        @staticmethod
        def center() -> object:
            return center

    class FakeWidget:
        @staticmethod
        def windowHandle() -> None:  # noqa: N802 - Qt-style fake
            return None

        @staticmethod
        def frameGeometry() -> FakeGeometry:  # noqa: N802 - Qt-style fake
            return FakeGeometry()

    def screen_at(point: object) -> object:
        points.append(point)
        return screen

    monkeypatch.setattr(shell_module.QGuiApplication, 'screenAt', screen_at)

    assert shell_module.resolve_widget_screen(FakeWidget()) is screen
    assert points == [center]
