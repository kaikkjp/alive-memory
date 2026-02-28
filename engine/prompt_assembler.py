# prompt_assembler.py
"""
Reads config/prompts.yaml and assembles complete image generation prompts.

This is the ONLY module that touches prompt text. scene.py calls this module
with structured state (posture, mood, outfit, weather, time) and gets back
a complete prompt string ready for the image API.

Flow:
  Visual Identity Doc (human reference)
       | (manual sync)
  config/prompts.yaml (machine source of truth)
       | (this module reads it)
  prompt_assembler.py
       | (returns complete prompt strings)
  image_gen.py -> API call -> PNG

Nothing else in the codebase contains prompt text for image generation.
"""

import os
import yaml
from pathlib import Path
from typing import Optional

# ── Path resolution for engine/demo split (TASK-101) ──
# Pre-move: prompt_assembler.py is at repo root, config/prompts.yaml exists
# Post-move: engine/prompt_assembler.py, prompts.yaml is at demo/config/
_ENGINE_DIR = Path(__file__).resolve().parent          # engine/ or repo root
_REPO_ROOT = _ENGINE_DIR.parent                         # repo root (if in engine/)


def _find_prompts_yaml() -> Path:
    """Locate prompts.yaml using search chain."""
    # 1. Explicit env var
    explicit = os.environ.get('AGENT_PROMPTS_YAML')
    if explicit:
        return Path(explicit)
    # 2. AGENT_CONFIG_DIR (per-agent config)
    config_dir = os.environ.get('AGENT_CONFIG_DIR')
    if config_dir:
        for sub in ('prompts.yaml', 'config/prompts.yaml'):
            p = Path(config_dir) / sub
            if p.exists():
                return p
    # 3. Module-relative config/ (pre-move layout)
    local = _ENGINE_DIR / 'config' / 'prompts.yaml'
    if local.exists():
        return local
    # 4. Repo root demo/config/ (post engine/demo split)
    demo = _REPO_ROOT / 'demo' / 'config' / 'prompts.yaml'
    if demo.exists():
        return demo
    # 5. Fallback to module-relative (will raise in load_config if missing)
    return local


_DEFAULT_CONFIG = _find_prompts_yaml()

_CONFIG: dict = {}


def load_config(path: str | Path | None = None):
    """Load the prompt config. Called once at startup.

    Args:
        path: Explicit path to prompts.yaml. Checked in order:
              AGENT_PROMPTS_YAML env → AGENT_CONFIG_DIR → config/prompts.yaml
              → demo/config/prompts.yaml
    """
    global _CONFIG
    config_path = Path(path) if path else _DEFAULT_CONFIG
    if not config_path.exists():
        raise FileNotFoundError(
            f'Prompt config not found: {config_path}. '
            f'Set AGENT_PROMPTS_YAML or AGENT_CONFIG_DIR env var, or '
            f'place prompts.yaml in config/ or demo/config/.'
        )
    with open(config_path) as f:
        _CONFIG = yaml.safe_load(f)


def _cfg() -> dict:
    """Lazy load if not yet initialized."""
    if not _CONFIG:
        load_config()
    return _CONFIG


def _f(name: str) -> str:
    """Get a fragment by name, stripped of extra whitespace."""
    return _cfg()['fragments'][name].strip()


# ─────────────────────────────────────────────
# PUBLIC API — one function per asset type
# ─────────────────────────────────────────────

def assemble_background(weather: str, time_of_day: str) -> dict:
    """
    Assemble a background prompt.

    Args:
        weather: 'clear' | 'overcast' | 'rain' | 'snow' | 'storm'
        time_of_day: 'morning' | 'afternoon' | 'evening' | 'night'

    Returns:
        {
            'filename': 'bg_tokyo_rain_afternoon.png',
            'prompt': '...',
            'aspect': '3:2',
        }
    """
    cfg = _cfg()
    weather_cfg = cfg['weather'][weather]
    weather_detail = weather_cfg['detail'][time_of_day]
    time_cfg = cfg['time_of_day'][time_of_day]

    prompt = '\n'.join([
        _f('street'),
        '',
        f"Time: {time_of_day}. {weather_detail}",
        '',
        time_cfg.get('window_note', ''),
        _f('window_view'),
        '',
        _f('style'),
        _f('palette'),
    ])

    return {
        'filename': f"bg_tokyo_{weather}_{time_of_day}.png",
        'subdir': 'bg',
        'prompt': prompt.strip(),
        'aspect': '3:2',
    }


def assemble_shop(lighting: str) -> dict:
    """
    Assemble a shop interior prompt.

    Args:
        lighting: 'warm_day' | 'soft_evening' | 'dim_night' | 'dark_sleep'

    Returns:
        {
            'filename': 'shop_warm_day.png',
            'prompt': '...',
            'aspect': '3:2',
        }
    """
    cfg = _cfg()
    lighting_desc = cfg['shop_lighting'][lighting]['description'].strip()

    prompt = '\n'.join([
        _f('shop'),
        '',
        f"Lighting: {lighting_desc}",
        '',
        _f('compositing_shop'),
        '',
        _f('style'),
        _f('palette'),
    ])

    return {
        'filename': f"shop_{lighting}.png",
        'subdir': 'shop',
        'prompt': prompt.strip(),
        'aspect': '3:2',
    }


