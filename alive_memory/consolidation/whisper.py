"""Whisper — config changes translated into dream perceptions."""

from __future__ import annotations

import logging

from alive_memory.storage.base import BaseStorage

logger = logging.getLogger(__name__)

_TRANSLATION_TABLE: list[tuple[str, str, str]] = [
    ("curiosity",
     "Something in you stirs — an urge to look around corners, to wonder.",
     "The restless scanning fades. You feel settled, less hungry for novelty."),
    ("social",
     "You notice the silence more. Company would be welcome.",
     "The need for others softens. Solitude feels comfortable."),
    ("expression",
     "Words are building up inside. You want to say something, write something.",
     "The pressure to express eases. Quiet feels natural."),
    ("valence",
     "A warmth seeps in, subtle. Things feel a little brighter.",
     "A weight settles. The world dims, just slightly."),
    ("arousal",
     "Your awareness sharpens. Senses open wider.",
     "Everything softens. A drowsiness, not unpleasant."),
    ("energy",
     "You feel more capable today. There's fuel in the tank.",
     "Tiredness pulls at you. Best to be selective with effort."),
]


def translate_whisper(param_path: str, old_value: float, new_value: float) -> str:
    """Translate a parameter change into a dream perception string."""
    direction = "increase" if new_value > old_value else "decrease"
    for pattern, inc, dec in _TRANSLATION_TABLE:
        if pattern in param_path.lower():
            return inc if direction == "increase" else dec

    human = param_path.replace("_", " ").replace(".", " ")
    if direction == "increase":
        return f"Something shifts — your sense of {human} grows stronger."
    return f"Something shifts — your sense of {human} fades slightly."


async def process_whispers(
    whispers: list[dict],
    storage: BaseStorage,
) -> list[str]:
    """Process config change whispers into dream perceptions."""
    dreams: list[str] = []
    for w in whispers:
        param = w.get("param_path", "")
        old = float(w.get("old_value", 0))
        new = float(w.get("new_value", 0))
        dream_text = translate_whisper(param, old, new)
        dreams.append(dream_text)
        try:
            await storage.set_parameter(param, new, reason=f"whisper: {dream_text[:50]}")
        except Exception:
            logger.warning("Failed to set parameter %s via whisper", param, exc_info=True)
    return dreams
