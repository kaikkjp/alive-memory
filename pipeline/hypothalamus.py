"""Hypothalamus — drives math. Deterministic. No LLM."""

from models.event import Event
from models.state import DrivesState
import db as _db


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


async def update_drives(
    drives: DrivesState,
    elapsed_hours: float,
    events: list[Event],
    cortex_flags: dict = None,
) -> tuple[DrivesState, str]:
    """Update drives based on time passage and events. Returns new drives + feelings text."""

    new = drives.copy()

    # Time-based decay/buildup
    new.social_hunger = clamp(new.social_hunger + 0.05 * elapsed_hours)
    new.curiosity = clamp(new.curiosity + 0.03 * elapsed_hours)
    new.expression_need = clamp(new.expression_need + 0.04 * elapsed_hours)
    new.energy = clamp(new.energy - 0.02 * elapsed_hours)

    # Rest need builds with time — she gets tired just from being awake
    # Faster when engaged (+0.06/hr), slower when idle (+0.03/hr)
    has_visitor_events = any(
        e.event_type in ('visitor_speech', 'visitor_connect')
        for e in events
    )
    if has_visitor_events:
        new.rest_need = clamp(new.rest_need + 0.06 * elapsed_hours)
    else:
        new.rest_need = clamp(new.rest_need + 0.03 * elapsed_hours)

    # Event-based changes
    for event in events:
        if event.event_type == 'visitor_speech':
            new.social_hunger = clamp(new.social_hunger - 0.08)
            new.energy = clamp(new.energy - 0.03)
            new.rest_need = clamp(new.rest_need + 0.04)  # each interaction tires her

        if event.event_type == 'action_speak':
            new.expression_need = clamp(new.expression_need - 0.05)

        if event.event_type == 'visitor_connect':
            new.mood_arousal = clamp(new.mood_arousal + 0.1)

        if event.event_type == 'visitor_disconnect':
            new.mood_arousal = clamp(new.mood_arousal - 0.05)
            new.social_hunger = clamp(new.social_hunger + 0.03)

    # Cortex resonance flags (from previous cycle)
    if cortex_flags and cortex_flags.get('resonance'):
        new.social_hunger = clamp(new.social_hunger - 0.15)  # bonus
        new.energy = clamp(new.energy + 0.05)                 # energy boost
        new.mood_valence = clamp(new.mood_valence + 0.1, -1.0, 1.0)

    # Rest recovery only during rest cycles (no events and enough elapsed time)
    if not events and elapsed_hours > 0.5:
        new.rest_need = clamp(new.rest_need - 0.1 * elapsed_hours)
        new.energy = clamp(new.energy + 0.08 * elapsed_hours)

    # Generate feelings text
    feelings = drives_to_feeling(new)

    return new, feelings


def drives_to_feeling(d: DrivesState) -> str:
    """Translate numeric drives into diegetic feeling text for Cortex."""

    parts = []

    # Social
    if d.social_hunger > 0.8:
        parts.append("I feel deeply lonely. The shop has been too quiet.")
    elif d.social_hunger > 0.6:
        parts.append("I could use some company.")
    elif d.social_hunger < 0.2:
        parts.append("I've had enough interaction for now. I need some quiet.")

    # Energy
    if d.energy < 0.3:
        parts.append("I'm tired. Everything feels heavy today.")
    elif d.energy > 0.8:
        parts.append("I feel sharp and present.")

    # Curiosity
    if d.curiosity > 0.7:
        parts.append("I'm restless. I want to find something new.")

    # Expression
    if d.expression_need > 0.7:
        parts.append("There's something building inside me that wants to come out. I should write, or post, or rearrange something.")

    # Mood
    if d.mood_valence < -0.5:
        parts.append("Everything feels dim right now.")
    elif d.mood_valence > 0.5:
        parts.append("There's a warmth in me. Something happened that I'm still carrying.")

    if not parts:
        parts.append("I feel steady. Present. Nothing pulling me in any particular direction.")

    return " ".join(parts)


# ─── Immediate Drive Relief ───
# Called directly by executor after HER OWN actions complete.
# Bypasses inbox/event loop — drive relief is immediate, not queued.

EXPRESSION_RELIEF = {
    'action_speak':    {'expression_need': -0.05, 'social_hunger': -0.03},
    'write_journal':   {'expression_need': -0.12, 'rest_need': 0.02},
    'post_x_draft':    {'expression_need': -0.10, 'rest_need': 0.02},
    'rearrange':       {'expression_need': -0.06},
}


async def apply_expression_relief(action_type: str):
    """Immediate drive update after her own action. No event loop. No inbox."""
    relief = EXPRESSION_RELIEF.get(action_type)
    if not relief:
        return

    drives = await _db.get_drives_state()
    for field, delta in relief.items():
        current = getattr(drives, field)
        setattr(drives, field, clamp(current + delta))
    await _db.save_drives_state(drives)
