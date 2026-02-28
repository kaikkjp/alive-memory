#!/usr/bin/env python3
"""CLI ingestion tool — add content to the pool manually.

Usage:
    python ingest.py content/readings.txt          # bulk load from file
    python ingest.py --url "https://example.com"    # single URL
    python ingest.py --quote "Some quote text"      # single quote
    python ingest.py --url "..." --tags "music,art" # with tags
    python ingest.py --status                       # show pool stats
"""

import argparse
import asyncio
import sys

import db
from feed_ingester import compute_pool_fingerprint, ingest_from_file


async def ingest_single(content: str, source_type: str, tags: list[str]):
    """Add a single item to the pool."""
    fingerprint = compute_pool_fingerprint('manual', source_type, content)

    title = content[:80]
    if source_type == 'url':
        from pipeline.enrich import fetch_url_metadata
        meta = await fetch_url_metadata(content)
        title = meta.get('title', content[:80])

    result = await db.add_to_content_pool(
        fingerprint=fingerprint,
        source_type=source_type,
        source_channel='manual',
        content=content,
        title=title,
        metadata={},
        tags=tags,
        ttl_hours=None,  # manual items don't expire
    )

    if result:
        print(f"  Added: {title}")
    else:
        print(f"  Already exists (duplicate fingerprint)")


async def show_status():
    """Show pool statistics."""
    stats = await db.get_pool_stats()
    total = sum(stats.values())

    print(f"\n  Content Pool ({total} items)")
    print(f"  ─────────────────────────")
    for status, count in sorted(stats.items()):
        print(f"  {status:<12} {count}")
    print()


async def main():
    parser = argparse.ArgumentParser(description='Ingest content into the pool')
    parser.add_argument('file', nargs='?', help='File path for bulk ingestion')
    parser.add_argument('--url', help='Single URL to ingest')
    parser.add_argument('--quote', help='Single quote/text to ingest')
    parser.add_argument('--tags', help='Comma-separated tags', default='')
    parser.add_argument('--status', action='store_true', help='Show pool stats')
    args = parser.parse_args()

    await db.init_db()

    tags = [t.strip() for t in args.tags.split(',') if t.strip()] if args.tags else []

    if args.status:
        await show_status()
    elif args.url:
        await ingest_single(args.url, 'url', tags)
    elif args.quote:
        await ingest_single(args.quote, 'text', tags)
    elif args.file:
        count = await ingest_from_file(args.file, tags)
        print(f"  Ingested {count} new items from {args.file}")
    else:
        parser.print_help()
        sys.exit(1)

    await db.close_db()


if __name__ == '__main__':
    asyncio.run(main())