def assemble_character(posture: str, mood: str, outfit: str) -> dict:
    """
    Assemble a character sprite prompt.

    Args:
        posture: 'reading' | 'writing' | 'standing_window' | etc.
        mood: 'calm' | 'happy' | 'melancholy' | 'curious' | 'tired'
        outfit: 'apronA' | 'casualB' | 'curatorC'

    Returns:
        {
            'filename': 'her_reading_calm_apronA.png',
            'prompt': '...',
            'aspect': '3:4',
        }

    Raises:
        ValueError if mood is not valid for the given posture.
    """
    cfg = _cfg()
    posture_cfg = cfg['postures'][posture]
    mood_cfg = cfg['moods'][mood]
    outfit_cfg = cfg['outfits'][outfit]

    # Validate combination
    if mood not in posture_cfg['valid_moods']:
        valid = posture_cfg['valid_moods']
        raise ValueError(
            f"Mood '{mood}' not valid for posture '{posture}'. "
            f"Valid moods: {valid}"
        )

    prompt = '\n'.join([
        _f('character'),
        '',
        outfit_cfg['description'].strip(),
        '',
        posture_cfg['body'].strip(),
        mood_cfg['face'].strip(),
        '',
        _f('compositing_character'),
        '',
        _f('style'),
        _f('palette'),
    ])

    return {
        'filename': f"her_{posture}_{mood}_{outfit}.png",
        'subdir': 'her',
        'prompt': prompt.strip(),
        'aspect': '3:4',
    }


def assemble_item(item_id: str, description: str) -> dict:
    """
    Assemble an item sprite prompt.

    Args:
        item_id: unique item ID, e.g. 't001'
        description: natural language, e.g. 'A small brass compass with a cracked face'

    Returns:
        {
            'filename': 'item_t001.png',
            'prompt': '...',
            'aspect': '1:1',
        }
    """
    cfg = _cfg()
    template = cfg['item_template'].strip()

    prompt = template.format(
        description=description,
        style=_f('style'),
        palette=_f('palette'),
    )

    return {
        'filename': f"item_{item_id}.png",
        'subdir': 'items',
        'prompt': prompt,
        'aspect': '1:1',
    }


def assemble_foreground(overlay_id: str) -> dict:
    """
    Assemble a foreground overlay prompt.

    Args:
        overlay_id: 'counter_top' | 'lantern_glow' | 'window_frame' | 'door_frame'

    Returns:
        {
            'filename': 'fg_counter_top.png',
            'prompt': '...',
            'aspect': '3:2',
        }
    """
    cfg = _cfg()
    fg_desc = cfg['foreground'][overlay_id]['description'].strip()

    prompt = '\n'.join([
        fg_desc,
        '',
        _f('style'),
        _f('palette'),
    ])

    return {
        'filename': f"fg_{overlay_id}.png",
        'subdir': 'fg',
        'prompt': prompt.strip(),
        'aspect': '3:2',
    }


# ─────────────────────────────────────────────
# CATALOG BUILDERS — generate full launch set
# ─────────────────────────────────────────────

def build_full_catalog() -> list[dict]:
    """
    Build the complete launch asset catalog.
    Returns a list of all assets that should exist before deploy.
    """
    catalog = []

    # 20 backgrounds
    for weather in ['clear', 'overcast', 'rain', 'snow', 'storm']:
        for time in ['morning', 'afternoon', 'evening', 'night']:
            catalog.append(assemble_background(weather, time))

    # 4 shop interiors
    for lighting in ['warm_day', 'soft_evening', 'dim_night', 'dark_sleep']:
        catalog.append(assemble_shop(lighting))

    # Character sprites — launch set (outfit A only, common combos)
    launch_sprites = [
        ('reading', 'calm'),
        ('reading', 'curious'),
        ('writing', 'calm'),
        ('writing', 'curious'),
        ('standing_window', 'calm'),
        ('standing_window', 'melancholy'),
        ('sitting', 'calm'),
        ('sitting', 'curious'),
        ('talking', 'calm'),
        ('talking', 'happy'),
        ('arranging', 'calm'),
        ('resting', 'tired'),
    ]
    for posture, mood in launch_sprites:
        catalog.append(assemble_character(posture, mood, 'apronA'))

    # 4 foreground overlays
    for overlay in ['counter_top', 'lantern_glow', 'window_frame', 'door_frame']:
        catalog.append(assemble_foreground(overlay))

    return catalog


def build_all_character_sprites(outfit: str = 'apronA') -> list[dict]:
    """
    Build ALL valid character sprite combinations for a given outfit.
    Used for complete library generation.
    """
    cfg = _cfg()
    sprites = []
    for posture_name, posture_cfg in cfg['postures'].items():
        for mood in posture_cfg['valid_moods']:
            sprites.append(assemble_character(posture_name, mood, outfit))
    return sprites


