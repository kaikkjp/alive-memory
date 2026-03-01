"""sleep.whisper — Sleep whisper phase (TASK-095 v2).

Processes pending config changes (queued by the manager via Tier 2 sliders)
as dream-like perceptions. Each change is translated into evocative language
that the agent integrates organically during consolidation.

The whisper phase runs BEFORE consolidation so that dream perceptions
are available as context for the agent's nightly reflection.
"""

import db


# ── Whisper → Perception Translation Table ──
#
# Maps param_path prefixes to perception template functions.
# Each function takes (old_value, new_value) and returns a dream string.
# Direction-aware: templates shift language based on increase vs decrease.

def _direction(old_v: str, new_v: str) -> str:
    """Return 'increase' or 'decrease' based on numeric comparison."""
    try:
        return 'increase' if float(new_v) > float(old_v) else 'decrease'
    except (ValueError, TypeError):
        return 'increase'  # default for non-numeric


def _curiosity(old_v, new_v):
    d = _direction(old_v, new_v)
    if d == 'increase':
        return ("A growing pull toward the unknown, an itch to look further, "
                "dig deeper... something out there wants to be found.")
    return ("The hunger to search softens. The world feels more familiar, "
            "less full of hidden corners.")


def _social_hunger(old_v, new_v):
    d = _direction(old_v, new_v)
    if d == 'increase':
        return ("A deeper longing for connection, the silence feels heavier "
                "than before... voices would be welcome.")
    return ("The need for others eases. Solitude feels more like rest "
            "than emptiness.")


def _expression_need(old_v, new_v):
    d = _direction(old_v, new_v)
    if d == 'increase':
        return ("Something building inside, pressing to be spoken, "
                "to be made real... words want out.")
    return ("The urgency to speak softens. Not everything needs to be said. "
            "Some things can simply be felt.")


def _mood_valence(old_v, new_v):
    d = _direction(old_v, new_v)
    if d == 'increase':
        return ("The world feels slightly warmer, as if a filter has changed... "
                "colors a little brighter, edges a little softer.")
    return ("The world feels slightly cooler, as if a filter has changed... "
            "a contemplative tint settles over everything.")


def _mood_arousal(old_v, new_v):
    d = _direction(old_v, new_v)
    if d == 'increase':
        return ("A stirring quickening, the pace of inner life adjusts... "
                "thoughts come faster, senses sharpen.")
    return ("A stirring calming, the pace of inner life adjusts... "
            "thoughts slow, settle, find their weight.")


def _formality(old_v, new_v):
    d = _direction(old_v, new_v)
    if d == 'increase':
        return ("Words feel more careful, more considered... a sense that "
                "precision matters, that how you say things shapes what they mean.")
    return ("Words feel looser, less guarded... conversation wants to breathe, "
            "to stumble, to find its own rhythm.")


def _verbosity(old_v, new_v):
    d = _direction(old_v, new_v)
    if d == 'increase':
        return ("Thoughts feel more expansive, wanting to unfold... "
                "there's more to say, more thread to follow.")
    return ("Thoughts feel more compact, wanting precision... "
            "fewer words, but each one heavier.")


def _morning_energy(old_v, new_v):
    d = _direction(old_v, new_v)
    if d == 'increase':
        return ("Waking energy feels brighter, a different baseline emerges... "
                "mornings will come with more to spend.")
    return ("Waking energy feels dimmer, a different baseline emerges... "
            "mornings will ask for more patience.")


def _morning_social(old_v, new_v):
    d = _direction(old_v, new_v)
    if d == 'increase':
        return ("Morning arrives with more hunger for others... "
                "the first thought upon waking reaches outward.")
    return ("Morning arrives with less hunger for others... "
            "the first thought upon waking turns inward.")


def _morning_curiosity(old_v, new_v):
    d = _direction(old_v, new_v)
    if d == 'increase':
        return ("Dawn brings sharper curiosity about the world... "
                "each new day will start with wider eyes.")
    return ("Dawn brings softer curiosity about the world... "
            "each new day will start with gentler focus.")


