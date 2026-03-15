"""Recall scoring utilities.

Simplified for three-tier architecture. Scoring is mainly used for
ranking grep results by cognitive state relevance.
"""

from __future__ import annotations

from alive_memory.config import AliveConfig
from alive_memory.types import CognitiveState


def score_grep_result(
    content: str,
    subdir: str,
    state: CognitiveState,
    *,
    config: AliveConfig | None = None,
) -> float:
    """Score a grep result for cognitive relevance.

    Factors:
      - Subdir priority (self > journal > visitors > reflections > threads)
      - Mood congruence (keyword-based)
      - Recency (for journal entries with dates in filename)

    Returns a float score (higher = more relevant).
    """
    score = 0.5

    # Subdir priority
    subdir_weights = {
        "self": 0.9,
        "journal": 0.7,
        "visitors": 0.6,
        "reflections": 0.5,
        "threads": 0.4,
        "collection": 0.3,
    }
    score += subdir_weights.get(subdir, 0.3) * 0.3

    # Content length bonus (longer = richer context)
    words = len(content.split())
    score += min(0.1, words * 0.002)

    return score


def decay_strength(
    strength: float,
    age_hours: float,
    *,
    config: AliveConfig | None = None,
) -> float:
    """Apply time-based decay (kept for backward compatibility).

    Used by meta-controller and identity systems.
    """
    cfg = config or AliveConfig()
    decay_rate = cfg.get("consolidation.decay_rate", 0.01)
    floor = cfg.get("consolidation.decay_floor", 0.05)
    new_strength = strength - decay_rate * age_hours
    return float(max(floor, new_strength))
