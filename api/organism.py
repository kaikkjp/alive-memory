"""Organism parameter computation for the consciousness canvas.

Maps internal drive/mood/energy state to visual parameters consumed by
the p5.js organism renderer on the Lounge frontend.

Pure function — no DB access, no side effects.
"""

import math


def compute_organism_params(drives: dict, mood_valence: float, mood_arousal: float,
                            energy: float, is_sleeping: bool, is_dreaming: bool,
                            is_thinking: bool) -> dict:
    """Compute visual organism parameters from internal state.

    Args:
        drives: Dict with keys 'curiosity', 'social_hunger', 'expression_need' (0-1 each).
        mood_valence: 0.0 (negative) to 1.0 (positive).
        mood_arousal: 0.0 (calm) to 1.0 (aroused).
        energy: 0.0 (depleted) to 1.0 (full).
        is_sleeping: Whether the agent is in sleep mode.
        is_dreaming: Whether the agent is actively dreaming (currently always False).
        is_thinking: Whether a cognitive cycle just ran.

    Returns:
        Dict of visual parameters for the consciousness canvas.
    """
    if is_sleeping:
        speed = math.pi / 120
    elif is_thinking:
        speed = math.pi / 40
    elif mood_arousal > 0.6:
        speed = math.pi / 35
    else:
        speed = math.pi / 45

    return {
        "evolution_speed": speed,
        "complexity": 8 - drives['curiosity'] * 4,
        "stroke_alpha": 40 + energy * 80,
        "color_temp": mood_valence,
        "bg_darkness": 0.92 - (mood_valence * 0.05),
        "amplitude": 0.7 + drives['social_hunger'] * 0.6,
        "phase_offsets": [drives['curiosity'], drives['social_hunger'], drives['expression_need']],
        "dream_flare": is_dreaming,
        "thinking_boost": is_thinking,
    }