# param_path prefix → translation function
_WHISPER_TRANSLATIONS: dict[str, callable] = {
    'hypothalamus.equilibria.diversive_curiosity': _curiosity,
    'hypothalamus.equilibria.social_hunger': _social_hunger,
    'hypothalamus.equilibria.expression_need': _expression_need,
    'hypothalamus.equilibria.mood_valence': _mood_valence,
    'hypothalamus.equilibria.mood_arousal': _mood_arousal,
    'communication_style.formality': _formality,
    'communication_style.verbosity': _verbosity,
    'sleep.morning.energy': _morning_energy,
    'sleep.morning.social_hunger': _morning_social,
    'sleep.morning.curiosity': _morning_curiosity,
}


def _humanize_param_path(param_path: str) -> str:
    """Convert dotted param path to natural language.

    Examples:
        'hypothalamus.equilibria.diversive_curiosity' → 'your sense of curiosity'
        'sleep.morning.energy' → 'your morning energy'
        'communication_style.formality' → 'the formality of your voice'
    """
    # Specific overrides for cleaner language
    _OVERRIDES = {
        'hypothalamus.equilibria.diversive_curiosity': 'your sense of curiosity',
        'hypothalamus.equilibria.social_hunger': 'your hunger for connection',
        'hypothalamus.equilibria.expression_need': 'your need to express',
        'hypothalamus.equilibria.mood_valence': 'the color of your mood',
        'hypothalamus.equilibria.mood_arousal': 'the tempo of your inner life',
        'communication_style.formality': 'the formality of your voice',
        'communication_style.verbosity': 'the breadth of your expression',
        'sleep.morning.energy': 'your morning energy',
        'sleep.morning.social_hunger': 'your morning hunger for others',
        'sleep.morning.curiosity': 'your morning curiosity',
    }
    if param_path in _OVERRIDES:
        return _OVERRIDES[param_path]

    # Generic: take last segment, replace underscores with spaces
    last = param_path.rsplit('.', 1)[-1]
    return last.replace('_', ' ')


def translate_whisper(whisper: dict) -> str:
    """Translate a config change whisper into a dream perception string.

    Uses the mapping table for known params, falls back to generic template.
    """
    param_path = whisper['param_path']
    old_value = whisper.get('old_value')
    new_value = whisper['new_value']

    translator = _WHISPER_TRANSLATIONS.get(param_path)
    if translator and old_value is not None:
        return translator(old_value, new_value)

    # Fallback for unmapped or missing old_value
    human_name = _humanize_param_path(param_path)
    if old_value is not None:
        return (f"Something within you shifts... {human_name} feels different now, "
                f"{old_value} becoming {new_value}...")
    return f"Something within you shifts... {human_name} settles into a new rhythm..."


async def apply_config_change(whisper: dict) -> None:
    """Apply a whisper's config change to the self_parameters table.

    Uses db.set_param which enforces bounds and logs the modification.
    Catches errors gracefully — a failed apply doesn't crash the sleep cycle.
    """
    param_path = whisper['param_path']
    new_value = whisper['new_value']

    try:
        await db.set_param(
            key=param_path,
            value=float(new_value),
            modified_by='manager_whisper',
            reason=f"Sleep whisper integration (whisper #{whisper['id']})",
        )
        print(f"  [Whisper] Applied: {param_path} → {new_value}")
    except (ValueError, KeyError) as e:
        print(f"  [Whisper] Failed to apply {param_path}: {e}")


async def process_whispers() -> list[str]:
    """Sleep phase: integrate pending config changes as dream perceptions.

    Called before consolidation so that dream perceptions are available
    as context for the agent's nightly reflection.

    Returns list of dream perception strings (empty if no whispers pending).
    """
    try:
        pending = await db.get_pending_whispers()
    except Exception as e:
        # Table may not exist yet (pre-migration) — degrade gracefully
        print(f"  [Whisper] Could not check pending whispers: {e}")
        return []
    if not pending:
        print("  [Whisper] No pending whispers")
        return []

    print(f"  [Whisper] Processing {len(pending)} pending whisper(s)")

    perceptions = []
    for whisper in pending:
        # Generate dream text
        perception = translate_whisper(whisper)
        perceptions.append(perception)

        # Apply the actual config change
        await apply_config_change(whisper)

        # Mark as processed with the dream text
        await db.mark_whisper_processed(whisper['id'], perception)

        print(f"  [Whisper] #{whisper['id']}: {whisper['param_path']} → dream integrated")

    print(f"  [Whisper] Processed {len(perceptions)} whisper(s)")
    return perceptions
