from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QSettings

from easy_cull.ui.identity import APP_NAME
from easy_cull.ui.main_window.build import COMPARE_PHOTO_LIMIT_SETTINGS_KEY


@pytest.fixture(autouse=True)
def clear_compare_photo_limit_setting() -> Iterator[None]:
    settings = QSettings(APP_NAME, APP_NAME)
    had_original_value = settings.contains(COMPARE_PHOTO_LIMIT_SETTINGS_KEY)
    original_value = settings.value(COMPARE_PHOTO_LIMIT_SETTINGS_KEY)
    settings.remove(COMPARE_PHOTO_LIMIT_SETTINGS_KEY)
    settings.sync()
    yield
    if had_original_value:
        settings.setValue(COMPARE_PHOTO_LIMIT_SETTINGS_KEY, original_value)
    else:
        settings.remove(COMPARE_PHOTO_LIMIT_SETTINGS_KEY)

    settings.sync()
