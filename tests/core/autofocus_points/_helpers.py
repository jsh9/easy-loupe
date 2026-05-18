"""Shared helpers for autofocus-point tests."""

from __future__ import annotations

from typing import Any


def first_int(metadata: dict[str, Any], keys: list[str]) -> int | None:
    """Return the first integer value from test metadata."""
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return int(value)

        if isinstance(value, str) and value.isdigit():
            return int(value)

    return None