# ─────────────────────────────────────────────
# VALIDATION — check YAML integrity
# ─────────────────────────────────────────────

def validate_config() -> list[str]:
    """
    Validate the prompt config for completeness and consistency.
    Returns a list of errors (empty = valid).
    """
    cfg = _cfg()
    errors = []

    # Check all required fragments exist
    required_fragments = [
        'style', 'palette', 'character', 'shop', 'street',
        'window_view', 'compositing_character', 'compositing_shop',
    ]
    for frag in required_fragments:
        if frag not in cfg.get('fragments', {}):
            errors.append(f"Missing fragment: {frag}")

    # Check all postures have valid_moods that exist in moods
    for posture_name, posture_cfg in cfg.get('postures', {}).items():
        for mood in posture_cfg.get('valid_moods', []):
            if mood not in cfg.get('moods', {}):
                errors.append(f"Posture '{posture_name}' references unknown mood: {mood}")

    # Check weather has all time_of_day entries
    for weather_name, weather_cfg in cfg.get('weather', {}).items():
        for time in ['morning', 'afternoon', 'evening', 'night']:
            if time not in weather_cfg.get('detail', {}):
                errors.append(f"Weather '{weather_name}' missing time: {time}")

    # Check shop_lighting has all 4 variants
    for lighting in ['warm_day', 'soft_evening', 'dim_night', 'dark_sleep']:
        if lighting not in cfg.get('shop_lighting', {}):
            errors.append(f"Missing shop lighting: {lighting}")

    # Check outfits
    for outfit in ['apronA', 'casualB', 'curatorC']:
        if outfit not in cfg.get('outfits', {}):
            errors.append(f"Missing outfit: {outfit}")

    # Check item_template has {description}, {style}, {palette} placeholders
    template = cfg.get('item_template', '')
    for placeholder in ['{description}', '{style}', '{palette}']:
        if placeholder not in template:
            errors.append(f"Item template missing placeholder: {placeholder}")

    return errors


# ─────────────────────────────────────────────
# CLI — preview prompts without generating
# ─────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description='Preview or validate image prompts')
    sub = parser.add_subparsers(dest='cmd')

    # Validate
    sub.add_parser('validate', help='Check prompts.yaml for errors')

    # Preview a single prompt
    p_preview = sub.add_parser('preview', help='Preview a single assembled prompt')
    p_preview.add_argument('type', choices=['bg', 'shop', 'her', 'item', 'fg'])
    p_preview.add_argument('--weather', default='clear')
    p_preview.add_argument('--time', default='afternoon')
    p_preview.add_argument('--lighting', default='warm_day')
    p_preview.add_argument('--posture', default='reading')
    p_preview.add_argument('--mood', default='calm')
    p_preview.add_argument('--outfit', default='apronA')
    p_preview.add_argument('--item-id', default='t001')
    p_preview.add_argument('--item-desc', default='A small brass compass with a cracked face')
    p_preview.add_argument('--overlay', default='counter_top')

    # List all assets in launch catalog
    sub.add_parser('catalog', help='List all launch catalog assets')

    # Count all valid sprites
    sub.add_parser('sprites', help='List all valid character sprite combinations')

    args = parser.parse_args()

    if args.cmd == 'validate':
        errors = validate_config()
        if errors:
            print(f"{len(errors)} error(s):")
            for e in errors:
                print(f"  - {e}")
            sys.exit(1)
        else:
            print("Config valid.")

    elif args.cmd == 'preview':
        if args.type == 'bg':
            result = assemble_background(args.weather, args.time)
        elif args.type == 'shop':
            result = assemble_shop(args.lighting)
        elif args.type == 'her':
            result = assemble_character(args.posture, args.mood, args.outfit)
        elif args.type == 'item':
            result = assemble_item(args.item_id, args.item_desc)
        elif args.type == 'fg':
            result = assemble_foreground(args.overlay)

        print(f"Filename: {result['filename']}")
        print(f"Aspect:   {result['aspect']}")
        print(f"Subdir:   {result['subdir']}")
        print(f"\n--- PROMPT ---\n")
        print(result['prompt'])

    elif args.cmd == 'catalog':
        catalog = build_full_catalog()
        print(f"Launch catalog: {len(catalog)} assets\n")
        for asset in catalog:
            print(f"  {asset['subdir']}/{asset['filename']}")
        print(f"\n  Backgrounds: 20")
        print(f"  Shop:        4")
        print(f"  Character:   12 (launch set)")
        print(f"  Foreground:  4")
        print(f"  Total:       {len(catalog)}")

    elif args.cmd == 'sprites':
        sprites = build_all_character_sprites('apronA')
        print(f"All valid sprites (outfit A): {len(sprites)}\n")
        for s in sprites:
            print(f"  {s['filename']}")
        print(f"\n  x 3 outfits = {len(sprites) * 3} total possible sprites")
