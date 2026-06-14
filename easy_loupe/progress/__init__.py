"""Shared progress reporting primitives for long-running workflows."""

from __future__ import annotations

from easy_loupe.progress.callbacks import (
    accepted_keyword_arguments,
    accepts_keyword_argument,
)
from easy_loupe.progress.models import (
    LegacyProgressCallback,
    ProgressSnapshot,
    ProgressStageDefinition,
    ProgressStageSnapshot,
    ProgressStageStatus,
    StructuredProgressCallback,
)
from easy_loupe.progress.reporter import (
    CountedProgressStage,
    ProgressReporter,
)

__all__ = [
    'CountedProgressStage',
    'LegacyProgressCallback',
    'ProgressReporter',
    'ProgressSnapshot',
    'ProgressStageDefinition',
    'ProgressStageSnapshot',
    'ProgressStageStatus',
    'StructuredProgressCallback',
    'accepted_keyword_arguments',
    'accepts_keyword_argument',
]
