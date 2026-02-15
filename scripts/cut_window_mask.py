"""Prepare shop interior image from shop-back.png.

For the initial version, this copies the full shop-back.png as the
shop interior layer. Future iterations may add window transparency
masks so outdoor scenery shows through the window regions.

Usage:
    python scripts/cut_window_mask.py
"""

import os
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("[cut_window_mask] Pillow is required: pip install Pillow")
    sys.exit(1)

# Resolve paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE = PROJECT_ROOT / "assets" / "shop-back.png"
OUTPUT_DIR = PROJECT_ROOT / "window" / "public" / "assets"
OUTPUT = OUTPUT_DIR / "shop_interior.png"


def main() -> None:
    if not SOURCE.exists():
        print(f"[cut_window_mask] Source not found: {SOURCE}")
        sys.exit(1)

    img = Image.open(SOURCE).convert("RGBA")
    width, height = img.size

    print(f"[cut_window_mask] Source: {width}x{height}")
    print("[cut_window_mask] NOTE: Window regions are not yet masked.")
    print("[cut_window_mask]       Outdoor scenery layer won't show through")
    print("[cut_window_mask]       until window alpha masks are painted manually.")

    # Save full image as shop interior (future: apply window mask)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    img.save(OUTPUT, "PNG")
    print(f"[cut_window_mask] Saved: {OUTPUT} ({os.path.getsize(OUTPUT)} bytes)")


if __name__ == "__main__":
    main()
