"""Cognition-only types — structured event input and scored perception output.

These types extend the alive_memory type system with multi-channel salience
scoring used by the thalamus v2 pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from alive_memory.types import EventType, Perception


@dataclass
class EventSchema:
    """Structured event input for the thalamus."""

    event_type: EventType
    content: str
    source: str = "chat"  # "chat", "sensor", "tool", "system"
    actor: str = "user"  # "user", "agent", "environment"
    timestamp: datetime | None = None  # defaults to now UTC
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now(UTC)


@dataclass
class ChannelScores:
    """Per-channel salience breakdown."""

    relevance: float = 0.0  # 0-1: goal + actionability
    surprise: float = 0.0  # 0-1: novelty + memory value
    impact: float = 0.0  # 0-1: affect + safety
    urgency: float = 0.0  # 0-1: time sensitivity


class SalienceBand(Enum):
    """Discrete salience bands for routing decisions."""

    DROP = 0  # 0.00-0.30
    STORE = 1  # 0.31-0.70
    PRIORITIZE = 2  # 0.71-1.00


@dataclass
class ChannelWeights:
    """Configurable weights for composite scoring."""

    relevance: float = 0.35
    surprise: float = 0.25
    impact: float = 0.20
    urgency: float = 0.20


@dataclass
class ScoredPerception:
    """Result of thalamus scoring -- carries channel scores + band + reasons."""

    event: EventSchema
    channels: ChannelScores
    salience: float  # composite score
    band: SalienceBand
    reasons: list[str]  # human-readable explanations
    novelty_factor: float = 1.0  # habituation decay applied
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_perception(self) -> Perception:
        """Bridge to legacy Perception type for backward compatibility."""
        return Perception(
            event_type=self.event.event_type,
            content=self.event.content,
            salience=self.salience,
            timestamp=self.timestamp,
            metadata=self.event.metadata,
        )
