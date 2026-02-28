#!/usr/bin/env python3
"""
Generate the launch asset library.

Usage:
    python bootstrap_assets.py                  # Generate all missing launch assets
    python bootstrap_assets.py --all-sprites    # Generate ALL valid sprites (not just launch set)
    python bootstrap_assets.py --dry-run        # Preview what would be generated
    python bootstrap_assets.py --only bg        # Only generate backgrounds
    python bootstrap_assets.py --only her       # Only generate character sprites

Reads prompts from config/prompts.yaml via prompt_assembler.py.
Visual Identity Document (visual-identity.md) is the human reference.
"""

import asyncio
import argparse
import os
import sys
from pathlib import Path

from prompt_assembler import (
    load_config,
    validate_config,
    build_full_catalog,
    build_all_character_sprites,
)
from pipeline.image_gen import generate_image

ASSET_DIR = os.environ.get('ASSET_DIR', 'assets')


async def bootstrap(args):
    # Load and validate config
    load_config()
    errors = validate_config()
    if errors:
        print(f"Config errors — fix before generating:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("Config valid.\n")

    # Build catalog
    if args.all_sprites:
        catalog = build_full_catalog()
        # Replace launch sprites with all valid sprites
        catalog = [a for a in catalog if a['subdir'] != 'her']
        catalog.extend(build_all_character_sprites('apronA'))
        # Uncomment when ready:
        # catalog.extend(build_all_character_sprites('casualB'))
        # catalog.extend(build_all_character_sprites('curatorC'))
    else:
        catalog = build_full_catalog()

    # Filter by subdir if --only specified
    if args.only:
        subdir_map = {
            'bg': 'bg', 'backgrounds': 'bg',
            'shop': 'shop',
            'her': 'her', 'character': 'her', 'sprites': 'her',
            'fg': 'fg', 'foreground': 'fg',
            'items': 'items',
        }
        target = subdir_map.get(args.only)
        if not target:
            print(f"Unknown asset type: {args.only}")
            print(f"Valid: bg, shop, her, fg, items")
            return
        catalog = [a for a in catalog if a['subdir'] == target]

    # Summary
    by_type = {}
    for a in catalog:
        by_type.setdefault(a['subdir'], []).append(a)

    print(f"Asset catalog: {len(catalog)} total")
    for subdir, assets in sorted(by_type.items()):
        print(f"  {subdir}: {len(assets)}")
    print()

    # Check existing
    existing = 0
    missing = []
    for asset in catalog:
        filepath = Path(ASSET_DIR) / asset['subdir'] / asset['filename']
        if filepath.exists():
            existing += 1
        else:
            missing.append(asset)

    print(f"Existing: {existing}")
    print(f"To generate: {len(missing)}")
    print()

    if not missing:
        print("Nothing to generate. Library complete.")
        return

    if args.dry_run:
        print("--- DRY RUN --- Would generate:\n")
        for asset in missing:
            print(f"  {asset['subdir']}/{asset['filename']}")
            if args.verbose:
                print(f"    Prompt preview: {asset['prompt'][:120]}...")
                print()
        return

    # Generate
    generated = 0
    failed = 0

    for i, asset in enumerate(missing, 1):
        filepath = Path(ASSET_DIR) / asset['subdir'] / asset['filename']
        filepath.parent.mkdir(parents=True, exist_ok=True)

        print(f"[{i}/{len(missing)}] Generating: {asset['subdir']}/{asset['filename']}...")

        try:
            image_data = await generate_image(
                prompt=asset['prompt'],
                aspect=asset.get('aspect', '3:2'),
            )

            with open(filepath, 'wb') as f:
                f.write(image_data)

            generated += 1
            size_kb = len(image_data) / 1024
            print(f"         {size_kb:.0f}KB")

            # Rate limit between API calls
            await asyncio.sleep(2)

        except Exception as e:
            failed += 1
            print(f"         FAILED: {e}")

    # Summary
    print(f"\n{'=' * 40}")
    print(f"BOOTSTRAP COMPLETE")
    print(f"{'=' * 40}")
    print(f"Generated:  {generated}")
    print(f"Failed:     {failed}")
    print(f"Previously: {existing}")
    print(f"Total:      {existing + generated}/{len(catalog)}")

    if failed:
        print(f"\nRe-run to retry failed assets (existing ones are skipped).")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Bootstrap the asset library')
    parser.add_argument('--all-sprites', action='store_true',
                        help='Generate ALL valid sprites, not just launch set')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview without generating')
    parser.add_argument('--only', type=str, default=None,
                        help='Only generate one type: bg, shop, her, fg')
    parser.add_argument('--verbose', action='store_true',
                        help='Show prompt previews in dry run')
    asyncio.run(bootstrap(parser.parse_args()))
