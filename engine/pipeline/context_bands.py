"""Shared trigger context computation for habit system.

Converts continuous drive values and engagement state into coarse-grained
bands suitable for habit matching. Shared by output.py (tracking, 011a)
and basal_ganglia.py (auto-fire, 011b).
"""

import clock
from models.pipeline import TriggerContext
from models.state import DrivesState, EngagementState


def compute_trigger_context(drives: DrivesState,
                            engagement: EngagementState) -> TriggerContext:
    """Build a TriggerContext from current drives and engagement state.

    Bands are deliberately coarse so habits generalize across
    similar situations rather than being hyper-specific.
    """
    # Energy: low < 0.33, mid 0.33-0.66, high > 0.66
    if drives.energy < 0.33:
        energy_band = 'low'
    elif drives.energy > 0.66:
        energy_band = 'high'
    else:
        energy_band = 'mid'

    # Mood: negative < -0.3, neutral -0.3 to 0.3, positive > 0.3
    if drives.mood_valence < -0.3:
        mood_band = 'negative'
    elif drives.mood_valence > 0.3:
        mood_band = 'positive'
    else:
        mood_band = 'neutral'

    # Mode: derived from engagement status
    if engagement.status == 'engaged':
        mode = 'engaged'
    else:
        mode = 'idle'

    # Time band: JST hour
    hour = clock.now().hour
    if 6 <= hour < 12:
        time_band = 'morning'
    elif 12 <= hour < 17:
        time_band = 'afternoon'
    elif 17 <= hour < 21:
        time_band = 'evening'
    else:
        time_band = 'night'

    visitor_present = engagement.status == 'engaged'

    return TriggerContext(
        energy_band=energy_band,
        mood_band=mood_band,
        mode=mode,
        time_band=time_band,
        visitor_present=visitor_present,
    )
