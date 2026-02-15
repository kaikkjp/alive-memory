"""Slice counter foreground from shop-back.png.

Produces an RGBA PNG where everything above y=72% of the image is
transparent, with a 6px vertical fade at the cut edge. The result is
the counter/foreground layer that occludes the character's lower body.

Usage:
    python scripts/slice_counter.py
"""

import os
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("[slice_counter] Pillow is required: pip install Pillow")
    sys.exit(1)

# Resolve paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE = PROJECT_ROOT / "assets" / "shop-back.png"
OUTPUT_DIR = PROJECT_ROOT / "window" / "public" / "assets"
OUTPUT = OUTPUT_DIR / "counter_foreground.png"

COUNTER_CUT_PCT = 0.72
FADE_PX = 6


def main() -> None:
    if not SOURCE.exists():
        print(f"[slice_counter] Source not found: {SOURCE}")
        sys.exit(1)

    img = Image.open(SOURCE).convert("RGBA")
    width, height = img.size
    cut_y = int(height * COUNTER_CUT_PCT)

    print(f"[slice_counter] Source: {width}x{height}, cut at y={cut_y} ({COUNTER_CUT_PCT*100:.0f}%)")

    # Get pixel data
    pixels = img.load()

    # Make everything above the cut fully transparent
    for y in range(cut_y):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            pixels[x, y] = (r, g, b, 0)

    # Apply fade zone: gradual alpha from 0 to original over FADE_PX rows
    for dy in range(FADE_PX):
        y = cut_y + dy
        if y >= height:
            break
        fade_factor = dy / FADE_PX
        for x in range(width):
            r, g, b, a = pixels[x, y]
            pixels[x, y] = (r, g, b, int(a * fade_factor))

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    img.save(OUTPUT, "PNG")
    print(f"[slice_counter] Saved: {OUTPUT} ({os.path.getsize(OUTPUT)} bytes)")


if __name__ == "__main__":
    main()
