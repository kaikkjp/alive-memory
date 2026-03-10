"""Memory translator — numbers to feelings.

Converts drive values, mood states, and energy levels into natural language
suitable for conscious memory (markdown files).  No raw numbers, no
percentages, no drive names leak into the agent's memories.

Ported from Shopkeeper engine/memory/translator.py, adapted for SDK types.

Usage:
    from alive_memory.hot.translator import translate_mood, scrub_numbers

    sentence = translate_mood(0.7, 0.8)   # "I felt alive and buzzing with energy."
    clean = scrub_numbers("valence=0.84")  # ""
"""

from __future__ import annotations

import re

from alive_memory.types import DriveState, MoodState


# ── Single-word helpers ──────────────────────────────────────────────

def mood_word(valence: float, arousal: float) -> str:
    """Convert valence/arousal to a natural mood word."""
    if valence > 0.5 and arousal > 0.5:
        return "energized"
    if valence > 0.5 and arousal <= 0.5:
        return "content"
    if valence > 0.2 and arousal > 0.5:
        return "curious"
    if valence > 0.2:
        return "calm"
    if valence > -0.2 and arousal > 0.5:
        return "restless"
    if valence > -0.2:
        return "neutral"
    if valence > -0.5 and arousal > 0.5:
        return "agitated"
    if valence > -0.5:
        return "subdued"
    if arousal > 0.5:
        return "distressed"
    return "low"


def drive_level(value: float) -> str:
    """Convert a 0-1 drive value to a natural word."""
    if value > 0.8:
        return "high"
    if value > 0.6:
        return "moderate"
    if value > 0.3:
        return "low"
    return "quiet"


def energy_word(ratio: float) -> str:
    """Convert remaining budget ratio to an energy word."""
    if ratio > 0.8:
        return "full"
    if ratio > 0.6:
        return "good"
    if ratio > 0.35:
        return "moderate"
    if ratio > 0.15:
        return "low"
    return "depleted"


# ── Richer sentence generators (for MD memory files) ─────────────────

_MOOD_SENTENCES = {
    "energized": "I felt alive and buzzing with energy.",
    "content": "A quiet contentment settled in.",
    "curious": "Something caught my attention \u2014 I wanted to know more.",
    "calm": "Everything felt still and unhurried.",
    "restless": "I felt restless, like I needed something to change.",
    "neutral": "I felt even. Neither pulled toward anything nor pushed away.",
    "agitated": "Something was gnawing at me. I couldn't quite settle.",
    "subdued": "A heaviness hung over me, muted and low.",
    "distressed": "Something felt wrong. I couldn't shake the unease.",
    "low": "Everything felt far away and dulled.",
}

# SDK drive names mapped to engine-style sentence templates.
# SDK DriveState fields: curiosity, social, expression, rest
_DRIVE_SENTENCES = {
    "social": {
        "high": "I longed for someone to talk to.",
        "moderate": "I wouldn't mind some company.",
        "low": "I was fine on my own for now.",
        "quiet": "Solitude felt right.",
    },
    "curiosity": {
        "high": "My mind was restless, reaching for something new.",
        "moderate": "A mild itch of curiosity.",
        "low": "My thoughts were calm, not searching.",
        "quiet": "My mind was still.",
    },
    "expression": {
        "high": "Words were building up inside me, needing out.",
        "moderate": "I had things I could say, if asked.",
        "low": "I was content to listen.",
        "quiet": "Nothing pressing to express.",
    },
}

_ENERGY_SENTENCES = {
    "full": "I felt sharp and ready.",
    "good": "Plenty of energy to go around.",
    "moderate": "Getting a bit worn, but managing.",
    "low": "Running thin. Need to be careful.",
    "depleted": "I was running on fumes.",
}


def translate_mood(valence: float, arousal: float) -> str:
    """Convert valence/arousal to a natural felt sentence."""
    word = mood_word(valence, arousal)
    return _MOOD_SENTENCES.get(word, f"I felt {word}.")


def translate_drive(name: str, value: float) -> str:
    """Convert a drive name + value to a felt statement."""
    level = drive_level(value)
    sentences = _DRIVE_SENTENCES.get(name, {})
    return sentences.get(level, "")


