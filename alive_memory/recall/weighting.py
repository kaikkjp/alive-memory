"""Re-ranking math: strength, valence, drive-coupling, decay, recall count.

These scoring functions take raw search results and re-rank them
based on cognitive state (mood, drives, recency).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from alive_memory.config import AliveConfig
from alive_memory.types import CognitiveState, DriveState, Memory, MoodState


def score_memory(
    memory: Memory,
    state: CognitiveState,
    *,
    similarity: float = 1.0,
    config: AliveConfig | None = None,
) -> float:
    """Compute a composite relevance score for a memory.

    Combines:
    - Vector similarity (from search)
    - Consolidation strength
    - Emotional valence congruence (mood-congruent recall)
    - Drive coupling
    - Recency decay
    - Recall frequency bonus

    Returns a float score (higher = more relevant).
    """
    cfg = config or AliveConfig()
    w_strength = cfg.get("recall.strength_weight", 0.3)
    w_valence = cfg.get("recall.valence_weight", 0.2)
    w_drive = cfg.get("recall.drive_weight", 0.2)
    w_recency = cfg.get("recall.recency_weight", 0.3)

    # Base: vector similarity
    score = similarity

    # Strength: stronger memories are more accessible
    score += memory.strength * w_strength

    # Valence congruence: mood-matching memories surface more easily
    valence_match = 1.0 - abs(state.mood.valence - memory.valence)
    score += valence_match * w_valence

    # Drive coupling: memories coupled to active drives are more relevant
    drive_score = _drive_coupling_score(memory.drive_coupling, state.drives)
    score += drive_score * w_drive

    # Recency: recent memories have a bonus, old memories decay
    recency = _recency_score(memory.formed_at)
    score += recency * w_recency

    # Recall frequency: small bonus for frequently recalled memories
    recall_bonus = min(0.1, memory.recall_count * 0.01)
    score += recall_bonus

    return score


def _drive_coupling_score(
    coupling: dict[str, float], drives: DriveState
) -> float:
    """Score how well a memory's drive-coupling matches current drives.

    A memory coupled to an active drive (high value) is more relevant.
    """
    if not coupling:
        return 0.0

    total = 0.0
    for drive_name, coupling_strength in coupling.items():
        current = getattr(drives, drive_name, 0.5)
        # Active drive (high value) + strong coupling = high relevance
        total += coupling_strength * current

    return total / max(len(coupling), 1)


def _recency_score(formed_at: datetime, half_life_hours: float = 24.0) -> float:
    """Exponential decay based on memory age.

    Half-life of ~24 hours: memory formed 24h ago has 0.5 recency.
    """
    now = datetime.now(timezone.utc)
    if formed_at.tzinfo is None:
        formed_at = formed_at.replace(tzinfo=timezone.utc)
    age_hours = (now - formed_at).total_seconds() / 3600
    return math.exp(-0.693 * age_hours / half_life_hours)


def decay_strength(
    strength: float,
    age_hours: float,
    *,
    config: AliveConfig | None = None,
) -> float:
    """Apply time-based decay to memory strength.

    Uses a slow linear decay with a floor to prevent total erasure.
    """
    cfg = config or AliveConfig()
    decay_rate = cfg.get("consolidation.decay_rate", 0.01)
    floor = cfg.get("consolidation.decay_floor", 0.05)
    new_strength = strength - decay_rate * age_hours
    return max(floor, new_strength)
