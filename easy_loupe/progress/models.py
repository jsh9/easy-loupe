"""Immutable progress payload models and callback type aliases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

ProgressStageStatus = Literal['pending', 'active', 'complete']
LegacyProgressCallback = Callable[[str, int], None]
StructuredProgressCallback = Callable[['ProgressSnapshot'], None]


@dataclass(frozen=True, slots=True)
class ProgressStageDefinition:
    """Static description of a workflow stage."""

    stage_id: str
    label: str
    total: int | None = None


@dataclass(frozen=True, slots=True)
class ProgressStageSnapshot:
    """Immutable progress state for one workflow stage."""

    stage_id: str
    label: str
    current: int | None
    total: int | None
    status: ProgressStageStatus

    def count_text(self) -> str:
        """Return count text only for positive-total determinate stages."""
        if self.total is None or self.total <= 0:
            return ''

        current = self.current if self.current is not None else 0
        return f'{current} of {self.total}'

    def progress_value(self) -> int:
        """Return bounded progress value, including zero-work completion."""
        if self.total is None or self.total <= 0:
            return 100 if self.status == 'complete' else 0

        current = self.current if self.current is not None else 0
        return max(0, min(self.total, current))


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    """Immutable progress payload emitted to structured UI renderers."""

    workflow_label: str
    current_message: str
    overall_progress: int | None
    stages: tuple[ProgressStageSnapshot, ...]
