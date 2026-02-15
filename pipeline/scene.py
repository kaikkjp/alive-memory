"""Scene Layer System — deterministic state-to-layer mapping.

No LLM calls. Maps current drives/ambient/engagement to layer filenames.
The scene is assembled client-side from pre-generated PNG layers.
"""

import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone

import clock
from models.state import DrivesState, EngagementState, RoomState

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


# ─── Sprite state resolution (for scene compositor) ───

# Valid sprite states for the scene compositor layer system
SPRITE_STATES = ('surprised', 'tired', 'engaged', 'curious', 'focused', 'thinking')

# Cycle types that indicate focused work
_FOCUSED_CYCLE_TYPES = {'thread_work', 'arranging', 'creative', 'consume', 'express'}


def resolve_sprite_state(
    drives: DrivesState,
    engagement: EngagementState,
    room_state: RoomState,
    recent_events: list[dict],
) -> str:
    """Resolve the current sprite state from live pipeline state.

    Priority order (highest first):
      surprised  — unexpected event in last 2 cycles
      tired      — energy < 30%
      engaged    — has_visitor AND in conversation
      curious    — has_visitor AND not yet engaged
      focused    — thread_work / arranging / creative cycle type
      thinking   — default idle

    Args:
        drives: Current DrivesState
        engagement: Current EngagementState
        room_state: Current RoomState (for activity context)
        recent_events: List of recent event dicts (most recent first),
                       each with at least 'event_type' key.
                       Typically the last ~5 events from the event log.
    """
    # surprised: unexpected event in recent events (last 2 cycle windows)
    surprise_types = {'visitor_connect', 'gift_received', 'unexpected_sound', 'anomaly'}
    for evt in recent_events[:5]:
        etype = evt.get('event_type', '')
        if etype in surprise_types:
            return 'surprised'

    # tired: energy below 30%
    if drives.energy < 0.30:
        return 'tired'

    # engaged: visitor present AND actively in conversation
    has_visitor = engagement.status == 'engaged' and engagement.visitor_id is not None
    if has_visitor:
        return 'engaged'

    # curious: visitor present but not yet engaged (browsing state)
    visitor_browsing = engagement.status != 'engaged' and engagement.visitor_id is not None
    if visitor_browsing:
        return 'curious'

    # focused: currently doing thread work, arranging, or creative cycle
    current_activity = getattr(room_state, 'current_activity', None) or ''
    if current_activity in _FOCUSED_CYCLE_TYPES:
        return 'focused'

    # thinking: default idle
    return 'thinking'


def resolve_time_of_day() -> str:
    """Resolve time-of-day from clock.py for scene compositor.

    JST-based time bands (per TASK-021b spec):
      morning   — 06:00-10:59
      afternoon — 11:00-16:59
      evening   — 17:00-19:59
      night     — 20:00-05:59

    Note: These bands differ slightly from get_time_of_day() which uses
    the legacy layer-system boundaries (morning 6-12, afternoon 12-17,
    evening 17-21, night 21-6). The compositor bands are tuned for
    outdoor scenery lighting transitions.
    """
    jst_now = clock.now()
    hour = jst_now.hour
    if 6 <= hour < 11:
        return 'morning'
    elif 11 <= hour < 17:
        return 'afternoon'
    elif 17 <= hour < 20:
        return 'evening'
    else:
        return 'night'


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
