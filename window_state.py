"""Window State Builder — constructs payloads for window viewers.

Builds the full state JSON for:
- Initial WebSocket connection (complete scene + text + state)
- POST-cycle broadcasts (scene update + current thought)
- REST /api/state endpoint (same as initial WS payload)

No LLM calls. All deterministic.
"""

from datetime import datetime, timezone, timedelta

import db
from pipeline.scene import build_scene_layers, get_time_of_day, resolve_sprite_state, resolve_time_of_day

JST = timezone(timedelta(hours=9))


# ─── Activity labels (diegetic, not technical) ───

_ACTIVITY_LABELS = {
    'reading':          'Reading',
    'writing':          'Writing',
    'standing_window':  'Looking out the window',
    'arranging':        'Arranging the shelf',
    'sitting':          'Thinking',
    'talking':          'Talking',
    'resting':          'Resting',
    'sleeping':         'Sleeping',
    'consume':          'Reading',
    'express':          'Writing',
    'thread':           'Following a thought',
    'news':             'Noticing something',
    'rest':             'Resting',
    'sleep':            'Sleeping',
    'idle':             'Sitting quietly',
    'micro':            'Listening',
    'ambient':          'Sitting quietly',
}


def get_activity_label(activity: str) -> str:
    """Map activity/posture to natural-language label."""
    return _ACTIVITY_LABELS.get(activity, 'Sitting quietly')


def get_time_label(dt: datetime) -> str:
    """Map datetime to single-word time label."""
    return get_time_of_day(dt).capitalize()


def extract_current_thought(cycle_log: dict) -> str:
    """Extract a display-worthy thought from cycle results.

    Priority: dialogue > internal_monologue > activity label.
    """
    dialogue = cycle_log.get('dialogue')
    if dialogue and dialogue != '...':
        return dialogue

    monologue = cycle_log.get('internal_monologue', '')
    if monologue:
        # Truncate at sentence boundary for display
        for end in ('.', '。', '—', '…'):
            idx = monologue.find(end)
            if 0 < idx < 120:
                return monologue[:idx + 1]
        if len(monologue) > 120:
            return monologue[:117] + '...'
        return monologue

    routing = cycle_log.get('routing_focus', 'idle')
    return get_activity_label(routing)


async def build_initial_state(clock_now: datetime = None) -> dict:
    """Full state payload for new WebSocket connections and REST /api/state.

    Returns the complete scene + text + state JSON as defined in spec §2.9.
    """
    if clock_now is None:
        clock_now = datetime.now(timezone.utc)

    drives = await db.get_drives_state()
    room = await db.get_room_state()
    engagement = await db.get_engagement_state()
    fragments = await db.get_recent_text_fragments(limit=8)
    shelf_items = await db.get_shelf_assignments()
    active_threads = await db.get_active_threads(limit=5)

    # Build ambient dict from room state
    ambient = {
        'condition': room.weather,
        'diegetic': _weather_diegetic(room.weather),
    }

    # Build scene layers (deterministic)
    layers = await build_scene_layers(
        drives=drives,
        ambient=ambient,
        focus=None,  # no active focus on initial load
        engagement=engagement,
        clock_now=clock_now,
        shelf_items=shelf_items,
        shop_status=room.shop_status,
    )

    # Determine status
    if room.shop_status == 'closed':
        status = 'sleeping'
    elif engagement.status == 'engaged':
        status = 'awake'
    else:
        status = 'awake'

    # Resolve scene compositor fields
    sprite_state = resolve_sprite_state(drives, engagement, room, [])
    time_of_day = resolve_time_of_day()

    return {
        'type': 'scene_update',
        'layers': layers.to_dict(),
        'text': {
            'recent_entries': [
                {
                    'content': f['content'],
                    'type': f['fragment_type'],
                    'timestamp': f['created_at'],
                }
                for f in fragments
            ],
        },
        'state': {
            'threads': _serialize_threads(active_threads),
            'weather_diegetic': ambient.get('diegetic', ''),
            'time_label': get_time_label(clock_now),
            'status': status,
            'visitor_present': engagement.status == 'engaged',
            'sprite_state': sprite_state,
            'time_of_day': time_of_day,
        },
        'timestamp': clock_now.isoformat(),
    }


async def build_cycle_broadcast(
    cycle_log: dict,
    drives,
    ambient: dict | None,
    focus,
    engagement,
    clock_now: datetime,
    shelf_items: list[dict] | None = None,
    shop_status: str = 'open',
) -> dict:
    """Build a scene_update message for post-cycle broadcast.

    Lighter than build_initial_state — uses cycle_log for text.
    """
    active_threads = await db.get_active_threads(limit=5)

    layers = await build_scene_layers(
        drives=drives,
        ambient=ambient,
        focus=focus,
        engagement=engagement,
        clock_now=clock_now,
        shelf_items=shelf_items,
        shop_status=shop_status,
    )

    # Resolve scene compositor fields
    room = await db.get_room_state()
    recent_events = await db.get_recent_events(limit=5)
    recent_event_dicts = [
        {'event_type': getattr(e, 'event_type', ''), 'ts': getattr(e, 'ts', '')}
        for e in recent_events
    ]
    sprite_state = resolve_sprite_state(drives, engagement, room, recent_event_dicts)
    time_of_day = resolve_time_of_day()

    return {
        'type': 'scene_update',
        'layers': layers.to_dict(),
        'text': {
            'current_thought': extract_current_thought(cycle_log),
            'activity_label': get_activity_label(
                cycle_log.get('routing_focus', 'idle')
            ),
        },
        'state': {
            'threads': _serialize_threads(active_threads),
            'weather_diegetic': (
                ambient.get('diegetic', '') if ambient else ''
            ),
            'time_label': get_time_label(clock_now),
            'status': 'sleeping' if shop_status == 'closed' else 'awake',
            'visitor_present': engagement.status == 'engaged',
            'sprite_state': sprite_state,
            'time_of_day': time_of_day,
        },
        'timestamp': clock_now.isoformat(),
    }


def build_text_fragment_message(content: str, fragment_type: str,
                                  timestamp: str = None) -> dict:
    """Build a text_fragment WebSocket message."""
    return {
        'type': 'text_fragment',
        'content': content,
        'fragment_type': fragment_type,
        'timestamp': timestamp or datetime.now(timezone.utc).isoformat(),
    }


def build_item_added_message(item: dict, timestamp: str = None) -> dict:
    """Build an item_added WebSocket message for shelf animation."""
    return {
        'type': 'item_added',
        'item': item,
        'timestamp': timestamp or datetime.now(timezone.utc).isoformat(),
    }


def build_status_message(status: str, message: str) -> dict:
    """Build a status WebSocket message (sleep/wake)."""
    return {
        'type': 'status',
        'status': status,
        'message': message,
    }


# ─── Helpers ───

def _serialize_threads(threads) -> list[dict]:
    """Serialize Thread objects to ThreadInfo dicts for the frontend."""
    return [
        {
            'id': t.id,
            'title': t.title,
            'status': t.status,
        }
        for t in threads
    ]


def _weather_diegetic(weather: str) -> str:
    """Convert weather code to diegetic description."""
    descriptions = {
        'clear':    'Clear skies outside.',
        'overcast': 'Grey sky through the window.',
        'rain':     'Rain on the windows.',
        'snow':     'Snow falling outside.',
        'storm':    'A storm outside. The shop feels smaller.',
    }
    return descriptions.get(weather, '')
