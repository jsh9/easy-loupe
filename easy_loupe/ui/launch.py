"""Shared UI launch request models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from easy_loupe.core.photo_library import PhotoLibrary


@dataclass(frozen=True)
class CullingLaunchRequest:
    """Request to open the culling workspace for a hydrated photo folder."""

    folder: Path
    selected_photo_id: str
    enter_browse: bool = False
    preloaded_library: PhotoLibrary | None = None
