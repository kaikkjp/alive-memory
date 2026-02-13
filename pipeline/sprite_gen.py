"""Sprite Generation Queue — async, non-blocking.

New sprites are generated in the background. Never blocks a cycle.
Uses the fal.ai adapter for actual image generation.
Prompt assembly delegated to prompt_assembler (reads config/prompts.yaml).
"""

import asyncio
import os
import re
from pathlib import Path

ASSET_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets')
_ASSET_DIR_RESOLVED = Path(ASSET_DIR).resolve()


def _sanitize_filename(filename: str) -> str:
    """Strip path traversal characters and restrict to safe filename chars.

    Allows only alphanumerics, underscores, hyphens, and dots.
    Raises ValueError if the result is empty or starts with a dot.
    """
    # Remove path separators and traversal
    name = filename.replace('/', '').replace('\\', '').replace('..', '')
    # Strip to safe chars only
    name = re.sub(r'[^a-zA-Z0-9_\-.]', '', name)
    # Reject empty or hidden files
    if not name or name.startswith('.'):
        raise ValueError(f'Invalid sprite filename: {filename!r}')
    return name

GENERATION_QUEUE: asyncio.Queue = asyncio.Queue()

# Track in-flight generations to avoid duplicates
_in_flight: set[str] = set()


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


def build_sprite_prompt(params: dict) -> dict:
    """Build generation prompt from parsed params.

    Delegates to prompt_assembler which reads config/prompts.yaml.
    Returns dict with keys: filename, subdir, prompt, aspect.
    """
    from prompt_assembler import (
        assemble_background,
        assemble_shop,
        assemble_character,
        assemble_item,
        assemble_foreground,
    )

    category = params.get('category', 'unknown')

    if category == 'bg':
        return assemble_background(
            params.get('weather', 'clear'),
            params.get('time', 'afternoon'),
        )
    elif category == 'shop':
        return assemble_shop(params.get('lighting', 'warm_day'))
    elif category == 'her':
        return assemble_character(
            params.get('posture', 'sitting'),
            params.get('mood', 'calm'),
            params.get('outfit', 'apronA'),
        )
    elif category == 'items':
        return assemble_item(
            params.get('item_id', 'unknown'),
            params.get('description', 'a small antique object'),
        )
    elif category == 'fg':
        # parse_sprite_filename returns fg_type as 'fg_counter_top' etc.
        # but assemble_foreground expects 'counter_top'
        fg_type = params.get('fg_type', '')
        overlay_id = fg_type.removeprefix('fg_') if fg_type.startswith('fg_') else fg_type
        return assemble_foreground(overlay_id)
    else:
        raise ValueError(f'Unknown sprite category: {category}')


# ─── Queue operations ───

async def queue_sprite_generation(sprite_filename: str):
    """Queue a sprite for async generation. Non-blocking."""
    sprite_filename = _sanitize_filename(sprite_filename)
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
            asset = build_sprite_prompt(params)

            print(f'  [sprite_gen] Generating: {filename}')
            image_data = await generate_image(asset['prompt'], asset['aspect'])

            # Save to assets directory (with path confinement check)
            subdir = asset.get('subdir', params.get('category', 'unknown'))
            safe_name = _sanitize_filename(filename)
            filepath = Path(ASSET_DIR, subdir, safe_name).resolve()
            if not str(filepath).startswith(str(_ASSET_DIR_RESOLVED)):
                raise ValueError(f'Path escape attempt: {filename!r}')
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
    try:
        safe = _sanitize_filename(filename)
    except ValueError:
        return False
    for subdir in ('bg', 'shop', 'her', 'items', 'fg'):
        path = Path(ASSET_DIR, subdir, safe).resolve()
        if not str(path).startswith(str(_ASSET_DIR_RESOLVED)):
            continue
        if path.exists():
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