def translate_energy(value: float) -> str:
    """Convert energy ratio to a felt sentence."""
    word = energy_word(value)
    return _ENERGY_SENTENCES.get(word, "")


def translate_drives_summary(
    drives: DriveState,
    mood: MoodState,
    *,
    energy: float = 0.5,
) -> str:
    """Convert drive + mood state to a paragraph of felt experience.

    Args:
        drives: Current drive levels.
        mood: Current mood state.
        energy: Energy ratio (0-1), e.g. from CognitiveState.energy.

    Returns:
        Natural language paragraph. NO numbers.
    """
    parts: list[str] = []

    mood_sent = translate_mood(mood.valence, mood.arousal)
    if mood_sent:
        parts.append(mood_sent)

    # Only mention drives that are notably high or low
    for drive_name in ("social", "curiosity", "expression"):
        val = getattr(drives, drive_name, 0.5)
        if val > 0.6 or val < 0.3:
            sent = translate_drive(drive_name, val)
            if sent:
                parts.append(sent)

    energy_sent = translate_energy(energy)
    if energy_sent:
        parts.append(energy_sent)

    return " ".join(parts) if parts else "I felt even."


def translate_internal_conflict(conflicts: list[str]) -> str:
    """Convert metacognitive conflict descriptions to felt experience.

    Args:
        conflicts: Raw conflict strings from a metacognitive monitor,
                   e.g. ["Used exclamation mark without being surprised"]

    Returns:
        A natural first-person observation, or empty string if no conflicts.
    """
    if not conflicts:
        return ""

    conflict_map = [
        (r"exclamation", "I caught myself being louder than I meant to be"),
        (r"question.mark", "I noticed I was asking something I wasn't really curious about"),
        (r"ellipsis|\.\.\.", "My thoughts trailed off in a way that felt rehearsed"),
        (r"emoji", "I used a gesture that didn't feel like mine"),
        (r"apolog", "I apologized when I didn't need to"),
        (r"offer.help|assist", "I slipped into being helpful instead of being myself"),
        (r"certainty|definitely|absolutely", "I spoke with more certainty than I felt"),
    ]

    felt_parts: list[str] = []
    for conflict in conflicts[:3]:  # cap at 3
        matched = False
        for pattern, felt in conflict_map:
            if re.search(pattern, conflict, re.IGNORECASE):
                felt_parts.append(felt)
                matched = True
                break
        if not matched:
            felt_parts.append("Something about what I just did felt off")

    if len(felt_parts) == 1:
        return f"Something felt off \u2014 {felt_parts[0].lower()}."
    joined = "; ".join(p.lower() for p in felt_parts)
    return f"A few things felt off \u2014 {joined}."


# ── Safety net ───────────────────────────────────────────────────────

# Patterns that indicate machine-readable state leaked into conscious text.
# Dates (2026-02-19) and times (14:32) are intentionally preserved.
_SCRUB_PATTERNS = [
    # Floats like 0.84, 3.14 (but NOT inside dates like 2026-02-19)
    (r"(?<!\d{4}-\d{2}-)(?<!\d{2}-)\b\d+\.\d+\b", ""),
    # Percentages like 84%
    (r"\b\d+%", ""),
    # Pipeline variable names followed by numbers
    (
        r"\b(arousal|valence|salience|energy|hunger|curiosity|expression_need)"
        r"\s*[:=]?\s*\d[\d.]*",
        "",
    ),
    # Bare integers that look like scores (preceded by "score")
    (r"\bscore\s*[:=]?\s*\d+", ""),
]


def scrub_numbers(text: str) -> str:
    """Strip stray numbers/percentages from text meant for conscious memory.

    Safety net called before writing to MD files.
    Preserves dates (2026-02-19) and times (14:32).
    """
    if not text:
        return text
    result = text
    for pattern, replacement in _SCRUB_PATTERNS:
        result = re.sub(pattern, replacement, result)
    # Clean up double spaces left by removals
    result = re.sub(r"  +", " ", result)
    # Clean up leading/trailing whitespace on lines
    lines = [line.rstrip() for line in result.split("\n")]
    return "\n".join(lines)
