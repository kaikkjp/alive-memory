"""Thalamus — raw event → structured Perception with salience scoring.

Extracted from engine/pipeline/thalamus.py.
Stripped: routing decisions, token budgets, memory request building (all application-level).
Kept: event-to-perception conversion, salience scoring.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from alive_memory.config import AliveConfig
from alive_memory.types import EventType, Perception


def perceive(
    event_type: str | EventType,
    content: str,
    *,
    config: AliveConfig | None = None,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> Perception:
    """Convert a raw event into a structured Perception.

    Args:
        event_type: Type of event (conversation, action, observation, system).
        content: Raw event text.
        config: Configuration for salience tuning.
        metadata: Additional metadata to attach.
        timestamp: Event time (defaults to now UTC).

    Returns:
        A Perception with computed salience.
    """
    cfg = config or AliveConfig()

    # Normalize event type
    if isinstance(event_type, str):
        try:
            et = EventType(event_type)
        except ValueError:
            et = EventType.SYSTEM
    else:
        et = event_type

    ts = timestamp or datetime.now(timezone.utc)
    meta = metadata or {}

    # Compute salience
    salience = _compute_salience(et, content, cfg, meta)

    return Perception(
        event_type=et,
        content=content,
        salience=salience,
        timestamp=ts,
        metadata=meta,
    )


def _compute_salience(
    event_type: EventType,
    content: str,
    config: AliveConfig,
    metadata: dict[str, Any],
) -> float:
    """Compute salience score (0-1) for a perception.

    Salience determines how much attention this perception gets:
    - Base salience from config
    - Boost for conversations (social interaction)
    - Novelty bonus from content length and uniqueness signals
    """
    base = config.get("intake.base_salience", 0.5)

    # Conversation boost
    if event_type == EventType.CONVERSATION:
        base += config.get("intake.conversation_boost", 0.2)

    # Content-based novelty
    novelty_weight = config.get("intake.novelty_weight", 0.3)
    novelty = _estimate_novelty(content)
    base += novelty * novelty_weight

    # Metadata overrides
    if "salience" in metadata:
        base = float(metadata["salience"])

    return max(0.0, min(1.0, base))


def _estimate_novelty(content: str) -> float:
    """Estimate content novelty from surface features.

    Simple heuristic: longer, more varied content is more novel.
    """
    if not content:
        return 0.0

    words = content.split()
    word_count = len(words)
    unique_ratio = len(set(w.lower() for w in words)) / max(word_count, 1)

    # Short messages: low novelty
    if word_count < 3:
        return 0.1

    # Medium messages: moderate novelty
    if word_count < 20:
        return 0.2 + unique_ratio * 0.2

    # Long, varied messages: high novelty
    return min(0.5, 0.3 + unique_ratio * 0.3)
