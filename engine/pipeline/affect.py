"""Affect Lens — subjective coloring based on drives. No LLM."""

import random
from datetime import datetime, timezone
import clock
from models.state import DrivesState
from pipeline.sensorium import Perception


def apply_affect_lens(perceptions: list[Perception], drives: DrivesState) -> list[Perception]:
    """Color perceptions with her current emotional state."""

    dilation = time_dilation(drives)

    colored = []
    for p in perceptions:
        # Add subjective time
        wait_seconds = (clock.now_utc() - p.ts).total_seconds()
        p.content = inject_time_feeling(p.content, wait_seconds, dilation, drives)

        # Mood colors interpretation
        if drives.mood_valence < -0.3:
            # Dark mood — things feel heavier
            p.salience = min(1.0, p.salience + 0.1)

        colored.append(p)
    return colored


def time_dilation(drives: DrivesState) -> float:
    d = 1.0
    d *= 1.0 + 0.6 * max(0.0, drives.social_hunger - 0.6)   # lonely → time drags
    d *= 1.0 - 0.5 * max(0.0, drives.curiosity - 0.6)        # curious → time flies
    return max(0.7, min(1.3, d + random.uniform(-0.08, 0.08)))


def inject_time_feeling(content: str, wait_s: float, dilation: float,
                        drives: DrivesState) -> str:
    """Add subjective time context without exposing real numbers."""
    effective = wait_s * dilation

    if effective < 5:
        return content  # just happened, no time note
    elif effective < 60:
        return content  # recent, no comment
    elif effective < 300:
        return f"(they've been here a moment) {content}"
    elif effective < 900:
        return f"(they've been waiting a while) {content}"
    else:
        return f"(they've been waiting a long time) {content}"
