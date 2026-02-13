"""Feed Ingester — fetches content from RSS/file sources into the content pool.

Runs as a periodic task inside heartbeat or as a standalone import.
Idempotent: duplicate content is ignored via fingerprint uniqueness.
"""

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import db

logger = logging.getLogger(__name__)


def compute_pool_fingerprint(source_channel: str, source_type: str, content: str) -> str:
    """Compute a deterministic fingerprint for deduplication.

    Canonicalizes: strip UTM params from URLs, lowercase, collapse whitespace.
    """
    canonical = canonicalize_content(source_type, content)
    raw = f"{source_channel}|{source_type}|{canonical}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def canonicalize_content(source_type: str, content: str) -> str:
    """Normalize content for fingerprinting."""
    if source_type == 'url':
        # Strip UTM and tracking params
        content = re.sub(r'[?&](utm_\w+|ref|source|fbclid|gclid)=[^&]*', '', content)
        # Remove trailing ? or & left over
        content = content.rstrip('?&')
    # Lowercase, collapse whitespace
    content = content.lower().strip()
    content = re.sub(r'\s+', ' ', content)
    return content


async def ingest_from_file(filepath: str, tags: list[str] = None) -> int:
    """Ingest URLs/quotes from a text file (one per line).

    Returns number of new items added (skips duplicates).
    """
    import pathlib
    path = pathlib.Path(filepath)
    if not path.exists():
        logger.warning("Feed file not found: %s", filepath)
        return 0

    lines = [l.strip() for l in path.read_text().splitlines() if l.strip() and not l.startswith('#')]
    added = 0

    for line in lines:
        is_url = bool(re.match(r'https?://', line))
        source_type = 'url' if is_url else 'text'
        fingerprint = compute_pool_fingerprint('file', source_type, line)

        title = line[:80] if not is_url else ''
        if is_url:
            # Try to extract a clean title from the URL path
            parts = line.rstrip('/').rsplit('/', 1)
            title = parts[-1].replace('-', ' ').replace('_', ' ')[:80] if len(parts) > 1 else line[:80]

        result = await db.add_to_content_pool(
            fingerprint=fingerprint,
            source_type=source_type,
            source_channel='file',
            content=line,
            title=title,
            metadata={},
            tags=tags or [],
            ttl_hours=None,  # curated content doesn't expire
        )
        if result:
            added += 1

    return added


async def ingest_from_rss(feed_url: str, tags: list[str] = None) -> int:
    """Ingest items from an RSS feed.

    Requires feedparser: pip install feedparser
    Returns number of new items added.
    """
    try:
        import feedparser
    except ImportError:
        logger.warning("feedparser not installed. Run: pip install feedparser")
        return 0

    try:
        feed = feedparser.parse(feed_url)
    except Exception as e:
        logger.warning("RSS fetch failed for %s: %s", feed_url, e)
        return 0

    added = 0
    for entry in feed.entries[:20]:  # cap at 20 per fetch
        link = entry.get('link', '')
        title = entry.get('title', '')

        if not link and not title:
            continue

        content = link or title
        source_type = 'url' if link else 'rss_headline'
        fingerprint = compute_pool_fingerprint('rss', source_type, content)

        metadata = {}
        if entry.get('summary'):
            metadata['description'] = entry.summary[:300]
        if entry.get('author'):
            metadata['author'] = entry.author

        result = await db.add_to_content_pool(
            fingerprint=fingerprint,
            source_type=source_type,
            source_channel='rss',
            content=content,
            title=title[:200],
            metadata=metadata,
            tags=tags or [],
            ttl_hours=4.0,  # headlines expire in 4 hours
        )
        if result:
            added += 1

    return added


async def run_feed_ingestion() -> int:
    """Run one pass of all configured feed sources.

    Returns total items added.
    """
    from config.feeds import FEED_SOURCES

    total = 0
    for source in FEED_SOURCES:
        try:
            if source['type'] == 'file':
                count = await ingest_from_file(source['path'], source.get('tags', []))
            elif source['type'] == 'rss':
                count = await ingest_from_rss(source['url'], source.get('tags', []))
            else:
                logger.warning("Unknown feed type: %s", source['type'])
                continue
            total += count
            if count > 0:
                logger.info("Ingested %d items from %s", count, source.get('url', source.get('path', '?')))
        except Exception as e:
            logger.warning("Feed source error: %s — %s", source, e)

    return total
