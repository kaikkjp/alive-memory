"""Sprite Generation Queue — async, non-blocking.

New sprites are generated in the background. Never blocks a cycle.
Uses the Gemini Imagen adapter for actual image generation.
"""

import asyncio
import os
from pathlib import Path

ASSET_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets')

GENERATION_QUEUE: asyncio.Queue = asyncio.Queue()

# Track in-flight generations to avoid duplicates
_in_flight: set[str] = set()


# ─── Prompt Templates (from spec §1.2-1.5) ───

TIME_DETAIL = {
    'morning':   'Early light, long shadows on the narrow street. A few people walking.',
    'afternoon': 'Full daylight, warm. A bicycle parked against a wall.',
    'evening':   'Golden hour fading to blue. Shop signs beginning to glow.',
    'night':     'Dark street, puddles of light from vending machines and distant signs.',
}

WEATHER_DETAIL = {
    'clear':    'Clear sky. Sharp light.',
    'overcast': 'Grey sky, flat diffused light. Everything looks muted.',
    'rain':     'Rain streaks the glass. The street glistens. Umbrellas.',
    'snow':     'Snow falling gently. The street is hushed. White edges on everything.',
    'storm':    'Heavy rain. The street is empty. Water running along the curb.',
}

LIGHTING_DESCRIPTIONS = {
    'warm_day':     'Warm natural daylight filling the shop through the window. Everything looks golden.',
    'soft_evening': 'Soft amber light from paper lanterns. Outside is turning blue.',
    'dim_night':    'Low warm light. The lanterns are the main light source. Cozy and quiet.',
    'dark_sleep':   'Nearly dark. Only a faint glow from a lamp in the back room.',
}

POSTURE_DESCRIPTIONS = {
    'reading':          'sitting at a wooden counter, leaning slightly over an open book, one hand resting on the page',
    'writing':          'sitting at a wooden counter, writing in a small journal with a pen, head slightly tilted',
    'standing_window':  'standing by a window, hands loosely clasped behind her back, looking outward',
    'arranging':        'reaching toward a shelf, carefully adjusting the position of a small object',
    'sitting':          'sitting still on a wooden stool behind the counter, hands in her lap, eyes unfocused',
    'talking':          'leaning slightly forward across the counter, one hand gesturing gently, making eye contact',
    'resting':          'resting her head on her folded arms on the counter, eyes half-closed',
    'sleeping':         'not visible — the shop is dark, only a faint light from the back room',
}

MOOD_DESCRIPTIONS = {
    'calm':       'calm, neutral, at rest — a quiet presence',
    'happy':      'a slight smile, warmth in the eyes, something gentle',
    'melancholy': 'a distant look, not sad but contemplative, as if remembering something',
    'curious':    'eyes slightly wider, head tilted, engaged with something interesting',
    'tired':      'heavy eyelids, shoulders slightly low, the weight of a long day',
}

OUTFIT_DESCRIPTIONS = {
    'apronA': 'a dark indigo work apron over a cream-colored long-sleeve shirt, sleeves rolled up',
    'casualB': 'a loose grey cardigan over a white tee, comfortable and relaxed',
    'coatC': 'a dark wool coat, as if she just came in from outside or is about to leave',
}


def _build_bg_prompt(location: str, weather: str, time: str) -> str:
    time_detail = TIME_DETAIL.get(time, '')
    weather_detail = WEATHER_DETAIL.get(weather, '')
    return (
        f'A view through a shop window in a quiet Tokyo side street. '
        f'{time.capitalize()}, {weather}. '
        f'{time_detail} {weather_detail} '
        f'The view is from inside looking out — the window frame is visible at the edges. '
        f'Style: soft illustration, muted warm palette, Studio Ghibli atmosphere, slight grain, 16:9. '
        f'Consistent with a series — same street, same angle, different conditions.'
    )


