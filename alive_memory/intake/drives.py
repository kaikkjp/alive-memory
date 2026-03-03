"""Drive state updates: homeostatic pull, event-driven changes, mood coupling.

Extracted from engine/pipeline/hypothalamus.py.
Stripped: session tracking (application concern), visitor-specific events,
          epistemic curiosities, feelings text generation.
Kept: drive update math, homeostatic pull, diminishing returns, mood coupling.
"""

from __future__ import annotations

from alive_memory.config import AliveConfig
from alive_memory.types import DriveState, EventType, MoodState, Perception


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def update_drives(
    drives: DriveState,
    perceptions: list[Perception],
    elapsed_hours: float,
    *,
    config: AliveConfig | None = None,
    social_sensitivity: float = 0.5,
) -> DriveState:
    """Update drives based on time passage and new perceptions.

    Args:
        drives: Current drive state.
        perceptions: New perceptions this cycle.
        elapsed_hours: Time since last update.
        config: Configuration parameters.
        social_sensitivity: How much social events affect drives (0-1).

    Returns:
        New DriveState (original is not mutated).
    """
    cfg = config or AliveConfig()

    eq_pull = cfg.get("drives.equilibrium_pull", 0.02)
    dim_returns = cfg.get("drives.diminishing_returns", 0.8)
    ss = social_sensitivity

    new = DriveState(
        curiosity=drives.curiosity,
        social=drives.social,
        expression=drives.expression,
        rest=drives.rest,
    )

    # Time-based drift
    new.social = clamp(new.social + 0.01 * ss * elapsed_hours)
    new.curiosity = clamp(new.curiosity + 0.005 * elapsed_hours)
    new.expression = clamp(new.expression + 0.008 * elapsed_hours)

    # Homeostatic pull toward equilibrium (0.5)
    for drive_name in ("curiosity", "social", "expression", "rest"):
        current = getattr(new, drive_name)
        equilibrium = 0.5
        distance = abs(equilibrium - current)
        delta = (equilibrium - current) * eq_pull * elapsed_hours

        # Exponential spring at extremes
        if distance > 0.5:
            delta *= 1 + distance * 3.0

        setattr(new, drive_name, clamp(current + delta))

    # Event-driven changes
    conversation_count = 0
    for p in perceptions:
        if p.event_type == EventType.CONVERSATION:
            conversation_count += 1
            # Social relief with diminishing returns
            relief = 0.1 * (1.0 + (1.0 - ss)) / (1 + conversation_count * 0.3)
            new.social = clamp(new.social - relief)

        elif p.event_type == EventType.ACTION:
            # Expression relief
            new.expression = clamp(new.expression - 0.05)

        elif p.event_type == EventType.OBSERVATION:
            # Curiosity stimulation
            new.curiosity = clamp(new.curiosity + p.salience * 0.05)

    return new


def update_mood(
    mood: MoodState,
    drives: DriveState,
    perceptions: list[Perception],
    elapsed_hours: float,
    *,
    config: AliveConfig | None = None,
) -> MoodState:
    """Update mood based on drives and perceptions.

    Drive-to-mood coupling:
    - High social hunger → negative valence pressure
    - Conversations → positive valence relief
    - Low stimulation → arousal decay
    """
    new_valence = mood.valence
    new_arousal = mood.arousal

    # Homeostatic pull toward neutral
    new_valence += (0.0 - new_valence) * 0.02 * elapsed_hours
    new_arousal += (0.5 - new_arousal) * 0.02 * elapsed_hours

    # Social hunger → valence suppression
    if drives.social > 0.7:
        pressure = -0.02 * (drives.social - 0.7)
        new_valence = clamp(new_valence + pressure, -1.0, 1.0)

    # Event-driven changes
    for p in perceptions:
        if p.event_type == EventType.CONVERSATION:
            # Social contact lifts mood proportionally to loneliness
            new_valence = clamp(new_valence + 0.05 * drives.social, -1.0, 1.0)
            new_arousal = clamp(new_arousal + 0.05)

    # Expression frustration
    if drives.expression > 0.7:
        new_valence = clamp(new_valence - 0.01 * (drives.expression - 0.7), -1.0, 1.0)

    # Per-cycle valence delta clamp (prevents death spirals)
    max_delta = 0.10
    delta = new_valence - mood.valence
    if abs(delta) > max_delta:
        new_valence = mood.valence + (max_delta if delta > 0 else -max_delta)

    # Hard floor
    new_valence = max(new_valence, -0.85)

    # Determine mood word
    word = _valence_to_word(new_valence, new_arousal)

    return MoodState(
        valence=clamp(new_valence, -1.0, 1.0),
        arousal=clamp(new_arousal),
        word=word,
    )


def _valence_to_word(valence: float, arousal: float) -> str:
    """Map valence+arousal to a mood word."""
    if valence > 0.3:
        if arousal > 0.6:
            return "excited"
        return "content"
    elif valence < -0.3:
        if arousal > 0.6:
            return "anxious"
        return "melancholy"
    else:
        if arousal > 0.6:
            return "alert"
        if arousal < 0.3:
            return "drowsy"
        return "neutral"
