from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QSettings

from easy_loupe.ui.identity import APP_NAME
from easy_loupe.ui.main_window.build import (
    COMPARE_PHOTO_LIMIT_SETTINGS_KEY,
    PHOTO_SORT_MODE_SETTINGS_KEY,
    PHOTO_SORT_REVERSED_SETTINGS_KEY,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def clear_main_window_settings() -> Iterator[None]:
    settings = QSettings(APP_NAME, APP_NAME)
    setting_keys = [
        COMPARE_PHOTO_LIMIT_SETTINGS_KEY,
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
