"""alive-cognition: Cognitive layer for AI agents.

Owns attention (thalamus), affect, drives, identity, and meta-control.
Depends on alive_memory for types, config, and storage primitives.
"""

from __future__ import annotations

from alive_cognition.affect import apply_affect, compute_valence
from alive_cognition.drives import update_drives, update_mood
from alive_cognition.thalamus import Thalamus
from alive_cognition.types import (
    ChannelScores,
    ChannelWeights,
    EventSchema,
    SalienceBand,
    ScoredPerception,
)

__all__ = [
    "Thalamus",
    "EventSchema",
    "ChannelScores",
    "ChannelWeights",
    "SalienceBand",
    "ScoredPerception",
    "apply_affect",
    "compute_valence",
    "update_drives",
    "update_mood",
]
