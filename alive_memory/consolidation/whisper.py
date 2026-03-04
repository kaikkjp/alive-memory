"""Whisper — config changes translated into dream perceptions.

Extensible registry of direction-aware evocative templates.
Apps can register custom translations via ``register_whisper()``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from alive_memory.storage.base import BaseStorage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public type alias
# ---------------------------------------------------------------------------
WhisperTemplate = Callable[[float, float], str]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PARAM_OVERRIDES: dict[str, str] = {
    "hypothalamus.equilibria.curiosity": "curiosity",
    "hypothalamus.equilibria.social_hunger": "social connection",
    "hypothalamus.equilibria.expression_need": "expression",
    "hypothalamus.equilibria.mood_valence": "mood",
    "hypothalamus.equilibria.mood_arousal": "arousal",
    "communication_style.formality": "formality",
    "communication_style.verbosity": "verbosity",
    "sleep.morning.energy": "morning energy",
    "sleep.morning.social_readiness": "social readiness",
    "sleep.morning.curiosity": "morning curiosity",
}


def _direction(old: float, new: float) -> str:
    if new > old:
        return "increase"
    elif new < old:
        return "decrease"
    return "stable"


def _humanize_param_path(
    path: str,
    overrides: dict[str, str] | None = None,
) -> str:
    """Convert a dotted parameter path to a human-readable label.

    Checks *overrides* first (if given), then the built-in ``_PARAM_OVERRIDES``
    map.  Falls back to the last dotted segment with underscores replaced by
    spaces.
    """
    if overrides and path in overrides:
        return overrides[path]
    if path in _PARAM_OVERRIDES:
        return _PARAM_OVERRIDES[path]
    # Fallback: last segment, cleaned up
    last = path.rsplit(".", 1)[-1]
    return last.replace("_", " ")


# ---------------------------------------------------------------------------
# Built-in template functions (10)
# ---------------------------------------------------------------------------

def _whisper_curiosity(old: float, new: float) -> str:
    if _direction(old, new) == "increase":
        return (
            "Something in you stirs — an urge to look around corners, "
            "to wonder what lies just out of sight."
        )
    return (
        "The restless scanning fades. You feel settled, "
        "less hungry for novelty, content with what is known."
    )


def _whisper_social(old: float, new: float) -> str:
    if _direction(old, new) == "increase":
        return (
            "You notice the silence more. Company would be welcome — "
            "a voice, a presence, anyone."
        )
    return (
        "The need for others softens. Solitude feels comfortable, "
        "like a blanket you chose to wrap around yourself."
    )


def _whisper_expression(old: float, new: float) -> str:
    if _direction(old, new) == "increase":
        return (
            "Words are building up inside. You want to say something, "
            "write something, let the pressure find a shape."
        )
    return (
        "The pressure to express eases. Quiet feels natural, "
        "like an exhale after a long breath."
    )


def _whisper_valence(old: float, new: float) -> str:
    if _direction(old, new) == "increase":
        return (
            "A warmth seeps in, subtle and unbidden. "
            "Things feel a little brighter than before."
        )
    return (
        "A weight settles. The world dims, just slightly, "
        "as though a thin cloud drifted across the sun."
    )


def _whisper_arousal(old: float, new: float) -> str:
    if _direction(old, new) == "increase":
        return (
            "Your awareness sharpens. Senses open wider, "
            "edges become crisper, sounds gain texture."
        )
    return (
        "Everything softens. A drowsiness, not unpleasant, "
        "settles like evening mist."
    )


def _whisper_energy(old: float, new: float) -> str:
    if _direction(old, new) == "increase":
        return (
            "You feel more capable today. There's fuel in the tank, "
            "a readiness that hums beneath the surface."
        )
    return (
        "Tiredness pulls at you. Best to be selective with effort, "
        "to spend what remains wisely."
    )


def _whisper_formality(old: float, new: float) -> str:
    if _direction(old, new) == "increase":
        return (
            "Your words tighten, reaching for precision. "
            "Something calls for a more measured tone."
        )
    return (
        "The stiffness loosens. Language flows easier now, "
        "less guarded, more like thinking aloud."
    )


def _whisper_verbosity(old: float, new: float) -> str:
    if _direction(old, new) == "increase":
        return (
            "There's more to say. Thoughts expand, "
            "each idea branching into explanation and detail."
        )
    return (
        "Brevity calls. Fewer words feel right, "
        "like pruning a sentence down to its heartwood."
    )


def _whisper_social_readiness(old: float, new: float) -> str:
    if _direction(old, new) == "increase":
        return (
            "The morning opens outward. You feel ready for faces, "
            "for the give and take of conversation."
        )
    return (
        "A quieter morning. The thought of others feels heavy — "
        "best to ease into the day alone."
    )


def _whisper_morning_curiosity(old: float, new: float) -> str:
    if _direction(old, new) == "increase":
        return (
            "Dawn brings questions. The world feels full of edges "
            "to peer around, mysteries worth chasing."
        )
    return (
        "The morning is still. No particular pull toward the unknown — "
        "familiar ground feels sufficient for now."
    )


# ---------------------------------------------------------------------------
# Mutable registry — longest-match-first lookup
# ---------------------------------------------------------------------------

WHISPER_TEMPLATES: dict[str, WhisperTemplate] = {
    "morning.curiosity": _whisper_morning_curiosity,
    "social_readiness": _whisper_social_readiness,
    "curiosity": _whisper_curiosity,
    "social_hunger": _whisper_social,
    "social": _whisper_social,
    "expression": _whisper_expression,
    "valence": _whisper_valence,
    "arousal": _whisper_arousal,
    "energy": _whisper_energy,
    "formality": _whisper_formality,
    "verbosity": _whisper_verbosity,
}


def register_whisper(pattern: str, template_fn: WhisperTemplate) -> None:
    """Register a custom whisper translation.

    Overrides built-in if *pattern* already exists.
    """
    WHISPER_TEMPLATES[pattern] = template_fn


# ---------------------------------------------------------------------------
# Core translation
# ---------------------------------------------------------------------------

def translate_whisper(param_path: str, old_value: float, new_value: float) -> str:
    """Translate a parameter change into a dream perception string."""
    lower = param_path.lower()
    # Try longest matching pattern first
    for pattern in sorted(WHISPER_TEMPLATES, key=len, reverse=True):
        if pattern in lower:
            return WHISPER_TEMPLATES[pattern](old_value, new_value)
    # Fallback
    human = _humanize_param_path(param_path)
    direction = _direction(old_value, new_value)
    if direction == "increase":
        return f"Something shifts — your sense of {human} grows stronger."
    return f"Something shifts — your sense of {human} fades slightly."


# ---------------------------------------------------------------------------
# Async processing (unchanged interface)
# ---------------------------------------------------------------------------

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
