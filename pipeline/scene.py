"""Scene Layer System — deterministic state-to-layer mapping.

No LLM calls. Maps current drives/ambient/engagement to layer filenames.
The scene is assembled client-side from pre-generated PNG layers.
"""

import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone

from models.state import DrivesState, EngagementState

JST = timezone(timedelta(hours=9))


# ─── Dataclass ───

@dataclass
class SceneLayers:
    background: str           # bg_tokyo_rain_afternoon.png
    shop: str                 # shop_warm_day.png
    items: list[dict] = field(default_factory=list)  # [{sprite, x, y, width, height}]
    character: str = ''       # her_reading_calm_apronA.png
    character_position: dict = field(default_factory=dict)  # {x, y, width, height}
    foreground: list[str] = field(default_factory=list)
    weather: str = 'clear'
    scene_id: str = ''

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Constants ───

# Character anchor position in the shop layout (pixels in 1536×1024 canvas)
CHARACTER_ANCHOR = {'x': 280, 'y': 380, 'width': 200, 'height': 350}

# Valid posture × mood combinations (from spec §1.5)
VALID_COMBINATIONS = {
    'reading':          ['calm', 'curious', 'happy'],
    'writing':          ['calm', 'melancholy', 'curious'],
    'standing_window':  ['calm', 'melancholy', 'curious', 'tired'],
    'arranging':        ['calm', 'happy', 'curious'],
    'sitting':          ['calm', 'melancholy', 'curious', 'tired'],
    'talking':          ['calm', 'happy', 'curious'],
    'resting':          ['tired', 'calm'],
    'sleeping':         ['calm'],
}

# Activity → posture mapping
ACTIVITY_TO_POSTURE = {
    'consume':  'reading',
    'express':  'writing',
    'thread':   'sitting',
    'rest':     'resting',
    'sleep':    'sleeping',
    'news':     'standing_window',
    'idle':     'sitting',
}

# Shelf slot positions (pixel coordinates in 1536×1024 canvas)
# Exact values will be calibrated after shop images are generated
SHELF_SLOTS = {
    'shelf_top_1':    {'x': 120, 'y': 180, 'width': 80, 'height': 80},
    'shelf_top_2':    {'x': 220, 'y': 180, 'width': 80, 'height': 80},
    'shelf_top_3':    {'x': 320, 'y': 180, 'width': 80, 'height': 80},
    'shelf_top_4':    {'x': 420, 'y': 180, 'width': 80, 'height': 80},
    'shelf_mid_1':    {'x': 120, 'y': 300, 'width': 80, 'height': 80},
    'shelf_mid_2':    {'x': 220, 'y': 300, 'width': 80, 'height': 80},
    'shelf_mid_3':    {'x': 320, 'y': 300, 'width': 80, 'height': 80},
    'shelf_mid_4':    {'x': 420, 'y': 300, 'width': 80, 'height': 80},
    'shelf_low_1':    {'x': 120, 'y': 420, 'width': 80, 'height': 80},
    'shelf_low_2':    {'x': 220, 'y': 420, 'width': 80, 'height': 80},
    'shelf_low_3':    {'x': 320, 'y': 420, 'width': 80, 'height': 80},
    'shelf_low_4':    {'x': 420, 'y': 420, 'width': 80, 'height': 80},
    'counter_left':   {'x': 100, 'y': 520, 'width': 100, 'height': 80},
    'counter_center': {'x': 300, 'y': 520, 'width': 100, 'height': 80},
    'counter_right':  {'x': 500, 'y': 520, 'width': 100, 'height': 80},
    'window_sill':    {'x': 50,  'y': 350, 'width': 60, 'height': 60},
}


# ─── Time / Weather helpers ───

