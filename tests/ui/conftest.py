from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QWidget

from easy_loupe.ui.identity import APP_NAME
from easy_loupe.ui.main_window.build import (
    COMPARE_PHOTO_LIMIT_SETTINGS_KEY,
    PHOTO_LOAD_RECURSIVELY_SETTINGS_KEY,
    PHOTO_SORT_MODE_SETTINGS_KEY,
    PHOTO_SORT_REVERSED_SETTINGS_KEY,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def show_windows_without_desktop_activation(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Show top-level UI test widgets without asking the OS for focus.

    The UI tests need real widget geometry and paint events, but normal
    ``show()`` calls can pull EasyLoupe in front of the developer's active app.
    Keeping the non-activating flag in the shared fixture prevents that focus
    theft without changing production window behavior.
    """
    original_show = QWidget.show

    def show_without_desktop_activation(widget: QWidget) -> None:
        if widget.isWindow():
            widget.setAttribute(
                Qt.WidgetAttribute.WA_ShowWithoutActivating,
                True,
            )

        original_show(widget)

    monkeypatch.setattr(QWidget, 'show', show_without_desktop_activation)


@pytest.fixture(autouse=True)
def clear_main_window_settings() -> Iterator[None]:
    """
    Isolate persisted main-window preferences between UI tests.

    Tests exercise real ``QSettings`` behavior, so each case starts without
    state left by earlier tests and restores the developer's original values
    afterward instead of overwriting local application preferences.
    """
    settings = QSettings(APP_NAME, APP_NAME)
    setting_keys = [
        COMPARE_PHOTO_LIMIT_SETTINGS_KEY,
        PHOTO_LOAD_RECURSIVELY_SETTINGS_KEY,
        PHOTO_SORT_MODE_SETTINGS_KEY,
        PHOTO_SORT_REVERSED_SETTINGS_KEY,
    ]
    original_values = {
        key: settings.value(key)
        for key in setting_keys
        if settings.contains(key)
    }
    for key in setting_keys:
        settings.remove(key)

    settings.sync()
    yield
    for key in setting_keys:
        if key in original_values:
            settings.setValue(key, original_values[key])
        else:
            settings.remove(key)

    settings.sync()
