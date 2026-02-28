"""Server-side scene compositing using Pillow.

Produces a single PNG from the layered scene definition.
Used for OG images, social preview cards, and static snapshots.
"""

import os
import re
from io import BytesIO
from pathlib import Path

from PIL import Image

ASSET_DIR = Path(os.environ.get('SHOPKEEPER_ASSET_DIR', 'assets'))
_ASSET_DIR_RESOLVED = ASSET_DIR.resolve()
OUTPUT_WIDTH = 1200
OUTPUT_HEIGHT = 630  # OG image standard 1.91:1


def _safe_asset_path(category: str, filename: str) -> Path | None:
    """Resolve an asset path and verify it stays within ASSET_DIR.

    Returns None if the filename is invalid or escapes the asset directory.
    """
    if not filename:
        return None
    # Strip traversal and unsafe characters
    safe = re.sub(
        r'[^a-zA-Z0-9_\-.]', '',
        filename.replace('/', '').replace('\\', '').replace('..', ''),
    )
    if not safe or safe.startswith('.'):
        return None
    resolved = (ASSET_DIR / category / safe).resolve()
    if not str(resolved).startswith(str(_ASSET_DIR_RESOLVED)):
        return None
    return resolved


def composite_scene(layers: dict) -> bytes:
    """Compose a scene from layer definitions into a PNG byte string.

    Args:
        layers: A dict matching SceneLayers with keys:
            background, shop, items, character, character_position, foreground

    Returns:
        PNG image bytes.
    """
    canvas = Image.new('RGBA', (OUTPUT_WIDTH, OUTPUT_HEIGHT), (10, 10, 12, 255))

    # Layer 1: Background
    _paste_layer(canvas, 'bg', layers.get('background', ''))

    # Layer 2: Shop interior
    _paste_layer(canvas, 'shop', layers.get('shop', ''))

    # Layer 3: Shelf items
    for item in layers.get('items', []):
        _paste_item(canvas, item)

    # Layer 4: Character (default anchor from legacy CHARACTER_ANCHOR constant)
    char_file = layers.get('character', '')
    if char_file:
        pos = layers.get('character_position', {})
        _paste_at(
            canvas, 'her', char_file,
            x=pos.get('x', 280),
            y=pos.get('y', 380),
            w=pos.get('width', 200),
            h=pos.get('height', 350),
        )

    # Layer 5: Foreground overlays
    for fg in layers.get('foreground', []):
        _paste_layer(canvas, 'fg', fg)

    # Convert to RGB (OG images don't need alpha)
    output = canvas.convert('RGB')
    buf = BytesIO()
    output.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def _paste_layer(canvas: Image.Image, category: str, filename: str):
    """Paste a full-canvas layer (background, shop, foreground)."""
    path = _safe_asset_path(category, filename)
    if not path or not path.exists():
        return
    try:
        layer = Image.open(path).convert('RGBA')
        layer = layer.resize((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.LANCZOS)
        canvas.alpha_composite(layer)
    except Exception as e:
        print(f'  [compositing] Failed to paste layer {filename}: {e}')


def _paste_item(canvas: Image.Image, item: dict):
    """Paste a shelf item at its specified position."""
    sprite = item.get('sprite', '')
    if not sprite:
        return
    # Scale item coordinates from scene canvas (1536x1024) to OG size (1200x630)
    sx = OUTPUT_WIDTH / 1536
    sy = OUTPUT_HEIGHT / 1024
    _paste_at(
        canvas, 'items', sprite,
        x=int(item.get('x', 0) * sx),
        y=int(item.get('y', 0) * sy),
        w=int(item.get('width', 64) * sx),
        h=int(item.get('height', 64) * sy),
    )


def _paste_at(canvas: Image.Image, category: str, filename: str,
              x: int, y: int, w: int, h: int):
    """Paste an image at a specific position and size."""
    path = _safe_asset_path(category, filename)
    if not path or not path.exists():
        return
    try:
        img = Image.open(path).convert('RGBA')
        img = img.resize((max(1, w), max(1, h)), Image.LANCZOS)
        canvas.alpha_composite(img, dest=(x, y))
    except Exception as e:
        print(f'  [compositing] Failed to paste {filename}: {e}')