def _build_shop_prompt(lighting: str) -> str:
    lighting_desc = LIGHTING_DESCRIPTIONS.get(lighting, LIGHTING_DESCRIPTIONS['warm_day'])
    return (
        f'Interior of a small, cluttered antique shop in Tokyo. Warm wooden shelves along the walls, '
        f'a wooden counter with a brass cash register, paper lanterns hanging from the ceiling. '
        f'Curious objects on shelves — old cameras, ceramic figures, brass instruments, glass bottles. '
        f'{lighting_desc}. '
        f'The shop window is visible on the left wall (leave this area semi-transparent for compositing). '
        f'There are 16 clearly visible empty spaces on the shelves where objects could be placed. '
        f'The counter area is clear for a character to stand/sit behind. '
        f'Style: soft illustration, muted warm palette, Studio Ghibli atmosphere, slight grain, 16:9. '
        f'Top-down slight angle, as if viewed from just inside the doorway.'
    )


def _build_character_prompt(posture: str, mood: str, outfit: str) -> str:
    posture_desc = POSTURE_DESCRIPTIONS.get(posture, POSTURE_DESCRIPTIONS['sitting'])
    mood_desc = MOOD_DESCRIPTIONS.get(mood, MOOD_DESCRIPTIONS['calm'])
    outfit_desc = OUTFIT_DESCRIPTIONS.get(outfit, OUTFIT_DESCRIPTIONS['apronA'])
    return (
        f'A young Japanese woman with short dark hair and quiet eyes, {posture_desc}. '
        f'She wears {outfit_desc}. Her expression is {mood_desc}. '
        f'Full body, positioned as if behind a shop counter in a small antique shop. '
        f'Transparent background. Consistent character across all images in the series. '
        f'Style: soft illustration, muted warm palette, Studio Ghibli atmosphere. '
        f'Same character as reference — maintain face, hair, body proportions exactly.'
    )


def _build_item_prompt(description: str) -> str:
    return (
        f'A single {description}. Small object, centered on transparent background. '
        f'Style: soft illustration, warm palette, consistent with antique shop aesthetic. '
        f'Studio Ghibli style object. Slight shadow beneath. 80x80 pixels effective size.'
    )


def _build_fg_prompt(fg_type: str) -> str:
    prompts = {
        'fg_counter_top': (
            'A wooden shop counter surface viewed from slightly above. '
            'Transparent except for the counter itself. '
            'Style: soft illustration, warm wood tones, Studio Ghibli atmosphere.'
        ),
        'fg_lantern_glow': (
            'Warm golden light bloom from paper lanterns. '
            'Semi-transparent overlay effect. '
            'Style: soft illustration, warm amber glow, subtle and atmospheric.'
        ),
        'fg_window_frame': (
            'A wooden window frame, viewing from inside a shop. '
            'The frame borders visible at the edges, interior transparent. '
            'Style: soft illustration, dark wood, Studio Ghibli atmosphere.'
        ),
    }
    return prompts.get(fg_type, f'Decorative foreground element: {fg_type}')


# ─── Filename parsing ───

def parse_sprite_filename(filename: str) -> dict:
    """Parse sprite filename to generation params.

    Examples:
        'her_reading_calm_apronA.png' → {category: 'her', posture: 'reading', mood: 'calm', outfit: 'apronA'}
        'bg_tokyo_rain_morning.png' → {category: 'bg', location: 'tokyo', weather: 'rain', time: 'morning'}
        'item_t001_brass_compass.png' → {category: 'items', item_id: 't001', description: 'brass compass'}
        'shop_warm_day.png' → {category: 'shop', lighting: 'warm_day'}
        'fg_counter_top.png' → {category: 'fg', fg_type: 'fg_counter_top'}
    """
    name = filename.replace('.png', '')
    parts = name.split('_')

    if parts[0] == 'her':
        # Handle multi-word postures like 'standing_window'
        # Format: her_{posture}_{mood}_{outfit}.png
        # Outfit is always the last part, mood is second-to-last
        outfit = parts[-1]
        mood = parts[-2]
        posture = '_'.join(parts[1:-2])
        return {
            'category': 'her',
            'posture': posture,
            'mood': mood,
            'outfit': outfit,
        }
    elif parts[0] == 'bg':
        return {
            'category': 'bg',
            'location': parts[1],
            'weather': parts[2],
            'time': parts[3],
        }
    elif parts[0] == 'shop':
        return {
            'category': 'shop',
            'lighting': '_'.join(parts[1:]),
        }
    elif parts[0] == 'item':
        return {
            'category': 'items',
            'item_id': parts[1],
            'description': ' '.join(parts[2:]) if len(parts) > 2 else 'unknown object',
        }
    elif parts[0] == 'fg':
        return {
            'category': 'fg',
            'fg_type': name,
        }
    return {'category': 'unknown', 'filename': filename}


