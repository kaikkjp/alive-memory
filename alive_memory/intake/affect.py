"""Affect Lens — emotional valence computation.

Extracted from engine/pipeline/affect.py.
Stripped: pipeline-stage interface, DrivesState dependency.
Kept: valence computation, time dilation math.
"""

from __future__ import annotations

import random

from alive_memory.types import DriveState, MoodState, Perception


def apply_affect(
    perception: Perception,
    mood: MoodState,
    drives: DriveState,
) -> Perception:
    """Color a perception with current emotional state.

    Modifies salience based on mood valence and returns the perception.
    Negative mood amplifies salience (things feel heavier).
    """
    if mood.valence < -0.3:
        perception.salience = min(1.0, perception.salience + 0.1)
    elif mood.valence > 0.3 and perception.metadata.get("valence", 0) < 0:
        # Positive mood: slightly dampens negative events
        perception.salience = max(0.0, perception.salience - 0.05)

    return perception


def compute_valence(content: str, mood: MoodState) -> float:
    """Estimate emotional valence of content text.

    Simple keyword-based approach. Returns -1 to 1.
    Biased toward current mood (mood-congruent perception).
    """
    positive = {"happy", "love", "beautiful", "wonderful", "thank", "great",
                "amazing", "joy", "good", "kind", "warm", "friend", "smile",
                "laugh", "gift", "welcome", "nice", "sweet"}
    negative = {"sad", "angry", "hate", "ugly", "terrible", "bad", "awful",
                "pain", "hurt", "lonely", "alone", "cold", "leave", "gone",
                "sorry", "lost", "miss", "cry", "fear", "worry"}

    words = set(content.lower().split())
    pos_count = len(words & positive)
    neg_count = len(words & negative)
    total = pos_count + neg_count

    base_valence = 0.0 if total == 0 else (pos_count - neg_count) / total

    # Mood-congruent bias: current mood shifts perception
    mood_bias = mood.valence * 0.2
    return max(-1.0, min(1.0, base_valence + mood_bias))


def time_dilation(drives: DriveState) -> float:
    """Compute subjective time dilation from drive state.

    Social hunger makes time feel slower (loneliness drags).
    High curiosity makes time fly.
    """
    d = 1.0
    d *= 1.0 + 0.6 * max(0.0, drives.social - 0.6)
    d *= 1.0 - 0.5 * max(0.0, drives.curiosity - 0.6)
    return max(0.7, min(1.3, d + random.uniform(-0.08, 0.08)))