def get_time_of_day(dt: datetime) -> str:
    """Map datetime to time_of_day label. Uses JST."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    hour = dt.astimezone(JST).hour
    if 6 <= hour < 12:
        return 'morning'
    elif 12 <= hour < 17:
        return 'afternoon'
    elif 17 <= hour < 21:
        return 'evening'
    else:
        return 'night'


def get_shop_lighting(time_of_day: str, shop_status: str) -> str:
    """Deterministic lighting from time + shop status."""
    if shop_status == 'closed':
        return 'dark_sleep'
    return {
        'morning':   'warm_day',
        'afternoon': 'warm_day',
        'evening':   'soft_evening',
        'night':     'dim_night',
    }.get(time_of_day, 'warm_day')


# ─── Mood mapping ───

def _map_mood(valence: float, arousal: float, energy: float) -> str:
    """Map continuous drives to discrete mood label."""
    if energy < 0.2:
        return 'tired'
    if valence > 0.3 and arousal > 0.3:
        return 'happy'
    if valence < -0.2:
        return 'melancholy'
    if arousal > 0.4:
        return 'curious'
    return 'calm'


def _get_outfit(weather: str, energy: float) -> str:
    """Outfit selection. Simple for launch — always apronA."""
    # Future: she can choose outfits, store in DB
    return 'apronA'


# ─── Character sprite resolution ───

def get_character_sprite(
    activity: str,
    drives: DrivesState,
    engagement_status: str,
    weather: str,
) -> str:
    """Map current state to sprite filename. Deterministic."""

    # Posture from activity/engagement
    if engagement_status == 'engaged':
        posture = 'talking'
    elif activity == 'consume':
        posture = 'reading'
    elif activity == 'express':
        posture = 'writing'
    elif activity == 'thread':
        posture = 'sitting'
    elif activity == 'rest':
        posture = 'resting'
    elif activity == 'sleep':
        posture = 'sleeping'
    elif activity == 'news' and random.random() < 0.5:
        posture = 'standing_window'
    else:
        posture = random.choices(
            ['standing_window', 'sitting', 'arranging'],
            weights=[0.4, 0.4, 0.2],
        )[0]

    # Mood from drives
    mood = _map_mood(drives.mood_valence, drives.mood_arousal, drives.energy)

    # Validate combination, fallback to 'calm' if invalid
    valid_moods = VALID_COMBINATIONS.get(posture, ['calm'])
    if mood not in valid_moods:
        mood = 'calm'

    # Outfit
    outfit = _get_outfit(weather, drives.energy)

    return f'her_{posture}_{mood}_{outfit}.png'


# ─── Main builder ───

async def build_scene_layers(
    drives: DrivesState,
    ambient: dict | None,
    focus: object | None,  # routing.focus or None
    engagement: EngagementState,
    clock_now: datetime,
    shelf_items: list[dict] | None = None,
    shop_status: str = 'open',
) -> SceneLayers:
    """Build layer specification from current state. No LLM, no generation.

    Args:
        drives: Current drives state
        ambient: Dict with weather info {'condition': 'rain', ...} or None
        focus: Current focus object (has .channel attribute) or None
        engagement: Current engagement state
        clock_now: Current datetime
        shelf_items: Pre-fetched shelf assignments or None (caller should provide)
        shop_status: 'open' | 'closed' | 'resting'
    """
    time_of_day = get_time_of_day(clock_now)
    weather = 'clear'
    if ambient and isinstance(ambient, dict):
        weather = ambient.get('condition', 'clear')

    # Layer 0: Background
    background = f'bg_tokyo_{weather}_{time_of_day}.png'

    # Layer 1: Shop interior
    lighting = get_shop_lighting(time_of_day, shop_status)
    shop = f'shop_{lighting}.png'

    # Layer 2: Items
    items = []
    if shelf_items:
        for item in shelf_items:
            slot_info = SHELF_SLOTS.get(item.get('slot_id', ''))
            if slot_info and item.get('sprite_filename'):
                items.append({
                    'sprite': item['sprite_filename'],
                    'x': slot_info['x'],
                    'y': slot_info['y'],
                    'width': slot_info['width'],
                    'height': slot_info['height'],
                })

    # Layer 3: Character
    activity = 'idle'
    if focus and hasattr(focus, 'channel'):
        activity = focus.channel or 'idle'
    elif focus and hasattr(focus, 'p_type'):
        activity = focus.p_type or 'idle'

    character = get_character_sprite(activity, drives, engagement.status, weather)

    # Layer 4: Foreground
    foreground = ['fg_counter_top.png']
    if time_of_day in ('evening', 'night'):
        foreground.append('fg_lantern_glow.png')

    return SceneLayers(
        background=background,
        shop=shop,
        items=items,
        character=character,
        character_position=CHARACTER_ANCHOR.copy(),
        foreground=foreground,
        weather=weather,
        scene_id=f'scene_{clock_now.strftime("%Y%m%d_%H%M%S")}',
    )