def build_sprite_prompt(params: dict) -> tuple[str, str]:
    """Build generation prompt from parsed params. Returns (prompt, aspect_ratio)."""
    category = params.get('category', 'unknown')

    if category == 'bg':
        return _build_bg_prompt(
            params.get('location', 'tokyo'),
            params.get('weather', 'clear'),
            params.get('time', 'afternoon'),
        ), '16:9'
    elif category == 'shop':
        return _build_shop_prompt(params.get('lighting', 'warm_day')), '16:9'
    elif category == 'her':
        return _build_character_prompt(
            params.get('posture', 'sitting'),
            params.get('mood', 'calm'),
            params.get('outfit', 'apronA'),
        ), '3:4'
    elif category == 'items':
        return _build_item_prompt(params.get('description', 'a small antique object')), '1:1'
    elif category == 'fg':
        return _build_fg_prompt(params.get('fg_type', '')), '16:9'
    else:
        raise ValueError(f'Unknown sprite category: {category}')


# ─── Queue operations ───

async def queue_sprite_generation(sprite_filename: str):
    """Queue a sprite for async generation. Non-blocking."""
    if sprite_filename in _in_flight:
        return  # already queued
    if sprite_exists(sprite_filename):
        return  # already generated
    _in_flight.add(sprite_filename)
    await GENERATION_QUEUE.put(sprite_filename)


async def sprite_gen_worker():
    """Background worker that generates sprites from queue.

    Start alongside heartbeat:
        asyncio.create_task(sprite_gen_worker())
    """
    # Lazy import to avoid circular dependency at module level
    from pipeline.image_gen import generate_image

    while True:
        filename = await GENERATION_QUEUE.get()
        try:
            if sprite_exists(filename):
                continue  # race condition guard

            params = parse_sprite_filename(filename)
            prompt, aspect_ratio = build_sprite_prompt(params)

            print(f'  [sprite_gen] Generating: {filename}')
            image_data = await generate_image(prompt, aspect_ratio)

            # Save to assets directory
            subdir = params.get('category', 'unknown')
            filepath = os.path.join(ASSET_DIR, subdir, filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'wb') as f:
                f.write(image_data)

            print(f'  [sprite_gen] Generated: {filename}')
        except Exception as e:
            print(f'  [sprite_gen] Failed: {filename} — {e}')
        finally:
            _in_flight.discard(filename)
            GENERATION_QUEUE.task_done()


# ─── Existence check + fallback ───

def sprite_exists(filename: str) -> bool:
    """Check if sprite already exists in library."""
    for subdir in ('bg', 'shop', 'her', 'items', 'fg'):
        if Path(ASSET_DIR, subdir, filename).exists():
            return True
    return False


def get_fallback_sprite(activity: str) -> str:
    """Return nearest valid sprite that exists. Always returns something."""
    from pipeline.scene import ACTIVITY_TO_POSTURE

    posture = ACTIVITY_TO_POSTURE.get(activity, 'standing_window')
    candidates = [
        f'her_{posture}_calm_apronA.png',
        'her_standing_window_calm_apronA.png',
        'her_reading_calm_apronA.png',
    ]
    for c in candidates:
        if sprite_exists(c):
            return c
    # Absolute fallback — even if file doesn't exist, return this name
    # (frontend handles missing images gracefully)
    return 'her_standing_window_calm_apronA.png'
