"""Intake pipeline: raw events -> structured perceptions -> day moments.

Functions that moved to alive_cognition are re-exported here for backward
compatibility.  New code should import from alive_cognition directly.
"""

from __future__ import annotations

import warnings
from datetime import datetime
from typing import Any

from alive_cognition.affect import apply_affect, compute_valence
from alive_cognition.drives import update_drives, update_mood
from alive_memory.intake.file_watcher import FileWatcher
from alive_memory.intake.formation import form_moment
from alive_memory.intake.multimodal import perceive_media


def perceive(
    event_type: str | object,
    content: str,
    *,
    config: object | None = None,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
    clock: object | None = None,
    identity_keywords: list[str] | None = None,
) -> object:
    """Backward-compatible wrapper around the new Thalamus.

    Returns a legacy Perception via ScoredPerception.to_perception().
    New code should use alive_cognition.Thalamus directly.
    """
    warnings.warn(
        "alive_memory.intake.perceive is deprecated, use alive_cognition.Thalamus",
        DeprecationWarning,
        stacklevel=2,
    )
    from alive_cognition.thalamus import Thalamus
    from alive_cognition.types import EventSchema
    from alive_memory.types import EventType

    if isinstance(event_type, str):
        _valid = {e.value for e in EventType}
        et = EventType(event_type) if event_type in _valid else EventType.SYSTEM
    else:
        et = event_type

    thalamus = Thalamus(config=config, identity_keywords=identity_keywords)
    event = EventSchema(
        event_type=et,
        content=content,
        timestamp=timestamp,
        metadata=metadata or {},
    )
    return thalamus.perceive(event).to_perception()


__all__ = [
    "apply_affect",
    "compute_valence",
    "update_drives",
    "update_mood",
    "form_moment",
    "perceive",
    "perceive_media",
    "FileWatcher",
]
